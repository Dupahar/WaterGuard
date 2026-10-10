"""Sentinel-2 change detection, used wherever the sky was clear before and after.

Monsoon cloud rarely leaves one clean image, so we build per-pixel cloud-free median composites
(Scene Classification Layer: keep vegetation, bare soil, water, dark-area and unclassified;
drop cloud, cirrus, cloud shadow, snow, saturated, nodata) over a window before and after the event.
Debris and scour strip vegetation (NDVI falls) and leave wet sediment or water (NDWI rises).
"""
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
from rasterio.enums import Resampling

from .providers.base import as_utc
from .readers import prefetch, read

CLEAR_SCL = (2, 4, 5, 6, 7, 11)
PRE_DAYS = 45
POST_DAYS = 40
MIN_CLEAR_FRAC = 0.02   # skip scenes that are essentially all cloud over the area
MAX_SCENES = 8          # clearest scenes kept per composite (bounds memory on large areas)
MAX_TILE_CLOUD = 95.0   # skip scenes whose whole tile is almost entirely cloud (saves downloads)


@dataclass
class OpticalResult:
    ndvi_pre: np.ndarray
    ndvi_post: np.ndarray
    ndwi_pre: np.ndarray
    ndwi_post: np.ndarray
    clear: np.ndarray            # both composites have at least one clear look
    rgb_post: np.ndarray | None  # 3 x H x W reflectance, for the dashboard
    rgb_pre: np.ndarray | None
    scenes: list = field(default_factory=list)


def _composite(provider, scenes, grid):
    """Per-pixel median of clear-sky looks. Memory-light: bands are downloaded in parallel into
    the disk cache, then each output variable is built from the cache one at a time."""
    scenes = sorted((s for s in scenes if (s.cloud_cover or 0) <= MAX_TILE_CLOUD), key=lambda x: x.datetime)
    prefetch(provider, [(sc, "scl", Resampling.nearest) for sc in scenes], grid)
    keep = []
    for sc in scenes:
        frac = float(np.isin(read(provider, sc, "scl", grid, Resampling.nearest), CLEAR_SCL).mean())
        if frac >= MIN_CLEAR_FRAC:
            keep.append((sc, frac))
    keep = sorted(keep, key=lambda k: -k[1])[:MAX_SCENES]
    if not keep:
        return None, []
    bands = ("blue", "green", "red", "nir")
    prefetch(provider, [(sc, b) for sc, _ in keep for b in bands], grid)

    def refl(sc, b):
        # Processing baseline >= 04.00 (25 Jan 2022 on) adds +1000 to L2A digital numbers.
        off = 1000.0 if float(sc.props.get("s2:processing_baseline", "99")) >= 4.0 else 0.0
        return np.maximum(read(provider, sc, b, grid) - off, 0) / 10000.0

    def variable(fn):
        stack = np.full((len(keep),) + grid.shape, np.nan, dtype="float32")
        for i, (sc, _) in enumerate(keep):
            ok = np.isin(read(provider, sc, "scl", grid, Resampling.nearest), CLEAR_SCL)
            with np.errstate(invalid="ignore", divide="ignore"):
                v = fn(sc)
            stack[i][ok] = v[ok]
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmedian(stack, 0).astype("float32")

    out = np.stack([
        variable(lambda sc: (refl(sc, "nir") - refl(sc, "red")) / (refl(sc, "nir") + refl(sc, "red"))),
        variable(lambda sc: (refl(sc, "green") - refl(sc, "nir")) / (refl(sc, "green") + refl(sc, "nir"))),
        variable(lambda sc: refl(sc, "red")),
        variable(lambda sc: refl(sc, "green")),
        variable(lambda sc: refl(sc, "blue")),
    ])
    used = [{"scene": sc.scene_id, "date": f"{sc.datetime:%Y-%m-%d}", "clear_pct": round(frac * 100, 1)}
            for sc, frac in sorted(keep, key=lambda k: k[0].datetime)]
    return out, used


def change(provider, grid, event) -> OpticalResult | None:
    event = as_utc(event)
    scenes = provider.search("sentinel-2-l2a", grid.bbox, event - timedelta(days=PRE_DAYS),
                             event + timedelta(days=POST_DAYS))
    pre, used_pre = _composite(provider, [s for s in scenes if s.datetime < event], grid)
    post, used_post = _composite(provider, [s for s in scenes if s.datetime >= event], grid)
    if pre is None or post is None:
        return None
    clear = np.isfinite(pre[0]) & np.isfinite(post[0])
    return OpticalResult(pre[0], post[0], pre[1], post[1], clear,
                         rgb_post=post[2:5], rgb_pre=pre[2:5],
                         scenes=[{"role": "pre", **u} for u in used_pre] + [{"role": "post", **u} for u in used_post])
