"""One real inspector cell under a known misregistration -> public/data/cv/ for the film's OpenCV chapter.

Same setup as `python -m waterguard.validate --robustness` at 3 px: the after bands of a held-out run are
shifted by (2.4, -1.8) px, then the agent settles the cell with its realign and zoom tools. Everything the
scene draws comes from here: before/after chips, the SIFT matches with the MAGSAC++ inlier mask (same
parameters as vision.realign), the quadrants and the
agent's own trace. Run from the repo root:  .venv\\Scripts\\python -X utf8 video/scripts/export_cv.py
"""
import json, sys
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from waterguard import inspector, vision   # noqa: E402
from waterguard.validate import DATA_DIR, POST_BANDS   # noqa: E402

RUN, CELL, AREA = "58052edd5e", "r840c660", "Bidur · held-out"
SHIFT = (0.8 * 3, -0.6 * 3)
UP = 8                       # chip px per 10 m pixel
OUT = ROOT / "video/public/data/cv"


def shifted(ev0):
    A = np.float32([[1, 0, SHIFT[0]], [0, 1, SHIFT[1]]])
    bands = dict(ev0.bands)
    for b in POST_BANDS:
        bands[b] = cv2.warpAffine(ev0.bands[b], A, ev0.bands[b].shape[::-1], flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_REFLECT)
    return vision.Evidence(bands, ev0.impact, ev0.classes, ev0.transform, ev0.crs, ev0.run_dir)


def png(name, rgb01, ok):
    """display only: pixels with no clear look (masked cloud, shadow, no data) are filled from their
    neighbours so they don't print as blocks; the measurements never use them"""
    img = (np.clip(rgb01, 0, 1) * 255).astype("uint8")
    img = cv2.inpaint(img, (~ok).astype("uint8"), 3, cv2.INPAINT_TELEA)
    img = cv2.resize(img, None, fx=UP, fy=UP, interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(str(OUT / name), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))


def outline(name, mask):
    m = cv2.resize(mask.astype("uint8"), None, fx=UP, fy=UP, interpolation=cv2.INTER_NEAREST)
    edge = cv2.morphologyEx(m, cv2.MORPH_GRADIENT, np.ones((3, 3), "uint8")) > 0
    rgba = np.zeros(m.shape + (4,), "uint8")
    rgba[edge] = (255, 255, 255, 230)
    rgba[(m > 0) & ~edge] = (255, 255, 255, 28)
    cv2.imwrite(str(OUT / name), rgba)


def matches(pre_l, post_l, valid, up=2):
    """vision.realign's matching, keeping every ratio-test match and the MAGSAC++ inlier flag"""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    prep = lambda a: clahe.apply(cv2.resize(np.clip(np.nan_to_num(a) * 2.55, 0, 255).astype("uint8"), None, fx=up, fy=up,
                                            interpolation=cv2.INTER_CUBIC))
    mask = cv2.resize(valid.astype("uint8") * 255, None, fx=up, fy=up, interpolation=cv2.INTER_NEAREST)
    sift = cv2.SIFT_create(nfeatures=3000, contrastThreshold=0.01)
    k1, d1 = sift.detectAndCompute(prep(pre_l), mask)
    k2, d2 = sift.detectAndCompute(prep(post_l), mask)
    good = [p[0] for p in cv2.BFMatcher(cv2.NORM_L2).knnMatch(d1, d2, k=2) if len(p) == 2 and p[0].distance < 0.8 * p[1].distance]
    src = np.float32([k1[g.queryIdx].pt for g in good]) / up
    dst = np.float32([k2[g.trainIdx].pt for g in good]) / up
    A, inl = cv2.estimateAffine2D(src, dst, method=cv2.USAC_MAGSAC, ransacReprojThreshold=0.75, maxIters=5000, confidence=0.999)
    return len(k1), len(k2), [[round(float(s[0]), 2), round(float(s[1]), 2), round(float(d[0]), 2), round(float(d[1]), 2), int(i)]
                              for s, d, i in zip(src, dst, inl.ravel())]


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    ev0 = vision.load(DATA_DIR / "runs" / RUN)
    ev = shifted(ev0)
    cell = next(c for c in vision.cells(DATA_DIR / "runs" / RUN, ev0) if c["id"] == CELL)
    res = inspector.settle(ev, cell, inspector.RulePlanner(), tools=("realign", "zoom"))
    ecc = inspector.settle(ev, cell, inspector.RulePlanner(), tools=())
    assert res["verdict"] == "confirmed" and ecc["verdict"] != "confirmed", (res["verdict"], ecc["verdict"])

    R0, R1, C0, C1 = vision.window(ev, cell)
    win = (slice(R0, R1), slice(C0, C1))
    B = {k: v[win] for k, v in ev.bands.items()}
    pre = np.dstack([B["red_pre"], B["green_pre"], B["blue_pre"]])
    post = np.dstack([B["red_post"], B["green_post"], B["blue_post"]])
    clear = np.isfinite(pre).all(2) & np.isfinite(post).all(2)
    pre_d, post_d = vision._display(pre), vision._display(post)
    lab_pre, lab_post = cv2.cvtColor(pre_d, cv2.COLOR_RGB2Lab), cv2.cvtColor(post_d, cv2.COLOR_RGB2Lab)
    r = vision.realign(lab_pre[..., 0], lab_post[..., 0], clear)
    n1, n2, M = matches(lab_pre[..., 0], lab_post[..., 0], clear)

    ok_pre, ok_post = np.isfinite(pre).all(2), np.isfinite(post).all(2)
    png("pre.png", pre_d, ok_pre)
    png("post.png", post_d, ok_post)
    png("post_aligned.png", cv2.warpAffine(cv2.inpaint((post_d * 255).astype("uint8"), (~ok_post).astype("uint8"), 3, cv2.INPAINT_TELEA),
                                           r["warp"], ok_post.shape[1::-1], flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                           borderMode=cv2.BORDER_REFLECT) / 255.0, np.ones_like(ok_post))
    (r0, r1), (c0, c1) = cell["rows"], cell["cols"]
    core = np.zeros(clear.shape, bool)
    core[r0 - R0:r1 - R0, c0 - C0:c1 - C0] = True
    outline("flagged.png", ev.impact[win] & core)

    zoom = next(t for t in res["trace"] if t.get("tool") == "vision.zoom")
    out = {"run": RUN, "cell": CELL, "area": AREA, "shift_px": [SHIFT[0], SHIFT[1]], "up": UP,
           "window": [int(C1 - C0), int(R1 - R0)], "cell_box": [c0 - C0, r0 - R0, c1 - c0, r1 - r0],
           "keypoints": [n1, n2], "matches": M,
           "realign": {k: r[k] for k in ("dx", "dy", "inliers", "matches", "residual_px")},
           "impact_ha": cell["impact_ha"], "buildings_hit": cell["buildings_hit"],
           "verdict": res["verdict"], "ecc_only_verdict": ecc["verdict"],
           "zoom": zoom["parts"], "strong_parts": zoom["strong_parts"], "strong_share": zoom["strong_share"],
           "trace": res["trace"], "ecc_trace": ecc["trace"],
           # the stress test this cell is one case of (python -m waterguard.validate --robustness)
           "robustness": [{k: x[k] for k in ("shift_px", "variant", "cells", "confirmed_cells", "false_confirmations",
                                             "real_damage_ha_auto_confirmed_pct", "realigned_cells")}
                          for x in json.loads((ROOT / "docs/validation_robustness.json").read_text())["results"]
                          if x["split"] == "held-out"]}
    (OUT / "cell.json").write_text(json.dumps(out, indent=1, default=lambda o: bool(o) if isinstance(o, np.bool_) else float(o)))
    print(json.dumps({k: out[k] for k in ("window", "cell_box", "keypoints", "realign", "verdict", "ecc_only_verdict", "strong_parts", "strong_share")}))
    print(sum(m[4] for m in M), "inliers of", len(M))
    for t in res["trace"]:
        print(" ", t)
