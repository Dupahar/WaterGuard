"""Fuse the evidence into one impact map: where the flood / debris hit.

Classes (uint8):
  0 = no impact mapped
  1 = flood / debris impact (ground changed on the valley floor)
  2 = open water after the event that was not water before (subset of impact)
  3 = riverbed that was already bare before the event, included only because it connects to
      detected change (lower confidence: e.g. a tributary's gravel bed near the confluence)
  9 = could not assess (no valid radar look and no clear optical pair)

Decision, per pixel, all on the 10 m grid:
  valley   = HAND <= HAND_MAX_M  (a surge cannot climb far above the river)
  optical  = where both Sentinel-2 composites are clear:
             NDVI fell by >= NDVI_DROP and post-event NDVI <= NDVI_POST_MAX (vegetation stripped,
             bare debris/sediment), or NDWI rose by >= NDWI_RISE (new water / wet sediment)
  radar    = elsewhere: smoothed Sentinel-1 |z| change >= Z_MIN (cloud-proof, less sharp)
  impact   = valley & (optical or radar), cleaned with OpenCV morphology, and kept only if the
             patch touches the river channel (a flood arrives from the river, not from mid-slope)
  channel  = clear-sky valley ground that is bare or water after the event (NDVI <= BARE_NDVI) is
             added where it is connected to that impact: the riverbed and gravel bars the surge
             ran through show no vegetation loss because they had none to lose
Thresholds were tuned on EMSR927 AOI01 + AOI02 only; AOI03 + AOI05 are held out for testing.
Pre-event OSM building footprints are excluded from riverbed growth (roofs are bare too): in a
Kathmandu 2024 test this cut false urban "riverbed" from 678 ha to 51 ha.
Patch-size limits were set with a placebo test (same area, a fake event date one month before the
flood): they cut false impact there from 35 ha to 0 ha without changing the tuning-area scores.
The riverbed-growth seed size (5 ha) was set with a control tributary (Tadi Khola, not on the flood
path), where 2 ha seeds let growth run up its pre-existing gravel bed (180 ha -> 24 ha).
"""
import cv2
import numpy as np

HAND_MAX_M = 80.0
CHANNEL_HAND_M = 3.0
NDVI_DROP = 0.05
NDVI_POST_MAX = 0.30
NDWI_RISE = 0.10
Z_SMOOTH_PX = 21
Z_MIN = 1.0
MIN_PATCH_PX = 200         # 2 ha: smaller patches are mostly seasonal noise (placebo-date test)
BARE_NDVI = 0.15
SEED_MIN_PX = 500          # only change patches >= 5 ha may seed riverbed growth (Tadi Khola control)
USE_BARE = True
BED_HAND_MAX_M = 0         # riverbed growth only this high above the river (0 = off)
BED_DIST_M = 0             # ... and this close to the channel (0 = off)
BUILT_CHANGE = 0.0         # building pixels may join riverbed growth if mean RGB reflectance changed this much


def _smooth(x, k):
    v = np.isfinite(x).astype("float32")
    s = cv2.blur(np.nan_to_num(x).astype("float32"), (k, k))
    c = cv2.blur(v, (k, k))
    return np.where(c > 0.2, s / np.maximum(c, 1e-6), np.nan)


def _touching(mask, seed):
    n, lab = cv2.connectedComponents(mask.astype("uint8"), connectivity=8)
    keep = np.zeros(n, bool)
    keep[np.unique(lab[seed & mask])] = True
    keep[0] = False
    return keep[lab]


def _min_area(mask, px):
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype("uint8"), connectivity=8)
    keep = st[:, cv2.CC_STAT_AREA] >= px
    keep[0] = False
    return keep[lab]


def impact_map(terrain: dict, sar, opt, built: np.ndarray | None = None) -> dict:
    """built: optional mask of pre-event OSM building footprints (roofs are 'bare' too)."""
    hand = terrain["hand"]
    valley = np.nan_to_num(hand, nan=999) <= HAND_MAX_M
    channel = (np.nan_to_num(hand, nan=999) <= CHANNEL_HAND_M) | terrain["streams"]

    zs = _smooth(sar.z, Z_SMOOTH_PX)
    radar_ok = np.isfinite(zs)
    radar_hit = radar_ok & (np.nan_to_num(zs) >= Z_MIN)

    if opt is not None:
        clear = opt.clear
        with np.errstate(invalid="ignore"):
            opt_hit = clear & ((((opt.ndvi_pre - opt.ndvi_post) >= NDVI_DROP) & (opt.ndvi_post <= NDVI_POST_MAX))
                               | ((opt.ndwi_post - opt.ndwi_pre) >= NDWI_RISE))
    else:
        clear = np.zeros(hand.shape, bool)
        opt_hit = clear

    evidence = np.where(clear, opt_hit, radar_hit)
    raw = valley & evidence
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    m = cv2.morphologyEx(raw.astype("uint8"), cv2.MORPH_OPEN, k)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k).astype(bool) & valley
    m = _touching(m, channel)
    if opt is not None and USE_BARE:
        with np.errstate(invalid="ignore"):
            bare = valley & clear & (np.nan_to_num(opt.ndvi_post, nan=1.0) <= BARE_NDVI)
        # a riverbed is next to the channel and only metres above it; without this, bare roofs and
        # streets in a city connect into one huge "riverbed" (Kathmandu 2024 test)
        if BED_HAND_MAX_M or BED_DIST_M:
            near = np.ones(hand.shape, bool)
            if BED_HAND_MAX_M:
                near &= np.nan_to_num(hand, nan=999) <= BED_HAND_MAX_M
            if BED_DIST_M:
                dist = cv2.distanceTransform((~channel).astype("uint8"), cv2.DIST_L2, 5) * 10.0
                near &= dist <= BED_DIST_M
            bare &= near
        if built is not None:
            # intact roofs look the same before and after; a house buried in debris does not
            blocked = built
            if BUILT_CHANGE and opt.rgb_pre is not None:
                with np.errstate(invalid="ignore"):
                    dr = np.nanmean(np.abs(opt.rgb_post - opt.rgb_pre), 0)
                blocked = built & ~(np.nan_to_num(dr, nan=0) >= BUILT_CHANGE)
            bare &= ~blocked
        seeds = _min_area(m, SEED_MIN_PX) if SEED_MIN_PX else m
        core = m
        m = m | _touching(bare | m, seeds)
        with np.errstate(invalid="ignore"):
            was_bare = np.nan_to_num(opt.ndvi_pre, nan=1.0) <= BARE_NDVI
        old_bed = m & ~core & was_bare      # bare before AND after: added only by connectivity
    else:
        old_bed = np.zeros(hand.shape, bool)
    m = _min_area(m, MIN_PATCH_PX)

    new_water = m & sar.water_post & ~sar.water_pre
    assessable = clear | radar_ok
    cls = np.zeros(hand.shape, "uint8")
    old_bed &= m
    cls[m] = 1
    cls[old_bed] = 3
    cls[new_water] = 2
    cls[~assessable] = 9
    source = np.where(clear, 1, np.where(radar_ok, 2, 0)).astype("uint8")   # 1 optical, 2 radar
    return {
        "classes": cls,
        "impact": m,
        "evidence_source": source,
        "stats": {
            "impact_ha": round(float(m.sum()) * 0.01, 1),
            "new_water_ha": round(float(new_water.sum()) * 0.01, 1),
            "riverbed_lower_confidence_ha": round(float(old_bed.sum()) * 0.01, 1),
            "share_decided_by_optical_pct": round(float((m & clear).sum() / max(m.sum(), 1) * 100), 1),
            "unassessable_pct_of_area": round(float((~assessable).mean() * 100), 1),
        },
    }
