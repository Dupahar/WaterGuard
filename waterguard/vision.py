"""Close inspection of one place on the impact map (OpenCV 5).

The impact map is decided per pixel. Inspection looks at a whole neighbourhood the way an analyst
would: are the before and after images actually aligned, did the ground change colour and structure,
did vegetation go, is the "change" just a bright edge shifting by a pixel, and what shape does the
patch have. Each measure is taken on the flagged pixels AND on nearby valley ground that was not
flagged, because a whole scene can brighten or green up with the season: only the contrast counts.

    cells(run_dir)                 inspection cells over the impact map, most exposed first
    measure(ev, cell)              metrics for one cell (+ an annotated before/after/change chip)

Everything here reads the run's evidence.tif (written by the pipeline) and impact.tif.
"""
from dataclasses import dataclass
from pathlib import Path

import cv2
import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer

from .pipeline import EVIDENCE_BANDS, EVIDENCE_SCALE

CELL_PX = 60            # 600 m cells
MIN_CELL_PX = 100       # at least 1 ha of impact in a cell to inspect it
PAD_PX = 30             # context around the cell (reference ground, co-registration)
HAND_VALLEY_M = 80.0
CHANNEL_HAND_M = 3.0
MAX_SHIFT_PX = 2.0      # Sentinel-2 multi-temporal registration is specified well under one pixel
MIN_COREG_CC = 0.3
DISPLAY_GAIN = 0.25     # reflectance that maps to white in the chips (same as the dashboard)


@dataclass
class Evidence:
    bands: dict             # name -> float32 array (nan = no data)
    impact: np.ndarray      # bool
    classes: np.ndarray
    transform: rasterio.Affine
    crs: object
    run_dir: Path

    def lonlat(self, r, c):
        x, y = self.transform * (c + 0.5, r + 0.5)
        lon, lat = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True).transform(x, y)
        return round(lon, 5), round(lat, 5)


def load(run_dir) -> Evidence:
    run_dir = Path(run_dir)
    with rasterio.open(run_dir / "evidence.tif") as src:
        raw = src.read()
        tr, crs = src.transform, src.crs
    bands = {}
    for i, b in enumerate(EVIDENCE_BANDS):
        a = raw[i].astype("float32")
        a[raw[i] == -32768] = np.nan
        bands[b] = a / EVIDENCE_SCALE.get(b, 10000)
    with rasterio.open(run_dir / "impact.tif") as src:
        cls = src.read(1)
    return Evidence(bands, np.isin(cls, (1, 2, 3)), cls, tr, crs, run_dir)


# ---------------------------------------------------------------- where to look
def cells(run_dir, ev: Evidence | None = None) -> list[dict]:
    """Tile the impact map into cells; rank by what is at stake (buildings hit, roads cut, people cut off)."""
    ev = ev or load(run_dir)
    H, W = ev.impact.shape
    run_dir = Path(run_dir)

    def pts(name, col=None):
        p = run_dir / name
        if not p.exists():
            return np.empty((0, 2)), np.empty(0)
        g = gpd.read_file(p)
        if not len(g):
            return np.empty((0, 2)), np.empty(0)
        g = g.to_crs(ev.crs)
        c = g.geometry.representative_point()
        cols, rows = ~ev.transform * (c.x.values, c.y.values)
        w = g[col].fillna(0).values.astype(float) if col and col in g else np.ones(len(g))
        return np.stack([rows, cols], 1), w

    bld, _ = pts("buildings_affected.geojson")
    road, _ = pts("roads_cut.geojson")
    sett, people = pts("settlements.geojson", "people_est")

    out = []
    for r0 in range(0, H, CELL_PX):
        for c0 in range(0, W, CELL_PX):
            r1, c1 = min(r0 + CELL_PX, H), min(c0 + CELL_PX, W)
            n = int(ev.impact[r0:r1, c0:c1].sum())
            if n < MIN_CELL_PX:
                continue
            inside = lambda P: (P[:, 0] >= r0) & (P[:, 0] < r1) & (P[:, 1] >= c0) & (P[:, 1] < c1) if len(P) else np.zeros(0, bool)
            near = lambda P: ((P[:, 0] >= r0 - CELL_PX) & (P[:, 0] < r1 + CELL_PX) & (P[:, 1] >= c0 - CELL_PX)
                              & (P[:, 1] < c1 + CELL_PX)) if len(P) else np.zeros(0, bool)
            b, rd = int(inside(bld).sum()), int(inside(road).sum())
            ppl = float(people[near(sett)].sum()) if len(sett) else 0.0
            lon, lat = ev.lonlat((r0 + r1) / 2, (c0 + c1) / 2)
            ring = [list(ev.lonlat(r - 0.5, c - 0.5)) for r, c in ((r0, c0), (r0, c1), (r1, c1), (r1, c0), (r0, c0))]
            out.append({"id": f"r{r0}c{c0}", "rows": [r0, r1], "cols": [c0, c1], "impact_ha": round(n * 0.01, 2),
                        "ring": ring,
                        "buildings_hit": b, "road_segments_cut": rd, "people_nearby_est": int(ppl),
                        "lon": lon, "lat": lat,
                        "priority": round(b * 10 + rd * 25 + ppl * 0.05 + n * 0.01, 1)})
    return sorted(out, key=lambda c: -c["priority"])


# ---------------------------------------------------------------- active perception
def window(ev: Evidence, cell: dict):
    H, W = ev.impact.shape
    (r0, r1), (c0, c1) = cell["rows"], cell["cols"]
    return max(r0 - PAD_PX, 0), min(r1 + PAD_PX, H), max(c0 - PAD_PX, 0), min(c1 + PAD_PX, W)


def later_look(ev: Evidence, cell: dict, event, provider, start_days=40, end=None) -> tuple[dict | None, list]:
    """A fresh cloud-free Sentinel-2 composite of just this cell's window, from a later period.
    Debris, scour and buried fields persist for months; wet soil, turbid water and seasonal
    green-up do not. Returns band overrides for measure() and the scenes used."""
    from datetime import datetime, timedelta, timezone
    from .grid import Grid
    from .optical import _composite
    from .providers.base import as_utc
    R0, R1, C0, C1 = window(ev, cell)
    x0, y0 = ev.transform * (C0, R0)
    tr = rasterio.Affine(ev.transform.a, 0, x0, 0, ev.transform.e, y0)
    xs, ys = tr * (np.array([0, C1 - C0]), np.array([R1 - R0, 0]))
    lon, lat = Transformer.from_crs(ev.crs, "EPSG:4326", always_xy=True).transform(xs, ys)
    g = Grid(ev.crs, tr, C1 - C0, R1 - R0, (min(lon), min(lat), max(lon), max(lat)))
    ev_t = as_utc(event)
    end = end or datetime.now(timezone.utc)
    scenes = provider.search("sentinel-2-l2a", g.bbox, ev_t + timedelta(days=start_days), end)
    comp, used = _composite(provider, scenes, g)
    if comp is None:
        return None, []
    return {"ndvi_post": comp[0], "ndwi_post": comp[1], "red_post": comp[2], "green_post": comp[3],
            "blue_post": comp[4]}, used


# ---------------------------------------------------------------- measurements
def _display(rgb):
    """Reflectance (H, W, 3, nan allowed) -> float32 sRGB-like 0..1 (same stretch as the dashboard)."""
    return (np.clip(np.nan_to_num(rgb, nan=0) / DISPLAY_GAIN, 0, 1) ** (1 / 1.6)).astype("float32")


def coregister(pre_l, post_l, valid):
    """Sub-pixel translation between before and after (ECC on gradient magnitude, which ignores the
    brightness change a flood causes). Returns (dx, dy, correlation) or None if it does not converge."""
    def grad(a):
        a = cv2.GaussianBlur(a, (0, 0), 1.0)
        return cv2.magnitude(cv2.Sobel(a, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(a, cv2.CV_32F, 0, 1, ksize=3))
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        cc, warp = cv2.findTransformECC(grad(pre_l), grad(post_l), warp, cv2.MOTION_TRANSLATION,
                                        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5),
                                        valid.astype("uint8"), 3)
    except cv2.error:
        return None
    dx, dy = float(warp[0, 2]), float(warp[1, 2])
    if cc < MIN_COREG_CC or np.hypot(dx, dy) > MAX_SHIFT_PX:   # did not lock on: do not trust it
        return None
    return dx, dy, float(cc)


def _ssim_dissimilarity(a, b):
    """Local structural dissimilarity (1 - SSIM) / 2 on two single-channel float images, Gaussian windows."""
    C1, C2 = (0.01 * 100) ** 2, (0.03 * 100) ** 2      # L* range 0..100
    g = lambda x: cv2.GaussianBlur(x, (0, 0), 1.5)
    mu_a, mu_b = g(a), g(b)
    va, vb, cov = g(a * a) - mu_a ** 2, g(b * b) - mu_b ** 2, g(a * b) - mu_a * mu_b
    ssim = ((2 * mu_a * mu_b + C1) * (2 * cov + C2)) / ((mu_a ** 2 + mu_b ** 2 + C1) * (va + vb + C2))
    return (1 - ssim) / 2


def _local_std(a, k=7):
    m = cv2.blur(a, (k, k))
    return np.sqrt(np.maximum(cv2.blur(a * a, (k, k)) - m * m, 0))


def _med(x, m):
    v = x[m & np.isfinite(x)]
    return round(float(np.median(v)), 4) if v.size >= 20 else None


def measure(ev: Evidence, cell: dict, chip_path: Path | None = None, rgb_override: dict | None = None) -> dict:
    """All metrics for one cell. rgb_override: {'red_post': arr, ...} chip-sized replacements (later imagery)."""
    (r0, r1), (c0, c1) = cell["rows"], cell["cols"]
    R0, R1, C0, C1 = window(ev, cell)
    win = (slice(R0, R1), slice(C0, C1))
    B = {k: v[win].copy() for k, v in ev.bands.items()}
    if rgb_override:
        B.update(rgb_override)
    imp = ev.impact[win]
    core = np.zeros_like(imp)
    core[r0 - R0:r1 - R0, c0 - C0:c1 - C0] = True
    M = imp & core
    hand = np.nan_to_num(B["hand_m"], nan=999)
    # reference = unflagged valley ground, but not the wetted channel itself (water level and turbidity
    # change from week to week whether or not a flood came through)
    valley = (hand <= HAND_VALLEY_M) & (hand > CHANNEL_HAND_M)
    away = cv2.dilate(imp.astype("uint8"), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) == 0
    Rf = valley & away
    if Rf.sum() < 50:                               # narrow gorge: any unflagged ground nearby
        Rf = away

    pre = np.dstack([B["red_pre"], B["green_pre"], B["blue_pre"]])
    post = np.dstack([B["red_post"], B["green_post"], B["blue_post"]])
    clear = np.isfinite(pre).all(2) & np.isfinite(post).all(2)
    m = {"cell": cell["id"], "clear_share": round(float(clear[M].mean()) if M.any() else 0.0, 3),
         "optical_decided_share": round(float((B["source"][M] == 1).mean()) if M.any() else 0.0, 3)}

    # radar, independent of cloud
    m["sar_z_flagged"], m["sar_z_reference"] = _med(B["sar_z"], M), _med(B["sar_z"], Rf)
    m["ndvi_drop_flagged"] = _med(B["ndvi_pre"] - B["ndvi_post"], M & clear)
    m["ndvi_drop_reference"] = _med(B["ndvi_pre"] - B["ndvi_post"], Rf & clear)

    lab_pre = cv2.cvtColor(_display(pre), cv2.COLOR_RGB2Lab)
    lab_post = cv2.cvtColor(_display(post), cv2.COLOR_RGB2Lab)
    shift = coregister(lab_pre[..., 0], lab_post[..., 0], clear) if clear.mean() > 0.3 else None
    if shift:
        dx, dy, cc = shift
        m["coreg_shift_px"], m["coreg_correlation"] = round(float(np.hypot(dx, dy)), 3), round(cc, 3)
        A = np.float32([[1, 0, dx], [0, 1, dy]])
        lab_post = cv2.warpAffine(lab_post, A, lab_post.shape[1::-1], flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                  borderMode=cv2.BORDER_REFLECT)
    else:
        m["coreg_shift_px"], m["coreg_correlation"] = None, None

    dE = np.linalg.norm(lab_post - lab_pre, axis=2)
    dis = _ssim_dissimilarity(lab_pre[..., 0], lab_post[..., 0])
    tex = np.log2((_local_std(cv2.Laplacian(lab_post[..., 0], cv2.CV_32F)) + 1) /
                  (_local_std(cv2.Laplacian(lab_pre[..., 0], cv2.CV_32F)) + 1))
    for k, v in (("delta_e", dE), ("ssim_dissimilarity", dis), ("texture_log2_ratio", tex)):
        v = np.where(clear, v, np.nan)
        m[f"{k}_flagged"], m[f"{k}_reference"] = _med(v, M), _med(v, Rf)

    # misregistration artefact: change concentrated on edges that already existed
    l8 = np.clip(lab_pre[..., 0] * 2.55, 0, 255).astype("uint8")
    edges = cv2.dilate(cv2.Canny(cv2.GaussianBlur(l8, (3, 3), 0), 40, 120), np.ones((3, 3), "uint8")) > 0
    m["on_pre_existing_edges_share"] = round(float(edges[M & clear].mean()), 3) if (M & clear).sum() >= 20 else None

    # shape of the flagged ground in this cell
    cnts, _ = cv2.findContours(M.astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        big = max(cnts, key=cv2.contourArea)
        (_, _), (w_, h_), _ = cv2.minAreaRect(big)
        hull = cv2.contourArea(cv2.convexHull(big))
        m["elongation"] = round(max(w_, h_) / max(min(w_, h_), 1), 2)
        m["solidity"] = round(cv2.contourArea(big) / max(hull, 1), 3)
        m["patches_in_cell"] = len(cnts)
    for k in ("delta_e", "ssim_dissimilarity", "texture_log2_ratio", "sar_z", "ndvi_drop"):
        f, r = m.get(f"{k}_flagged"), m.get(f"{k}_reference")
        m[f"{k}_contrast"] = round(f - r, 4) if f is not None and r is not None else None

    if chip_path is not None:
        chip(chip_path, _display(pre), cv2.cvtColor(lab_post, cv2.COLOR_Lab2RGB), dE, M, Rf, core, m,
             np.isfinite(pre).all(2), np.isfinite(post).all(2))
    return m


def chip(path, pre_rgb, post_rgb, dE, M, Rf, core, m, ok_pre, ok_post, scale=4):
    """before | after (co-registered) | colour change, with the flagged outline. RGB uint8 PNG.
    Grey = no cloud-free look."""
    def up(img, interp=cv2.INTER_CUBIC):
        return cv2.resize(img, None, fx=scale, fy=scale, interpolation=interp)
    to8 = lambda x: np.clip(x * 255, 0, 255).astype("uint8")
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))

    def enhance(rgb):
        lab = cv2.cvtColor(to8(rgb), cv2.COLOR_RGB2LAB)
        lab[..., 0] = clahe.apply(lab[..., 0])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)

    heat = cv2.applyColorMap(to8(np.clip(np.nan_to_num(dE) / 40, 0, 1)), cv2.COLORMAP_TURBO)[..., ::-1].copy()
    grey = np.array([90, 90, 90], "uint8")
    a, b = enhance(pre_rgb), enhance(post_rgb)
    a[~ok_pre], b[~ok_post], heat[~(ok_pre & ok_post)] = grey, grey, grey
    panels = [up(a), up(b), up(heat)]
    outline = cv2.findContours(up(M.astype("uint8"), cv2.INTER_NEAREST), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    box = cv2.findContours(up(core.astype("uint8"), cv2.INTER_NEAREST), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    for i, p in enumerate(panels):
        p = np.ascontiguousarray(p)
        cv2.drawContours(p, box, -1, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.drawContours(p, outline, -1, (255, 60, 30) if i < 2 else (255, 255, 255), 2, cv2.LINE_AA)
        sh = m.get("coreg_shift_px")
        label = ["BEFORE", f"AFTER{f' (aligned {sh:.2f} px)' if sh else ''}", "COLOUR CHANGE dE"][i]
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(p, (0, 0), (tw + 16, th + 14), (20, 20, 20), -1)
        cv2.putText(p, label, (8, th + 7), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        panels[i] = p
    img = cv2.hconcat(panels)
    cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
