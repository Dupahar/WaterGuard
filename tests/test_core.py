"""Offline unit tests (no network).   python -m pytest tests/test_core.py -q"""
from types import SimpleNamespace as NS

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, box

from waterguard import access, copilot, detect
from waterguard.terrain import radar_blind


# ---------------------------------------------------------------- number verifier
def test_verifier_accepts_numbers_from_tools():
    res = [{"tool": "x", "result": {"cut": 3, "people": 1765, "km": 12.4}}]
    nums, bad = copilot.verify("3 villages cut off, est. 1,765 people, 12.4 km of road.", res)
    assert bad == [] and set(nums) == {"3", "1765", "12.4"}


def test_verifier_flags_invented_numbers_and_devanagari():
    res = [{"tool": "x", "result": {"cut": 3}}]
    _, bad = copilot.verify("३ गाउँ र ४२० जना", res)
    assert bad == ["420"]


def test_mask_replaces_both_scripts():
    out = copilot._mask("420 people (४२० जना)", ["420"])
    assert "420" not in out and "४२०" not in out


# ---------------------------------------------------------------- radar geometry
def test_radar_blind_layover_and_shadow():
    slope = np.array([[50.0, 50.0, 5.0]])
    # ascending pass looks ~east (80 deg): a west-facing slope (aspect 260) faces the radar -> layover;
    # an east-facing slope (aspect 80) faces away -> shadow if steep enough; gentle slope -> visible
    aspect = np.array([[260.0, 80.0, 80.0]])
    blind = radar_blind(slope, aspect, "ascending")
    assert blind.tolist() == [[True, True, False]]


# ---------------------------------------------------------------- detection
def test_detect_needs_valley_and_change():
    h, w = 40, 40
    hand = np.full((h, w), 200.0)
    hand[:, 15:25] = 5.0                      # valley floor strip
    streams = np.zeros((h, w), bool)
    streams[:, 20] = True
    z = np.full((h, w), 3.0)                  # strong radar change everywhere (also on the hills)
    S = NS(z=z, water_post=np.zeros((h, w), bool), water_pre=np.zeros((h, w), bool))
    r = detect.impact_map({"hand": hand, "streams": streams}, S, None)
    assert r["impact"][:, 15:25].mean() > 0.9   # valley flagged
    assert not r["impact"][:, :10].any()        # hills never flagged, despite radar change


# ---------------------------------------------------------------- cut-off analysis
def _osm(roads, places, health=None, buildings=None):
    crs = 32645
    empty = gpd.GeoDataFrame({"osm_id": [], "name": [], "name_ne": []}, geometry=[], crs=crs)
    return NS(roads=roads, places=places, health=health if health is not None else empty.assign(amenity=[], healthcare=[]),
              buildings=buildings if buildings is not None else empty.assign(building=[]), bridges=empty)


def test_village_behind_washed_out_road_is_cut_off():
    crs = 32645
    # road: town (0,0) -- village (2000,0), single road; impact polygon covers x in 900..1100
    roads = gpd.GeoDataFrame({"osm_id": ["way/1"], "name": ["r"], "highway": ["secondary"]},
                             geometry=[LineString([(0, 0), (1000, 0), (2000, 0)])], crs=crs)
    places = gpd.GeoDataFrame({"osm_id": ["n/1", "n/2"], "name": ["Town", "Village"], "name_ne": [None, None],
                               "place": ["town", "village"]}, geometry=[Point(0, 0), Point(2000, 0)], crs=crs)
    impact = gpd.GeoDataFrame(geometry=[box(900, -50, 1100, 50)], crs=crs)
    osm = _osm(roads, places)
    dmg = {"bridges": osm.bridges.assign(status=pd.Series(dtype=str)),
           "health": osm.health.assign(status=pd.Series(dtype=str))}
    boundary = box(-5000, -5000, 7000, 5000)
    out = access.analyse(osm, dmg, impact, crs, boundary)
    S = out["settlements"].set_index("name")
    assert S.loc["Village", "vehicle_status"] == "cut off"
    assert S.loc["Town", "vehicle_status"] == "cut off" or S.loc["Town", "vehicle_status"] == "connected"
