"""Export real WaterGuard results for the launch film -> video/public/data/.
Run from the repo root with the project venv:  .venv/Scripts/python video/scripts/export_data.py
"""
import json, shutil, sys
from pathlib import Path

import cv2
import geopandas as gpd
import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from waterguard import flowpath, terrain  # noqa: E402
from waterguard.grid import Grid  # noqa: E402
from waterguard.providers.planetary import PlanetaryProvider  # noqa: E402

OUT = ROOT / "video/public/data"
OUT.mkdir(parents=True, exist_ok=True)
RUNS = ROOT / "data/runs"
SYA, BID = "e34c30aded", "58052edd5e"


def frame(run):
    f = json.loads((RUNS / run / "facts.json").read_text(encoding="utf-8"))
    g = Grid.from_bbox(tuple(f["area"]["bbox"]))
    cx = g.transform.c + g.width * g.res / 2
    cy = g.transform.f - g.height * g.res / 2
    return f, g, cx, cy


def xy(geom_xy, cx, cy):
    return [round(geom_xy[0] - cx, 1), round(-(geom_xy[1] - cy), 1)]   # metres, y down (screen)


def lines(geom, cx, cy, step=1):
    out = []
    for g in getattr(geom, "geoms", [geom]):
        if g.geom_type == "LineString":
            out.append([xy(p, cx, cy) for p in list(g.coords)[::step]])
    return out


def export_run(run, name, full=True):
    f, g, cx, cy = frame(run)
    d = RUNS / run
    ext = [-g.width * g.res / 2, -g.height * g.res / 2, g.width * g.res, g.height * g.res]   # x, y, w, h (m)
    for img in ("s2_pre", "s2_post", "impact", "sar_change", "sitrep_map"):
        if (d / f"{img}.png").exists():
            shutil.copy(d / f"{img}.png", OUT / f"{name}_{img}.png")
    S = gpd.read_file(d / "settlements.geojson").to_crs(g.crs)
    sett = [{"name": r["name"], "b": int(r["buildings"]), "s": r["vehicle_status"], "sh": float(r.get("vehicle_stranded_share") or 0),
             "c": xy((r.geometry.x, r.geometry.y), cx, cy)}
            for _, r in S.iterrows()]
    out = {"ext": ext, "facts": {k: f[k] for k in ("impact", "damage", "access")}, "settlements": sett,
           "cut": [s["name"] for s in f["cut_off_settlements"]],
           "stranded": [{"name": s["name"], "sh": s["share_of_buildings_cut_off"], "p": s["people_est_stranded"]} for s in f.get("most_stranded_settlements", [])]}
    if full:
        from waterguard.osm import load_pre_event_osm
        osm = load_pre_event_osm(tuple(f["area"]["bbox"]), f["event_time_utc"])
        hit = gpd.read_file(d / "buildings_affected.geojson").to_crs(g.crs)
        status = dict(zip(hit["osm_id"], hit["status"]))
        B = osm.buildings.to_crs(g.crs)
        pts = B.geometry.representative_point()
        out["buildings"] = [[round(p.x - cx), round(-(p.y - cy)), {"likely affected": 2, "possibly affected": 1}.get(status.get(i), 0),
                             round(min(40, max(4, np.sqrt(a)))) ] for p, i, a in zip(pts, B["osm_id"], B.area)]
        R = osm.roads.to_crs(g.crs)
        cutg = gpd.read_file(d / "roads_cut.geojson").to_crs(g.crs)
        cut_u = cutg.buffer(3).union_all() if len(cutg) else None
        out["roads"] = []
        for _, r in R.iterrows():
            for ln in lines(r.geometry, cx, cy):
                out["roads"].append({"h": r["highway"], "l": ln})
        out["roads_cut"] = [ln for geom in cutg.geometry for ln in lines(geom, cx, cy)]
        br = gpd.read_file(d / "bridges.geojson").to_crs(g.crs)
        out["bridges"] = [{"s": r["status"], "c": xy((r.geometry.centroid.x, r.geometry.centroid.y), cx, cy)} for _, r in br.iterrows()]
        # flood path from the top of the area
        line, _ = flowpath.trace(f["terrain_workdir"], 85.352, 28.196)
        out["path"] = lines(gpd.GeoSeries([line], crs=32645).to_crs(g.crs).iloc[0], cx, cy, step=2)
    (OUT / f"{name}.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(name, {k: len(v) if isinstance(v, list) else "" for k, v in out.items()})


def corridor():
    """Hillshade of the whole Bhote Koshi - Trishuli corridor + traced flood path, for the cold open."""
    bbox = (85.08, 27.84, 85.42, 28.30)
    g = Grid.from_bbox(bbox).with_res(30.0)
    T = terrain.build(Grid.from_bbox(bbox), PlanetaryProvider(), pad_deg=0.01)
    with rasterio.open(T["workdir"] / "dem.tif") as src:
        dem = src.read(1).astype("float32"); tr = src.transform
    dem[dem < -100] = np.nan
    gy, gx = np.gradient(np.nan_to_num(dem, nan=np.nanmean(dem)), 30, 30)
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(315), np.radians(40)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    hs = np.clip(hs, 0, 1)
    elev = (dem - np.nanmin(dem)) / (np.nanmax(dem) - np.nanmin(dem))
    img = (np.clip(hs * 0.75 + np.nan_to_num(elev) * 0.35, 0, 1) * 255).astype("uint8")
    cv2.imwrite(str(OUT / "corridor_hillshade.png"), img)
    H, W = img.shape
    cx, cy = tr.c + W * 30 / 2, tr.f - H * 30 / 2
    line, _ = flowpath.trace(T["workdir"], 85.375, 28.275)     # Timure, near the border
    pts = [xy(p, cx, cy) for p in list(line.coords)[::3]]
    aois = gpd.read_file(ROOT / "data/validation/emsr927/aois.geojson")   # for labelling places only
    places = {"Timure": (85.369, 28.262), "Syabru Bensi": (85.344, 28.163), "Betrawati": (85.185, 27.968), "Bidur": (85.163, 27.902)}
    from pyproj import Transformer
    trf = Transformer.from_crs(4326, g.crs, always_xy=True)
    out = {"ext": [-W * 15, -H * 15, W * 30, H * 30], "path": pts,
           "places": [{"name": k, "c": xy(trf.transform(*v), cx, cy)} for k, v in places.items()]}
    (OUT / "corridor.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print("corridor", img.shape, len(pts), "path pts", round(line.length / 1000, 1), "km")


if __name__ == "__main__":
    export_run(SYA, "sya", full=True)
    export_run(BID, "bid", full=False)
    corridor()
    for src, dst in ((ROOT / "docs/figures/aoi03_vs_ems.png", "val_bidur.png"), (ROOT / "docs/figures/aoi05_vs_ems.png", "val_phos.png")):
        shutil.copy(src, OUT / dst)
    v = json.loads((ROOT / "docs/validation_emsr927.json").read_text())
    (OUT / "validation.json").write_text(json.dumps(v), encoding="utf-8")
    print("done")
