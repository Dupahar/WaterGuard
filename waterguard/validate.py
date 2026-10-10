"""Compare a run with the Copernicus EMS EMSR927 reference maps (CHECKING ONLY).

Data rule: EMS products may only be used to check results. This module is the only code
that opens data/validation/, and the pipeline never imports it.

    python -m waterguard.validate --aoi 1 2 3 5

For each EMS area of interest (AOI), inside the area EMS actually analysed:
  - area agreement of our impact map vs EMS "observed event" polygons (precision, recall, F1, IoU)
  - a baseline that marks the whole valley floor (HAND <= our threshold) as hit, to show what the
    satellite change evidence adds beyond terrain alone
  - buildings: share of EMS damaged/destroyed building points that fall on our impact map
  - bridges: EMS destroyed bridges matched to an OSM bridge we rated likely/possibly damaged
AOI01 + AOI02 were used to choose thresholds; AOI03 + AOI05 are held out.
"""
import argparse
import glob
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize

from .config import DATA_DIR, ROOT
from .pipeline import run

VAL = DATA_DIR / "validation" / "emsr927"
EVENT = "2026-08-25T22:00:00Z"
TUNING = {1, 2}
PAD_DEG = 0.01


def _layers(aoi: int, kind: str) -> gpd.GeoDataFrame:
    fs = sorted(glob.glob(str(VAL / f"EMSR927_AOI{aoi:02d}_*{kind}*.json")))
    # prefer the latest product (monitoring > first delineation) when both exist
    mon = [f for f in fs if "MONIT" in f]
    fs = mon or fs
    if not fs:
        return gpd.GeoDataFrame(geometry=[], crs=4326)
    return gpd.GeoDataFrame(pd.concat([gpd.read_file(f) for f in fs], ignore_index=True), crs=4326)


def _scores(pred, ref, sel):
    tp = int((pred & ref & sel).sum()); fp = int((pred & ~ref & sel).sum()); fn = int((~pred & ref & sel).sum())
    return {"precision": round(tp / max(tp + fp, 1), 3), "recall": round(tp / max(tp + fn, 1), 3),
            "f1": round(2 * tp / max(2 * tp + fp + fn, 1), 3), "iou": round(tp / max(tp + fp + fn, 1), 3)}


def check_aoi(aoi: int) -> dict:
    aois = gpd.read_file(VAL / "aois.geojson")
    A = aois[aois.aoi == aoi]
    w, s, e, n = A.total_bounds
    bbox = tuple(round(v, 3) for v in (w - PAD_DEG, s - PAD_DEG, e + PAD_DEG, n + PAD_DEG))  # = dashboard presets
    facts = run(bbox, EVENT)
    out = DATA_DIR / "runs" / facts["run_id"]
    with rasterio.open(out / "impact.tif") as src:
        cls = src.read(1)
        tr, crs = src.transform, src.crs
    shape = cls.shape
    ref = _layers(aoi, "observedEventA")
    na = _layers(aoi, "notAnalysedA")
    ref_m = rasterize([(g, 1) for g in ref.to_crs(crs).geometry], out_shape=shape, transform=tr) > 0
    sel = rasterize([(g, 1) for g in A.to_crs(crs).geometry], out_shape=shape, transform=tr) > 0
    if len(na):
        sel &= ~(rasterize([(g, 1) for g in na.to_crs(crs).geometry], out_shape=shape, transform=tr) > 0)
    pred = np.isin(cls, (1, 2, 3))
    from .grid import Grid
    hand = Grid(crs, tr, shape[1], shape[0], bbox).read(str(Path(facts["terrain_workdir"]) / "hand.tif"))
    baseline = np.nan_to_num(hand, nan=999) <= facts["method"]["hand_max_m"]

    res = {"aoi": aoi, "name": A.iloc[0]["name"], "split": "tuning" if aoi in TUNING else "held-out",
           "ref_ha": round(float((ref_m & sel).sum()) * 0.01, 1),
           "ours_ha": round(float((pred & sel).sum()) * 0.01, 1),
           "area": _scores(pred, ref_m, sel), "valley_baseline": _scores(baseline, ref_m, sel)}

    # buildings: EMS damaged/destroyed points on our impact map (10 m tolerance)
    bu = _layers(aoi, "builtUpP")
    if len(bu):
        bu = bu[bu["damage_gra"].isin(["Destroyed", "Damaged", "Possibly damaged"])].to_crs(crs)
        bu = bu[bu.within(A.to_crs(crs).union_all())]
        cols, rows = ~tr * (bu.geometry.x.values, bu.geometry.y.values)
        rows, cols = rows.astype(int), cols.astype(int)
        ok = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
        import cv2
        pred_d = cv2.dilate(pred.astype("uint8"), np.ones((3, 3), "uint8")) > 0
        hit = np.zeros(len(bu), bool)
        hit[ok] = pred_d[rows[ok], cols[ok]]
        res["buildings"] = {"ems_damaged_points": int(len(bu)), "on_our_impact_map": int(hit.sum()),
                            "recall": round(float(hit.mean()), 3) if len(bu) else None,
                            "by_grade": {k: f"{int(hit[(bu['damage_gra'] == k).values].sum())}/{int((bu['damage_gra'] == k).sum())}"
                                         for k in ("Destroyed", "Damaged", "Possibly damaged")}}
    # bridges
    tp = _layers(aoi, "transportationP")
    if len(tp):
        eb = tp[tp["obj_type"].astype(str).str.startswith("214") & tp["damage_gra"].isin(["Destroyed", "Damaged"])].to_crs(crs)
        ours = gpd.read_file(out / "bridges.geojson").to_crs(crs)
        flagged = ours[ours["status"] != "no impact mapped"]
        matched = [bool(len(flagged)) and float(flagged.distance(p).min()) <= 50 for p in eb.geometry]
        osm_near = [bool(len(ours)) and float(ours.distance(p).min()) <= 50 for p in eb.geometry]
        res["bridges"] = {"ems_damaged_bridges": int(len(eb)), "in_pre_event_osm": int(sum(osm_near)),
                          "flagged_by_us": int(sum(matched))}
    res["run_id"] = facts["run_id"]
    return res


FALSE_ALARM_TESTS = [
    # same Syapru Besi box, fake event date a month before the flood: nothing happened -> expect ~0
    {"name": "placebo date (Syapru Besi, 20 Jul 2026)", "bbox": (85.313, 28.139, 85.358, 28.198),
     "date": "2026-07-20T00:00:00Z"},
    # Langtang Khola, a side valley east of Syapru Besi that the outburst flood did not run down
    {"name": "control valley (Langtang Khola, real event date)", "bbox": (85.365, 28.135, 85.445, 28.185),
     "date": EVENT},
    # Tadi Khola, a wide braided tributary joining the Trishuli near Bidur, not on the flood path
    {"name": "control tributary (Tadi Khola, real event date)", "bbox": (85.185, 27.85, 85.30, 27.93),
     "date": EVENT},
]


def false_alarms() -> list:
    out = []
    for t in FALSE_ALARM_TESTS:
        f = run(t["bbox"], t["date"])
        out.append({"test": t["name"], "area_km2": f["area"]["area_km2"], "impact_ha": f["impact"]["impact_ha"],
                    "of_which_riverbed_lower_confidence_ha": f["impact"]["riverbed_lower_confidence_ha"],
                    "buildings_likely_affected": f["damage"]["buildings_likely_affected"],
                    "bridges_likely_damaged": f["damage"]["bridges_likely_damaged"], "run_id": f["run_id"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", nargs="+", type=int, default=[1, 2, 3, 5])
    ap.add_argument("--no-false-alarm", action="store_true")
    a = ap.parse_args()
    results = [check_aoi(i) for i in a.aoi]
    if not a.no_false_alarm:
        results.append({"false_alarm_tests": false_alarms()})
    path = ROOT / "docs" / "validation_emsr927.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(results, indent=1))
    for r in results:
        print(json.dumps(r))


if __name__ == "__main__":
    main()
