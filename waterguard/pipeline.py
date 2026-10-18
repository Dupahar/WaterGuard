"""End to end: an area + a flood date -> impact map, damage, cut-off settlements, facts.json.

    python -m waterguard.pipeline --bbox 85.30 28.10 85.40 28.30 --date 2026-08-26

Everything a person or the copilot reads comes from facts.json (and the GeoJSON layers next to it),
so every number in a report can be traced back to a computation in this file.
"""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import box

from . import access, damage, detect, optical, sar, terrain
from .config import DATA_DIR
from .grid import Grid
from .osm import load_pre_event_osm
from .providers import providers
from .providers.base import as_utc

RUNS_DIR = DATA_DIR / "runs"
MAX_AREA_KM2 = 1500


def run_id(bbox, event) -> str:
    return hashlib.sha1(f"{[round(v, 4) for v in bbox]}|{as_utc(event):%Y-%m-%dT%H}".encode()).hexdigest()[:10]


def _to_geojson(gdf: gpd.GeoDataFrame, path: Path, cols=None):
    g = gdf if cols is None else gdf[[c for c in cols if c in gdf.columns] + ["geometry"]]
    g = g.to_crs(4326)
    for c in g.columns:
        if c != "geometry" and g[c].dtype == object:
            g[c] = g[c].apply(lambda v: v if v is None or isinstance(v, (str, int, float, bool)) else str(v))
    path.write_text(g.to_json(drop_id=True, na="null"), encoding="utf-8")


def _plain(o):
    """JSON-safe copy: numpy scalars -> Python, NaN/inf -> None, unknown objects -> str."""
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        o = o.item()
    if isinstance(o, float):
        return o if np.isfinite(o) else None
    if o is None or isinstance(o, (bool, int, str)):
        return o
    return str(o)


EVIDENCE_BANDS = ("red_pre", "green_pre", "blue_pre", "red_post", "green_post", "blue_post", "ndvi_pre", "ndvi_post",
                  "ndwi_pre", "ndwi_post", "sar_z", "hand_m", "source")
EVIDENCE_SCALE = {"sar_z": 1000, "hand_m": 10, "source": 1}     # everything else x 10000


def _save_evidence(path, grid, T, S, O, D):
    """The per-pixel evidence behind the impact map, for later inspection (waterguard/vision.py).
    int16, scaled; -32768 = no data."""
    nan = np.full(grid.shape, np.nan, "float32")
    have = O is not None and O.rgb_pre is not None
    layers = {
        "red_pre": O.rgb_pre[0] if have else nan, "green_pre": O.rgb_pre[1] if have else nan,
        "blue_pre": O.rgb_pre[2] if have else nan, "red_post": O.rgb_post[0] if have else nan,
        "green_post": O.rgb_post[1] if have else nan, "blue_post": O.rgb_post[2] if have else nan,
        "ndvi_pre": O.ndvi_pre if O is not None else nan, "ndvi_post": O.ndvi_post if O is not None else nan,
        "ndwi_pre": O.ndwi_pre if O is not None else nan, "ndwi_post": O.ndwi_post if O is not None else nan,
        "sar_z": S.z, "hand_m": T["hand"], "source": D["evidence_source"].astype("float32"),
    }
    stack = np.stack([np.where(np.isfinite(layers[b]), np.clip(np.round(layers[b] * EVIDENCE_SCALE.get(b, 10000)),
                                                              -32767, 32767), -32768).astype("int16")
                      for b in EVIDENCE_BANDS])
    grid.save(path, stack, nodata=-32768)
    import rasterio
    with rasterio.open(path, "r+") as ds:
        ds.descriptions = EVIDENCE_BANDS


def _png(path, rgba, grid):
    import cv2
    cv2.imwrite(str(path), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    from pyproj import Transformer
    tr = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    x0, y1 = grid.transform.c, grid.transform.f
    x1, y0 = x0 + grid.width * grid.res, y1 - grid.height * grid.res
    corners = [tr.transform(x, y) for x, y in ((x0, y1), (x1, y1), (x1, y0), (x0, y0))]
    return [[round(a, 6), round(b, 6)] for a, b in corners]


def _sitrep_map(path, grid, O, classes, dmg, settlements, bridges, max_px=1100):
    """Static map for the one-page report: Sentinel-2 after-image (or grey), impact, cut roads,
    damaged bridges, settlements coloured by road status, scale bar."""
    import cv2
    H, W = classes.shape
    if O is not None and O.rgb_post is not None:
        rgb = (np.clip(np.nan_to_num(O.rgb_post, nan=0) / 0.25, 0, 1) ** (1 / 1.6) * 255).astype("uint8")
        img = np.dstack([rgb[2], rgb[1], rgb[0]]).copy()           # BGR
        img = (img * 0.75).astype("uint8")
    else:
        img = np.full((H, W, 3), 60, "uint8")
    over = img.copy()
    over[classes == 1] = (20, 70, 200)
    over[classes == 2] = (230, 110, 20)
    over[classes == 3] = (60, 170, 230)
    img = cv2.addWeighted(over, 0.55, img, 0.45, 0)
    s = min(1.0, max_px / max(H, W)) if max(H, W) > max_px else max_px / max(H, W)
    img = cv2.resize(img, (int(W * s), int(H * s)), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_NEAREST)
    inv = ~grid.transform

    def px(x, y):
        c, r = inv * (x, y)
        return int(c * s), int(r * s)

    def lines(geom, color, w):
        for g in getattr(geom, "geoms", [geom]):
            if g.geom_type == "LineString":
                cv2.polylines(img, [np.array([px(x, y) for x, y in g.coords[:]], np.int32)], False, color, w, cv2.LINE_AA)
    for g in dmg["roads_cut"].geometry:
        lines(g, (40, 40, 255), 3)
    for _, b in bridges[bridges["status"] == "likely damaged"].iterrows():
        x, y = px(b.geometry.centroid.x, b.geometry.centroid.y)
        cv2.drawMarker(img, (x, y), (0, 0, 0), cv2.MARKER_TILTED_CROSS, 18, 6)
        cv2.drawMarker(img, (x, y), (60, 60, 255), cv2.MARKER_TILTED_CROSS, 16, 3)
    col = {"cut off": (60, 60, 230), "partly cut": (25, 180, 250), "connected": (40, 170, 40)}
    for _, r in settlements.sort_values("buildings").iterrows():
        x, y = px(r.geometry.x, r.geometry.y)
        st = r.get("vehicle_status")
        rad = int(5 + min(r["buildings"], 300) / 300 * 9)
        cv2.circle(img, (x, y), rad, col.get(st, (150, 150, 150)), -1, cv2.LINE_AA)
        cv2.circle(img, (x, y), rad, (0, 0, 0), 1, cv2.LINE_AA)
        if r["name"] and (st in ("cut off", "partly cut") or r["buildings"] >= 60):
            for c, th in (((0, 0, 0), 4), ((255, 255, 255), 1)):
                cv2.putText(img, str(r["name"]), (x + rad + 3, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, th, cv2.LINE_AA)
    # scale bar
    km = 1 if W * grid.res < 15000 else 5
    L = int(km * 1000 / grid.res * s)
    h = img.shape[0]
    cv2.rectangle(img, (10, h - 30), (20 + L, h - 8), (255, 255, 255), -1)
    cv2.line(img, (15, h - 14), (15 + L, h - 14), (0, 0, 0), 3)
    cv2.putText(img, f"{km} km", (17, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(img, "N", (img.shape[1] - 22, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(path), img)


def _apply_veto(D, veto):
    """Analyst-removed inspection cells (waterguard/inspector.py) are cleared from the impact map."""
    m = np.zeros(D["impact"].shape, bool)
    for v in veto:
        (r0, r1), (c0, c1) = v["rows"], v["cols"]
        m[r0:r1, c0:c1] = True
    cls = D["classes"]
    D["impact"] = D["impact"] & ~m
    cls[m & np.isin(cls, (1, 2, 3))] = 0
    st = D["stats"]
    st["impact_ha"] = round(float(D["impact"].sum()) * 0.01, 1)
    st["new_water_ha"] = round(float((cls == 2).sum()) * 0.01, 1)
    st["riverbed_lower_confidence_ha"] = round(float((cls == 3).sum()) * 0.01, 1)
    return D


def run(bbox, event, out_dir: Path | None = None, progress=lambda msg, pct: None, veto: list | None = None) -> dict:
    t0 = time.time()
    event = as_utc(event)
    bbox = tuple(float(v) for v in bbox)
    grid = Grid.from_bbox(bbox)
    area_km2 = grid.width * grid.height * grid.res ** 2 / 1e6
    if area_km2 > MAX_AREA_KM2:
        raise ValueError(f"Area is {area_km2:.0f} km2; the limit is {MAX_AREA_KM2} km2. Draw a smaller box.")
    rid = run_id(bbox, event)
    out = Path(out_dir or RUNS_DIR / rid)
    out.mkdir(parents=True, exist_ok=True)
    timings = {}

    def step(name, pct):
        progress(name, pct)
        timings[name] = round(time.time() - t0, 1)

    prov = providers()[0]   # Planetary Computer (full-resolution COGs with orbit metadata)

    step("terrain (Copernicus DEM)", 5)
    T = terrain.build(grid, prov)

    step("Sentinel-1 radar change", 20)
    try:
        S = sar.change(prov, grid, event, T)
    except Exception:
        # fallback provider (Meru) if Planetary Computer has no pair / is down
        alt = providers()[1:]
        if not alt:
            raise
        S = sar.change(alt[0], grid, event, T)

    step("Sentinel-2 optical change", 45)
    O = optical.change(prov, grid, event)

    step("pre-event OpenStreetMap", 62)
    osm = load_pre_event_osm(bbox, event)
    # building footprints: roofs look like bare ground, so they must not grow the "riverbed"
    import cv2
    from rasterio.features import rasterize
    blds = osm.buildings.to_crs(grid.crs).geometry
    built = rasterize([(g, 1) for g in blds], out_shape=grid.shape, transform=grid.transform, all_touched=True) > 0 \
        if len(blds) else np.zeros(grid.shape, bool)
    built = cv2.dilate(built.astype("uint8"), np.ones((3, 3), "uint8")) > 0

    step("impact map (OpenCV)", 72)
    D = detect.impact_map(T, S, O, built)
    if veto:
        before = float(D["impact"].sum())
        D = _apply_veto(D, veto)
        D["stats"]["removed_by_analyst_ha"] = round((before - float(D["impact"].sum())) * 0.01, 1)
    impact = damage.vectorize(D["impact"], grid)

    step("damage overlay", 80)
    dmg = damage.assess(osm, impact, grid.crs)

    step("cut-off settlements", 88)
    boundary = gpd.GeoSeries([box(*bbox)], crs=4326).to_crs(grid.crs).iloc[0]
    acc = access.analyse(osm, dmg, impact, grid.crs, boundary)

    step("writing outputs", 95)
    grid.save(out / "impact.tif", D["classes"], nodata=255)
    _to_geojson(impact.assign(kind="flood/debris impact"), out / "impact.geojson")
    _to_geojson(dmg["buildings"][dmg["buildings"]["status"] != "not mapped as affected"],
                out / "buildings_affected.geojson", ["osm_id", "name", "building", "status"])
    _to_geojson(dmg["bridges"], out / "bridges.geojson", ["osm_id", "name", "highway", "status"])
    _to_geojson(dmg["health"], out / "health.geojson", ["osm_id", "name", "amenity", "healthcare", "status"])
    if len(dmg["roads_cut"]):
        _to_geojson(dmg["roads_cut"], out / "roads_cut.geojson", ["osm_id", "name", "highway"])
    else:
        (out / "roads_cut.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    S_ = acc["settlements"].copy()
    _to_geojson(S_, out / "settlements.geojson")
    _save_evidence(out / "evidence.tif", grid, T, S, O, D)

    # imagery overlays for the dashboard
    overlays = {}
    if O is not None and O.rgb_post is not None:
        for name, rgb in (("s2_post", O.rgb_post), ("s2_pre", O.rgb_pre)):
            a = (np.clip(np.nan_to_num(rgb, nan=0) / 0.25, 0, 1) ** (1 / 1.6) * 255).astype("uint8")
            alpha = (np.isfinite(rgb[0]) * 255).astype("uint8")
            overlays[name] = _png(out / f"{name}.png", np.dstack([a[0], a[1], a[2], alpha]), grid)
    z = np.nan_to_num(S.z, nan=0)
    zc = np.clip(z / 3 * 255, 0, 255).astype("uint8")
    overlays["sar_change"] = _png(out / "sar_change.png",
                                  np.dstack([zc, zc // 3, 255 - zc, (np.isfinite(S.z) & (z > 1.0)) * 170]).astype("uint8"),
                                  grid)
    cls = D["classes"]
    rgba = np.zeros(cls.shape + (4,), "uint8")
    rgba[cls == 1] = (200, 70, 20, 190)
    rgba[cls == 2] = (20, 110, 230, 220)
    rgba[cls == 3] = (230, 170, 60, 150)
    rgba[cls == 9] = (120, 120, 120, 90)
    overlays["impact"] = _png(out / "impact.png", rgba, grid)

    # key named places for the report (largest affected / cut-off first)
    def top_settlements(mask, n=10):
        s = S_[mask].copy()
        if s.empty:
            return []
        share = s["vehicle_stranded_share"] if "vehicle_stranded_share" in s else 0
        s["_k"] = s["people_est"] * share + s["buildings"] * 1e-6
        s = s.sort_values("_k", ascending=False).head(n)
        return [{"name": r["name"] or f"unnamed {r['kind'].replace('building cluster', 'cluster')} ({int(r['buildings'])} buildings)",
                 "name_ne": r.get("name_ne"), "kind": r["kind"], "buildings": int(r["buildings"]),
                 "people_est": int(r["people_est"]),
                 "share_of_buildings_cut_off": r.get("vehicle_stranded_share"),
                 "people_est_stranded": int(round(r["people_est"] * (r.get("vehicle_stranded_share") or 0))),
                 "health_km_before": r.get("vehicle_health_km_before"),
                 "health_km_after": r.get("vehicle_health_km_after"),
                 "lost": r.get("vehicle_lost"),
                 "lon": round(float(gpd.GeoSeries([r.geometry], crs=S_.crs).to_crs(4326).iloc[0].x), 5),
                 "lat": round(float(gpd.GeoSeries([r.geometry], crs=S_.crs).to_crs(4326).iloc[0].y), 5)}
                for _, r in s.iterrows()]

    v = S_.get("vehicle_status")
    named = S_[S_["name"].notna()]

    def nearest_place(geom):
        if not len(named):
            return None, None, None
        d = named.distance(geom)
        i = d.idxmin()
        return named.loc[i, "name"], named.loc[i, "name_ne"], round(float(d[i]) / 1000, 1)

    br_utm = dmg["bridges"]
    near = [nearest_place(g.centroid) for g in br_utm.geometry]
    br_utm["near_place"] = [n[0] for n in near]
    br_utm["near_place_ne"] = [n[1] for n in near]
    br_utm["near_km"] = [n[2] for n in near]
    br_utm["name"] = [r["name"] or (f"bridge near {r['near_place']} ({r['near_km']} km)" if r["near_place"]
                                    else "unnamed bridge") for _, r in br_utm.iterrows()]
    bridges = br_utm.to_crs(4326)
    _to_geojson(br_utm, out / "bridges.geojson", ["osm_id", "name", "highway", "status"])
    _sitrep_map(out / "sitrep_map.png", grid, O, D["classes"], dmg, acc["settlements"], br_utm)
    facts = {
        "run_id": rid,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "area": {"bbox": [round(x, 5) for x in bbox], "area_km2": round(area_km2, 1)},
        "event_time_utc": f"{event:%Y-%m-%dT%H:%M:%SZ}",
        "impact": D["stats"] | {"patches": int(len(impact))},
        "damage": dmg["summary"],
        "access": acc["summary"],
        "cut_off_settlements": top_settlements(v == "cut off") if v is not None else [],
        "partly_cut_settlements": top_settlements(v == "partly cut") if v is not None else [],
        "most_stranded_settlements": (lambda s: top_settlements(s.index.isin(
            (S_["people_est"] * S_.get("vehicle_stranded_share", 0)).sort_values(ascending=False).head(8).index)
            & (S_.get("vehicle_stranded_share", 0) > 0)))(S_),
        "damaged_bridges": [
            {"name": r["name"], "osm_id": r["osm_id"], "status": r["status"],
             "near_place": r["near_place"], "near_place_ne": r["near_place_ne"], "near_km": r["near_km"],
             "lon": round(r.geometry.centroid.x, 5), "lat": round(r.geometry.centroid.y, 5)}
            for _, r in bridges[bridges["status"] != "no impact mapped"].iterrows()],
        "affected_health_facilities": [
            {"name": r["name"] or "unnamed", "status": r["status"]}
            for _, r in dmg["health"][dmg["health"]["status"] != "not mapped as affected"].iterrows()],
        "inputs": {
            "sentinel1": S.scenes,
            "sentinel2": O.scenes if O is not None else [],
            "dem": "Copernicus DEM GLO-30 (via Microsoft Planetary Computer)",
            "osm": osm.audit,
        },
        "method": {
            "hand_max_m": detect.HAND_MAX_M, "ndvi_drop": detect.NDVI_DROP, "ndwi_rise": detect.NDWI_RISE,
            "sar_z_min": detect.Z_MIN, "buffer_possible_m": damage.BUFFER_M,
        },
        "overlays": overlays,
        "analyst_review": {"removed_cells": [v["id"] for v in veto]} if veto else None,
        "terrain_workdir": str(T["workdir"]),
        "timings_s": timings,
    }
    facts["runtime_s"] = round(time.time() - t0, 1)
    (out / "facts.json").write_text(json.dumps(_plain(facts), indent=1, ensure_ascii=False), encoding="utf-8")
    progress("done", 100)
    return facts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    ap.add_argument("--date", required=True, help="event date/time, e.g. 2026-08-26 or 2026-08-25T22:00Z")
    ap.add_argument("--out")
    a = ap.parse_args()
    f = run(a.bbox, a.date, Path(a.out) if a.out else None, progress=lambda m, p: print(f"[{p:3d}%] {m}", flush=True))
    print(json.dumps({k: f[k] for k in ("run_id", "impact", "damage", "access", "runtime_s")}, indent=1))


if __name__ == "__main__":
    main()
