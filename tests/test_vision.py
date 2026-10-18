"""OpenCV inspection toolkit and inspector policy on synthetic scenes (no network).

    python -m pytest tests/test_vision.py -q
"""
import cv2
import numpy as np
import pytest
import rasterio

from waterguard import inspector, vision
from waterguard.pipeline import EVIDENCE_BANDS


def _texture(h, w, seed):
    rng = np.random.default_rng(seed)
    t = cv2.GaussianBlur(rng.random((h, w)).astype("float32"), (0, 0), 1.5)
    return (t - t.min()) / (t.max() - t.min())          # 0..1, visible texture


def test_coregister_recovers_subpixel_shift():
    base = _texture(200, 200, 1) * 100
    dx, dy = 0.6, -0.4
    moved = cv2.warpAffine(base, np.float32([[1, 0, dx], [0, 1, dy]]), (200, 200), flags=cv2.INTER_CUBIC,
                           borderMode=cv2.BORDER_REFLECT)
    got = vision.coregister(base, moved, np.ones(base.shape, bool))
    assert got is not None
    assert abs(got[0] - dx) < 0.1 and abs(got[1] - dy) < 0.1 and got[2] > 0.9


def test_coregister_refuses_unrelated_images():
    assert vision.coregister(_texture(120, 120, 1) * 100, _texture(120, 120, 2) * 100, np.ones((120, 120), bool)) is None


@pytest.fixture
def scene(tmp_path):
    """A valley with forest; a debris fan replaces the forest in the middle after the 'flood'."""
    H = W = 150
    tex = _texture(H, W, 3)
    band = {b: np.zeros((H, W), "float32") for b in EVIDENCE_BANDS}
    forest = (0.03 + 0.02 * tex, 0.06 + 0.02 * tex, 0.03 + 0.01 * tex)
    rough = _texture(H, W, 4)                         # boulders: a different pattern, not the forest's
    debris = (0.16 + 0.06 * rough, 0.15 + 0.06 * rough, 0.13 + 0.06 * rough)
    hit = np.zeros((H, W), bool)
    hit[50:100, 45:105] = True
    for i, k in enumerate(("red", "green", "blue")):
        band[f"{k}_pre"] = forest[i]
        band[f"{k}_post"] = np.where(hit, debris[i], forest[i])
    band["ndvi_pre"][:] = 0.7
    band["ndvi_post"] = np.where(hit, 0.1, 0.7).astype("float32")
    band["ndwi_pre"][:], band["ndwi_post"][:] = -0.5, -0.5
    band["sar_z"] = np.where(hit, 2.5, 0.6).astype("float32")
    band["hand_m"][:] = 20.0
    band["source"][:] = 1
    ev = vision.Evidence(band, hit, hit.astype("uint8"), rasterio.Affine(10, 0, 300000, 0, -10, 3100000),
                         rasterio.crs.CRS.from_epsg(32645), tmp_path)
    cell = {"id": "r60c60", "rows": [60, 120], "cols": [60, 120]}
    return ev, cell


def test_measure_sees_debris_against_reference(scene, tmp_path):
    ev, cell = scene
    m = vision.measure(ev, cell, tmp_path / "chip.png")
    assert m["delta_e_contrast"] > 15
    assert m["ndvi_drop_contrast"] > 0.5
    assert m["sar_z_contrast"] > 1.5
    assert m["clear_share"] == 1.0
    img = cv2.imread(str(tmp_path / "chip.png"))
    assert img is not None and img.shape[1] == 3 * img.shape[0]         # before | after | change
    assert all(inspector.lines(m).values())
    assert inspector.RulePlanner().decide(cell, m, None, True)[0] == "confirm"


def test_no_change_is_not_confirmed(scene):
    ev, cell = scene
    for k in ("red", "green", "blue"):
        ev.bands[f"{k}_post"] = ev.bands[f"{k}_pre"].copy()
    ev.bands["ndvi_post"] = ev.bands["ndvi_pre"].copy()
    ev.bands["sar_z"][:] = 0.6
    m = vision.measure(ev, cell)
    action, _ = inspector.RulePlanner().decide(cell, m, None, True)
    assert action == "ask_human"          # nothing agrees: too weak to be worth a download, goes to a person


def test_reverted_change_is_flagged_not_removed(scene):
    ev, cell = scene
    m = {"delta_e_contrast": 13, "ndvi_drop_contrast": 0.2, "ssim_dissimilarity_contrast": 0.2,
         "sar_z_contrast": 0.1, "clear_share": 0.9}
    later = {"delta_e_contrast": 1.0, "ndvi_drop_contrast": 0.0, "clear_share": 0.9}
    assert inspector.RulePlanner().decide(cell, m, None, True)[0] == "look_later"
    assert inspector.RulePlanner().decide(cell, m, later, False)[0] == "flag"


def test_llm_cannot_confirm_without_evidence(monkeypatch, scene):
    ev, cell = scene
    cell.update(impact_ha=1, buildings_hit=0, road_segments_cut=0, people_nearby_est=0)
    P = inspector.LLMPlanner.__new__(inspector.LLMPlanner)
    P.fallback = inspector.RulePlanner()
    P.call = lambda msgs, tools: ("", [("1", "confirm", {"reason": "looks bad"})], None)
    weak = {"delta_e_contrast": 1, "ndvi_drop_contrast": 0, "ssim_dissimilarity_contrast": 0, "sar_z_contrast": 0,
            "clear_share": 1.0}
    assert P.decide(cell, weak, None, True)[0] == "ask_human"


def test_settlement_sampling_ignores_osm_feature_order():
    """An independent re-run gets OSM features in another order; the reachability sample must not change."""
    from types import SimpleNamespace
    import geopandas as gpd
    from shapely.geometry import Point, box
    from waterguard import access
    rng = np.random.default_rng(0)
    pts = [Point(85.33 + rng.normal(0, 0.002), 28.16 + rng.normal(0, 0.002)) for _ in range(300)]
    blds = gpd.GeoDataFrame({"osm_id": range(300)}, geometry=[p.buffer(0.00005) for p in pts], crs=4326)
    places = gpd.GeoDataFrame({"name": ["Syabru Bensi"], "name_ne": [None], "place": ["village"]},
                              geometry=[Point(85.33, 28.16)], crs=4326)
    crs = "EPSG:32645"
    boundary = gpd.GeoSeries([box(85.3, 28.13, 85.36, 28.19)], crs=4326).to_crs(crs).iloc[0]
    a = access.settlements(SimpleNamespace(places=places, buildings=blds), crs, boundary)
    b = access.settlements(SimpleNamespace(places=places, buildings=blds.sample(frac=1, random_state=7)), crs, boundary)
    assert [sorted(s) for s in a["sample"]] == [sorted(s) for s in b["sample"]]
