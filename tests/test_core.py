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


def test_web_numbers_are_not_counted_as_map_checked():
    res = [{"tool": "list_cut_off", "result": {"count": 3, "people": 1765}},
           {"tool": "web_reports", "result": {"results": [{"url": "https://example.org/a", "title": "t", "site": "example.org",
                                                          "published": "2026-08-28", "snippet": "Officials report 41 dead"}]}}]
    nums, bad, web = copilot.verify_split("3 villages cut off (1,765 people, est.). Reported by example.org: 41 dead; 99 missing.", res)
    assert web == ["41"] and bad == ["99"]
    assert copilot._sources(res)[0]["site"] == "example.org"


def test_web_reports_need_a_key(monkeypatch):
    from waterguard import web
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert "error" in web.reports("roads reopened", "2026-08-25T22:00:00Z")
    assert "web_reports" not in {t["name"] for t in copilot.tool_specs()}


def test_web_reports_keep_only_stories_about_the_area(monkeypatch, tmp_path):
    from waterguard import web
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    monkeypatch.setattr(web, "CACHE", tmp_path)
    res = [{"title": "Nepal flash floods: hundreds missing", "url": "https://bbc.co.uk/a", "content": "Rasuwa ..."},
           {"title": "Deadly shooting at a bar", "url": "https://cnn.com/b", "content": "... more videos: Nepal flood"},
           {"title": "Highway reopens", "url": "https://reuters.com/c", "content": "road to Syabru Bensi reopened"},
           {"title": "Post", "url": "ftp://x/y", "content": "Nepal flood"}]

    class R:
        def raise_for_status(self): pass
        def json(self): return {"query": "q", "results": res}
    monkeypatch.setattr(web.requests, "post", lambda *a, **k: R())
    r = web.reports("relief", "2026-08-25T22:00:00Z", place_hint="Syabru Bensi Nepal")
    assert [x["site"] for x in r["results"]] == ["bbc.co.uk", "reuters.com"]
    assert list(tmp_path.glob("*.json"))                      # cached: the answer can be traced to what was read


def test_thousands_separators_in_evidence_and_masking():
    res = [{"tool": "web_reports", "result": {"results": [{"snippet": "would reconnect 2,678 people"}]}}]
    _, bad, web = copilot.verify_split("Reported by rieti.go.jp: 2,678 people; also 5,555 more.", res)
    assert web == ["2678"] and bad == ["5555"]
    assert copilot._mask("about 5,555 people", ["5555"]) == "about [unverified] people"


def test_copilot_falls_back_to_bedrock(monkeypatch):
    monkeypatch.setattr(copilot, "_backend", lambda: "nebius")
    monkeypatch.setattr(copilot, "tool_specs", lambda: copilot.TOOL_SPECS)

    def down(*a, **k):
        raise ConnectionError("token factory unreachable")
    monkeypatch.setattr(copilot, "_call_openai", down)
    monkeypatch.setattr(copilot, "_call_bedrock", lambda msgs, tools: ("No mapped data on that.", [], None))
    r = copilot.ask("e34c30aded", "hello")
    assert r["backend"] == "bedrock (fallback)" and r["answer"] == "No mapped data on that."


def test_worldpop_is_shared_by_buildings_and_orphans_go_to_the_nearest():
    import geopandas as gpd
    import numpy as np
    import rasterio
    from shapely.geometry import box
    from waterguard import exposure
    tr = rasterio.Affine(0.001, 0, 85.0, 0, -0.001, 28.0)          # ~100 m cells
    a = np.zeros((3, 3)); a[0, 0] = 10; a[0, 1] = 6; a[2, 2] = 4     # (0,1) has people but no building
    b = gpd.GeoDataFrame(geometry=[box(85.0002, 27.9992, 85.0004, 27.9994), box(85.0005, 27.9995, 85.0007, 27.9997),
                                   box(85.0022, 27.9972, 85.0024, 27.9974)], crs=4326)
    people, audit = exposure.allocate(b, (a, tr, rasterio.crs.CRS.from_epsg(4326), "test"))
    assert round(people.sum()) == 20 and audit["share_not_on_any_building"] == 0
    assert people[2] == 4 and people[0] + people[1] == 16          # the orphan cell went to a building next to it


def test_run_id_keeps_osm_only_reports_reproducible():
    from waterguard.pipeline import run_id
    bb, ev = [85.313, 28.139, 85.358, 28.198], "2026-08-25T22:00:00Z"
    assert run_id(bb, ev) == run_id(bb, ev, "osm") == "e34c30aded"   # the anchored report
    assert run_id(bb, ev, "open") != run_id(bb, ev)


def test_public_server_rejects_bad_or_costly_requests(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from waterguard import server
    for bbox, date in (([85.4, 28.1, 85.3, 28.2], "2026-08-26"), ([85.3, 28.1, 85.4, 28.2], "1999-01-01"),
                       ([85.3, 28.1, 85.4, 28.2], "not a date")):
        with pytest.raises(HTTPException) as e:
            server.start(server.RunReq(bbox=bbox, date=date))
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        server.chat("e34c30aded", server.ChatReq(message="x" * 601))
    assert e.value.status_code == 400
    monkeypatch.setattr(server, "_busy", lambda: server.MAX_QUEUE)
    with pytest.raises(HTTPException) as e:
        server.start(server.RunReq(bbox=[85.30, 28.10, 85.31, 28.11], date="2026-08-26"))
    assert e.value.status_code == 429
