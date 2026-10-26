"""Who and what is exposed, beyond OpenStreetMap: open building footprints and gridded population.

OpenStreetMap is patchy in rural South Asia: whole hamlets have no mapped buildings, so a cut-off
analysis on OSM alone misses them, and "people" was only buildings x average household size.

  buildings    Google Open Buildings v3 + Microsoft Global ML Building Footprints, combined by VIDA
               (Source Cooperative, GeoParquet by country). Footprints come from imagery taken before
               the event (up to 2023), so they are pre-event by construction. Only those that do not
               overlap an OSM building are added: OSM keeps priority (names, building types).
               The country file is never downloaded whole: its row groups carry bounding-box
               statistics, and only the row groups that overlap the area are read.
  population   WorldPop constrained 100 m population for the event year (R2025A, 2015-2030),
               read as a window over HTTP. Each 100 m cell's people are shared equally between the
               buildings whose centre falls in it (dasymetric), so a settlement's people are the sum
               over its own buildings. People in a cell with no footprint go to the nearest building
               within 250 m (the two layers' settlement masks differ); anything further is reported.

Neither changes the impact map (that stays the satellite evidence, validated against EMS); they
change what is counted on it. The mode is part of the run id (pipeline.run_id), so a report made
with OSM alone still re-runs to the same result.
"""
import hashlib
import json
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely
from rasterio.windows import from_bounds

from .config import CACHE_DIR

OB_URL = ("https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet/by_country/"
          "country_iso={iso}/{iso}.parquet")
WP_URL = ("https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/{year}/{ISO}/v1/100m/constrained/"
          "{iso}_pop_{year}_CN_100m_R2025A_v1.tif")
MIN_CONFIDENCE = 0.70      # Google's model score; Microsoft footprints carry their own (see confidence column)
MIN_AREA_M2 = 12.0         # smaller footprints are mostly sheds and noise at this resolution
REASSIGN_M = 250.0         # people in a cell with no footprint go to the nearest building this close
CACHE = CACHE_DIR / "exposure"
HH_SIZE = 4.37             # persons per household, Nepal census 2021: the fallback where there is no population layer


@dataclass
class Exposure:
    buildings: gpd.GeoDataFrame     # OSM + added open footprints (EPSG:4326), column 'source', 'people'
    audit: dict


def country_codes(bbox) -> list[str]:
    """ISO 3166 alpha-3 codes of the countries the area touches (OSM Nominatim, centre and corners)."""
    import pycountry
    w, s, e, n = bbox
    out = []
    for lon, lat in (((w + e) / 2, (s + n) / 2), (w, s), (w, n), (e, s), (e, n)):
        r = requests.get("https://nominatim.openstreetmap.org/reverse", timeout=20,
                         params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 3},
                         headers={"User-Agent": "WaterGuard flood mapping (github.com/Dupahar/WaterGuard)"})
        cc = (r.json().get("address") or {}).get("country_code") if r.ok else None
        c = pycountry.countries.get(alpha_2=cc.upper()) if cc else None
        if c and c.alpha_3 not in out:
            out.append(c.alpha_3)
    return out


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts).encode()).hexdigest()[:16]


def open_buildings(bbox, iso: str) -> gpd.GeoDataFrame:
    """Footprints inside bbox from the combined Google + Microsoft dataset (EPSG:4326, cached)."""
    import fsspec
    import pyarrow.parquet as pq
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"ob_{iso}_{_key(bbox)}.parquet"
    if cached.exists():
        return gpd.read_parquet(cached)
    w, s, e, n = bbox
    with fsspec.open(OB_URL.format(iso=iso), "rb", block_size=2 ** 20) as f:
        pf = pq.ParquetFile(f)
        md = pf.metadata
        paths = [md.row_group(0).column(j).path_in_schema for j in range(md.num_columns)]
        col = {c: paths.index(c) for c in ("bbox.xmin", "bbox.ymin", "bbox.xmax", "bbox.ymax")}
        keep = []
        for i in range(md.num_row_groups):
            st = {c: md.row_group(i).column(j).statistics for c, j in col.items()}
            if any(x is None or not x.has_min_max for x in st.values()):
                keep.append(i)
                continue
            if st["bbox.xmin"].min <= e and st["bbox.xmax"].max >= w and st["bbox.ymin"].min <= n and st["bbox.ymax"].max >= s:
                keep.append(i)
        t = pf.read_row_groups(keep, columns=["bf_source", "confidence", "area_in_meters", "geometry", "bbox"]).to_pandas() \
            if keep else pd.DataFrame(columns=["bf_source", "confidence", "area_in_meters", "geometry", "bbox"])
    if len(t):
        bb = pd.DataFrame(list(t.pop("bbox")))
        t = t[(bb.xmin <= e).values & (bb.xmax >= w).values & (bb.ymin <= n).values & (bb.ymax >= s).values]
    g = gpd.GeoDataFrame({"source": t["bf_source"].astype(str).values, "confidence": t["confidence"].values,
                          "area_m2": t["area_in_meters"].values},
                         geometry=shapely.from_wkb(t["geometry"].values) if len(t) else [], crs=4326)
    g.to_parquet(cached)
    return g


def population(bbox, iso: str, year: int):
    """WorldPop constrained 100 m people for the area: (array, transform, crs) or None if not published."""
    import os
    import rasterio
    year = min(max(int(year), 2015), 2030)
    url = WP_URL.format(year=year, ISO=iso.upper(), iso=iso.lower())
    local = CACHE / "worldpop" / url.rsplit("/", 1)[1]
    try:
        if not local.exists():   # the WorldPop server has no range requests: fetch the country file once
            local.parent.mkdir(parents=True, exist_ok=True)
            tmp = local.with_suffix(".part")
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(2 ** 20):
                        f.write(chunk)
            os.replace(tmp, local)
        with rasterio.open(local) as src:
            win = from_bounds(*bbox, transform=src.transform).round_offsets().round_lengths()
            a = src.read(1, window=win, boundless=True, fill_value=0).astype("float64")
            nod = src.nodata
            tr = src.window_transform(win)
            crs = src.crs
    except Exception:
        return None
    if nod is not None:
        a[a == nod] = 0
    a[~np.isfinite(a) | (a < 0)] = 0
    return a, tr, crs, url


def allocate(buildings: gpd.GeoDataFrame, pop) -> tuple[np.ndarray, dict]:
    """People per building: each population cell shared equally among the buildings centred in it."""
    a, tr, crs, url = pop
    pts = buildings.to_crs(crs).geometry.representative_point()
    col, row = ~tr * (pts.x.values, pts.y.values)
    r, c = np.floor(row).astype(int), np.floor(col).astype(int)
    inside = (r >= 0) & (r < a.shape[0]) & (c >= 0) & (c < a.shape[1])
    cell = np.where(inside, r * a.shape[1] + c, -1)
    n = np.bincount(cell[inside], minlength=a.size)
    flat = a.ravel()
    people = np.zeros(len(buildings))
    people[inside] = flat[cell[inside]] / n[cell[inside]]
    total = float(flat.sum())
    housed = float(flat[n > 0].sum())
    # WorldPop's own settlement mask and these footprints do not line up cell for cell: people in a cell
    # with no footprint go to the nearest building within REASSIGN_M, so they are not silently dropped
    orphan = np.flatnonzero((flat > 0) & (n == 0))
    moved = 0.0
    if len(orphan) and len(buildings):
        from scipy.spatial import cKDTree
        utm = buildings.estimate_utm_crs()
        bxy = np.c_[pts.to_crs(utm).x, pts.to_crs(utm).y]
        rr, cc = np.divmod(orphan, a.shape[1])
        cx, cy = tr * (cc + 0.5, rr + 0.5)
        oxy = gpd.GeoSeries(gpd.points_from_xy(cx, cy), crs=crs).to_crs(utm)
        d, j = cKDTree(bxy).query(np.c_[oxy.x, oxy.y], distance_upper_bound=REASSIGN_M)
        ok = np.isfinite(d)
        np.add.at(people, j[ok], flat[orphan[ok]])
        moved = float(flat[orphan[ok]].sum())
    return people, {"source": url, "people_in_area": round(total), "people_in_cells_with_a_building": round(housed),
                    f"people_moved_to_a_building_within_{REASSIGN_M:.0f}_m": round(moved),
                    "share_not_on_any_building": round(1 - (housed + moved) / total, 3) if total else None,
                    "buildings_in_cells_without_people": int((inside & (flat[np.where(inside, cell, 0)] == 0)).sum())}


def load(bbox, event_year: int, osm_buildings: gpd.GeoDataFrame) -> Exposure:
    """OSM buildings + open footprints that OSM lacks, each with an estimated number of people."""
    isos = country_codes(bbox)
    osm_b = osm_buildings.to_crs(4326).assign(source="osm")
    added, per = [], {}
    for iso in isos:
        try:
            ob = open_buildings(bbox, iso)
        except Exception as e:      # dataset unreachable: carry on with OSM, and say so
            per[iso] = f"unavailable: {type(e).__name__}"
            continue
        ob = ob[(ob["confidence"].fillna(1.0) >= MIN_CONFIDENCE) & (ob["area_m2"] >= MIN_AREA_M2)]
        if len(osm_b) and len(ob):
            hit = shapely.STRtree(osm_b.geometry.values).query(ob.geometry.values, predicate="intersects")[0]
            ob = ob[~np.isin(np.arange(len(ob)), hit)]
        per[iso] = {k: int(v) for k, v in ob["source"].value_counts().items()}
        added.append(ob.assign(osm_id=[f"open/{iso}/{s}/{i}" for i, s in enumerate(ob["source"])], name=None, name_ne=None,
                               building="yes"))
    b = pd.concat([osm_b] + added, ignore_index=True) if added else osm_b.reset_index(drop=True)
    b = gpd.GeoDataFrame(b[["osm_id", "name", "name_ne", "building", "source", "geometry"]], geometry="geometry", crs=4326)
    pop_audit = None
    b["people"] = np.nan
    for iso in isos:
        pop = population(bbox, iso, event_year)
        if pop is not None:
            b["people"], pop_audit = allocate(b, pop)
            break
    audit = {"countries": isos,
             "buildings": {"osm": int((b["source"] == "osm").sum()), "added_open_footprints": per,
                           "source": "Google Open Buildings v3 + Microsoft Building Footprints (VIDA, Source Cooperative)",
                           "min_confidence": MIN_CONFIDENCE, "min_area_m2": MIN_AREA_M2},
             "population": pop_audit or {"source": None, "note": f"no WorldPop layer: buildings x {HH_SIZE} persons/household"}}
    return Exposure(b, audit)
