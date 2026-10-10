"""Sentinel-1 change detection: sees through monsoon cloud.

Method
  1. For every orbit track that has an image after the event, take the first post-event image and
     up to N_PRE earlier images *of the same track* (same viewing geometry, 12-day repeat).
  2. 5x5 boxcar multilook (OpenCV) in linear power, then dB.
  3. Per-pixel z-score of the post image against the pre-event stack mean / std. A pixel that
     normally fluctuates (vegetation, wet soil) needs a larger change to count than a stable one.
     Debris both brightens (rough boulders) and darkens (smooth mud, water), so we use |z|.
  4. Pixels in radar layover / shadow for that track are excluded.
  5. Open water: VV and VH both below fixed dark thresholds (standard calm-water signature).
Tracks and polarisations are averaged, so the result uses every independent look available.
"""
from dataclasses import dataclass, field
from datetime import timedelta

import cv2
import numpy as np

from .providers.base import as_utc
from .readers import prefetch, read
from .terrain import radar_blind

N_PRE = 5
LOOK = 5               # multilook window (pixels)
SD_FLOOR_DB = 0.75     # minimum temporal std, so very stable pixels don't explode the z-score
WATER_VV_DB = -18.0
WATER_VH_DB = -25.0


@dataclass
class SarResult:
    z: np.ndarray                     # mean |z| over tracks/pols (nan where never visible)
    looks: np.ndarray                 # number of track-pol looks contributing per pixel
    water_post: np.ndarray
    water_pre: np.ndarray
    post_vv_db: np.ndarray
    scenes: list = field(default_factory=list)   # provenance: what was used


def _db(lin):
    a = np.nan_to_num(lin, nan=0.0).astype("float32")
    valid = cv2.blur((lin > 0).astype("float32"), (LOOK, LOOK)) > 0.5
    a = cv2.blur(a, (LOOK, LOOK))
    out = 10 * np.log10(np.maximum(a, 1e-6))
    out[~valid] = np.nan
    return out


def _orbit_state(scene, lon):
    if scene.orbit_state:
        return scene.orbit_state
    # Sentinel-1 passes ~06:00 local solar time descending, ~18:00 ascending.
    local = (scene.datetime.hour + scene.datetime.minute / 60 + lon / 15) % 24
    return "descending" if local < 12 else "ascending"


def change(provider, grid, event, terrain: dict, max_post_days=24) -> SarResult:
    event = as_utc(event)
    w, s, e, n = grid.bbox
    lon = (w + e) / 2
    scenes = provider.search_around("sentinel-1-rtc", grid.bbox, event, days_before=12 * N_PRE + 6,
                                    days_after=max_post_days)
    tracks: dict = {}
    for sc in scenes:
        tracks.setdefault(sc.track_key, []).append(sc)

    zsum = np.zeros(grid.shape, "float32")
    looks = np.zeros(grid.shape, "int16")
    water_post = np.zeros(grid.shape, bool)
    water_pre = np.zeros(grid.shape, bool)
    post_vv = np.full(grid.shape, np.nan, "float32")
    used = []
    # earliest post image first, so the "post" water map reflects the earliest look
    order = sorted(tracks.values(), key=lambda L: min((x.datetime for x in L if x.datetime >= event),
                                                       default=event + timedelta(days=99)))
    for L in order:
        pre = sorted((x for x in L if x.datetime < event), key=lambda x: x.datetime)[-N_PRE:]
        post = [x for x in L if x.datetime >= event]
        if not pre or not post:
            continue
        post = min(post, key=lambda x: x.datetime)
        state = _orbit_state(post, lon)
        blind = radar_blind(terrain["slope"], terrain["aspect"], state)
        rec = {"track": str(post.track_key), "orbit": state, "post": post.scene_id,
               "post_time": f"{post.datetime:%Y-%m-%d %H:%M}Z", "pre": [p.scene_id for p in pre],
               "provider": post.provider}
        db = {}
        for b in ("vv", "vh"):
            prefetch(provider, [(x, b) for x in pre + [post]], grid)
            P = np.stack([_db(read(provider, x, b, grid)) for x in pre])
            q = _db(read(provider, post, b, grid))
            mu = np.nanmean(P, 0)
            sd = np.maximum(np.nanstd(P, 0), SD_FLOOR_DB) if len(pre) >= 3 else np.full_like(mu, 1.5)
            z = np.abs(q - mu) / sd
            ok = np.isfinite(z) & ~blind
            zsum[ok] += z[ok]
            looks[ok] += 1
            db[b] = (mu, q)
        wpost = (db["vv"][1] < WATER_VV_DB) & (db["vh"][1] < WATER_VH_DB) & ~blind
        wpre = (db["vv"][0] < WATER_VV_DB) & (db["vh"][0] < WATER_VH_DB) & ~blind
        if not used:  # earliest post-event look defines the water maps
            water_post, water_pre, post_vv = wpost, wpre, db["vv"][1]
        rec["blind_pct"] = round(float(blind.mean() * 100), 1)
        used.append(rec)
    if not used:
        raise RuntimeError("No Sentinel-1 track has both pre- and post-event images for this area/date")
    z = np.where(looks > 0, zsum / np.maximum(looks, 1), np.nan).astype("float32")
    return SarResult(z, looks, water_post, water_pre, post_vv, used)
