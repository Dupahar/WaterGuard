"""Report figures: our impact map vs the EMSR927 reference (validation only) for each AOI.
    python scripts/figures.py
"""
import json
import sys
from pathlib import Path

import cv2
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from waterguard.validate import VAL, _layers  # noqa: E402
from waterguard.pipeline import RUNS_DIR  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "figures"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = [r for r in json.loads((OUT.parent / "validation_emsr927.json").read_text()) if "aoi" in r]
    aois = gpd.read_file(VAL / "aois.geojson")
    for r in res:
        d = RUNS_DIR / r["run_id"]
        with rasterio.open(d / "impact.tif") as src:
            cls, tr, crs = src.read(1), src.transform, src.crs
        ours = np.isin(cls, (1, 2, 3))
        ref = _layers(r["aoi"], "observedEventA").to_crs(crs)
        refm = rasterize([(g, 1) for g in ref.geometry], out_shape=cls.shape, transform=tr) > 0
        A = aois[aois.aoi == r["aoi"]].to_crs(crs)
        bg = cv2.imread(str(d / "s2_post.png"), cv2.IMREAD_UNCHANGED)
        img = (bg[:, :, :3] * 0.6).astype("uint8") if bg is not None else np.full(cls.shape + (3,), 50, "uint8")
        over = img.copy()
        over[ours & refm] = (60, 200, 60)      # both: green
        over[ours & ~refm] = (40, 140, 255)    # ours only: orange
        over[~ours & refm] = (255, 120, 60)    # EMS only: blue
        img = cv2.addWeighted(over, 0.7, img, 0.3, 0)
        for g in A.geometry:
            pts = np.array([~tr * xy for xy in g.exterior.coords], np.int32)
            cv2.polylines(img, [pts], True, (255, 255, 255), 2, cv2.LINE_AA)
        s = 900 / max(img.shape[:2])
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        cv2.putText(img, f"AOI{r['aoi']:02d} {r['name']} ({r['split']}) F1 {r['area']['f1']:.2f}", (10, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imwrite(str(OUT / f"aoi{r['aoi']:02d}_vs_ems.png"), img)
        print("wrote", OUT / f"aoi{r['aoi']:02d}_vs_ems.png")


if __name__ == "__main__":
    main()
