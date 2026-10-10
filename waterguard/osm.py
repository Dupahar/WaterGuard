"""Pre-event OpenStreetMap snapshot via the ohsome API v2, with a provenance audit.

Data rule: only OSM *as it was before the event* may be used. We request a historic
snapshot and then verify that no feature in it was edited at or after the snapshot time.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

import geopandas as gpd
import pandas as pd
import requests

from .config import CACHE_DIR, OHSOME_API_KEY, OHSOME_BASE_URL
from .providers.base import as_utc

ROAD_CLASSES = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
                "residential", "service", "track", "path", "footway")
FILTER = ("building=* or highway in ({}) or bridge=* or amenity in (hospital,clinic,doctors,health_post) "
          "or healthcare=* or place in (city,town,village,hamlet,suburb,neighbourhood)"
          ).format(",".join(ROAD_CLASSES))

# The snapshot is taken this long before the event, so last-minute edits can't leak in.
SNAPSHOT_MARGIN = timedelta(hours=24)


@dataclass
class OSMLayers:
    buildings: gpd.GeoDataFrame
    roads: gpd.GeoDataFrame
    bridges: gpd.GeoDataFrame
    health: gpd.GeoDataFrame
    places: gpd.GeoDataFrame
    audit: dict


def _fetch(bbox, timestamp: str):
    if not OHSOME_API_KEY:
        raise RuntimeError("OHSOME_API_KEY not set")
    key = hashlib.sha1(f"{bbox}|{timestamp}|{FILTER}".encode()).hexdigest()[:16]
    path = CACHE_DIR / f"osm_{key}.parquet"
    if not path.exists():
        r = requests.post(f"{OHSOME_BASE_URL}/extraction/features.parquet", timeout=300,
                          headers={"Authorization": OHSOME_API_KEY},
                          json={"aoi": [round(v, 5) for v in bbox], "time": timestamp,
                                "filter": FILTER, "clip": True})
        if r.status_code != 200:
            raise RuntimeError(f"ohsome HTTP {r.status_code}: {r.text[:300]}")
        path.write_bytes(r.content)
    gdf = gpd.read_parquet(path, to_pandas_kwargs={"maps_as_pydicts": "strict"})
    return gdf.set_geometry("geom").rename_geometry("geometry")


def _name(tags):
    return tags.get("name:en") or tags.get("name") or tags.get("name:ne")


def load_pre_event_osm(bbox, event_time) -> OSMLayers:
    event_time = as_utc(event_time)
    snap = event_time - SNAPSHOT_MARGIN
    ts = f"{snap:%Y-%m-%dT%H:%M:%SZ}"
    g = _fetch(bbox, ts)
    t = g["tags"]

    latest_edit = g["edit_timestamp"].max()
    audit = {
        "source": "OpenStreetMap via ohsome API v2",
        "snapshot_time": ts,
        "event_time": f"{event_time:%Y-%m-%dT%H:%M:%SZ}",
        "features": int(len(g)),
        "latest_edit_in_snapshot": None if pd.isna(latest_edit) else latest_edit.isoformat(),
        "features_edited_after_snapshot": int((g["edit_timestamp"] > pd.Timestamp(snap)).sum()),
    }
    audit["compliant"] = audit["features_edited_after_snapshot"] == 0
    if not audit["compliant"]:
        raise RuntimeError(f"OSM provenance audit failed: {json.dumps(audit)}")

    def sel(mask, cols):
        out = g[mask].copy()
        out["osm_id"] = out["osm_type"] + "/" + out["osm_id"].astype(str)
        out["name"] = out["tags"].apply(_name)
        out["name_ne"] = out["tags"].apply(lambda d: d.get("name:ne") or d.get("name"))
        for c in cols:
            out[c] = out["tags"].apply(lambda d, c=c: d.get(c))
        return out.drop(columns=["tags"]).reset_index(drop=True)

    is_bridge = t.apply(lambda d: d.get("bridge") not in (None, "no"))
    is_health = t.apply(lambda d: d.get("amenity") in ("hospital", "clinic", "doctors", "health_post") or "healthcare" in d)
    return OSMLayers(
        buildings=sel(t.apply(lambda d: "building" in d), ["building"]),
        roads=sel(t.apply(lambda d: d.get("highway") in ROAD_CLASSES)
                  & g.geometry.geom_type.isin(["LineString", "MultiLineString"]), ["highway", "bridge"]),
        bridges=sel(is_bridge, ["highway", "bridge"]),
        health=sel(is_health, ["amenity", "healthcare"]),
        places=sel(t.apply(lambda d: "place" in d), ["place"]),
        audit=audit,
    )
