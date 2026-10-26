"""What was damaged: overlay pre-event OSM buildings, roads and bridges on the impact map."""
import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import shapes
from shapely.geometry import shape

BUFFER_M = 20   # a feature within this distance of mapped impact is "possibly affected"
HH_SIZE = 4.37  # persons per household, Nepal census 2021 (same assumption as access.py)


def vectorize(mask: np.ndarray, grid, min_area_m2=2000, simplify_m=10) -> gpd.GeoDataFrame:
    """Binary mask -> polygons in the grid CRS."""
    geoms = [shape(g) for g, v in shapes(mask.astype("uint8"), mask=mask, transform=grid.transform) if v]
    gdf = gpd.GeoDataFrame(geometry=geoms, crs=grid.crs)
    if gdf.empty:
        return gdf
    gdf = gdf[gdf.area >= min_area_m2].copy()
    gdf["geometry"] = gdf.geometry.simplify(simplify_m)
    gdf["area_ha"] = (gdf.area / 1e4).round(2)
    return gdf.reset_index(drop=True)


def _hit(features: gpd.GeoDataFrame, impact: gpd.GeoDataFrame):
    """Returns (likely, possible) boolean Series: intersects impact / within BUFFER_M of it."""
    if features.empty or impact.empty:
        z = pd.Series(False, index=features.index)
        return z, z
    core = impact.geometry.union_all()
    near = core.buffer(BUFFER_M)
    likely = features.geometry.intersects(core)
    possible = features.geometry.intersects(near) & ~likely
    return likely, possible


def assess(osm, impact: gpd.GeoDataFrame, crs) -> dict:
    """impact: polygons (grid CRS) of flooded / debris-covered ground."""
    b = osm.buildings.to_crs(crs)
    r = osm.roads.to_crs(crs)
    br = osm.bridges.to_crs(crs)
    h = osm.health.to_crs(crs)

    b_l, b_p = _hit(b, impact)
    b = b.assign(status=np.select([b_l, b_p], ["likely affected", "possibly affected"], "not mapped as affected"))

    br_l, br_p = _hit(br, impact)
    br = br.assign(status=np.select([br_l, br_p], ["likely damaged", "possibly damaged"], "no impact mapped"))

    h_l, h_p = _hit(h, impact)
    h = h.assign(status=np.select([h_l, h_p], ["likely affected", "possibly affected"], "not mapped as affected"))

    # road length inside the impact footprint, by class
    if impact.empty or r.empty:
        cut = r.iloc[:0].copy()
    else:
        cut = gpd.overlay(r[["osm_id", "name", "highway", "geometry"]], impact[["geometry"]],
                          how="intersection", keep_geom_type=True)
    cut_km = (cut.length.groupby(cut["highway"]).sum() / 1000).round(2).to_dict() if len(cut) else {}
    total_km = (r.length.groupby(r["highway"]).sum() / 1000).round(2).to_dict()

    return {
        "buildings": b, "bridges": br, "health": h, "roads_cut": cut,
        "summary": {
            "buildings_total": int(len(b)),
            "buildings_likely_affected": int(b_l.sum()),
            "buildings_possibly_affected": int(b_p.sum()),
            "people_est_in_likely_affected_buildings": int(round(float(np.nansum(b.loc[b_l, "people"]))))
                if "people" in b and b["people"].notna().any() else int(round(int(b_l.sum()) * HH_SIZE)),
            "bridges_total": int(len(br)),
            "bridges_likely_damaged": int(br_l.sum()),
            "bridges_possibly_damaged": int(br_p.sum()),
            "health_facilities_total": int(len(h)),
            "health_facilities_affected": int(h_l.sum() + h_p.sum()),
            "road_km_total": round(sum(total_km.values()), 1),
            "road_km_in_impact": round(sum(cut_km.values()), 2),
            "road_km_in_impact_by_class": cut_km,
            "impact_area_ha": round(float(impact["area_ha"].sum()), 1) if len(impact) else 0.0,
        },
    }
