"""Who is cut off: settlements that had a road connection to a town or health facility before the
event and no longer have one, using the pre-event OSM road network with impacted segments removed.

- Graph: every OSM road vertex is a node, consecutive vertices are edges (so junctions in the
  middle of a way are honoured). Two networks are analysed:
    vehicle = motorable roads and tracks;  foot = vehicle + paths/footways (trails matter in the hills).
- An edge is cut if it crosses mapped impact or a bridge rated "likely damaged".
- Destinations: towns/cities, health facilities, and road exits at the edge of the analysis area
  (the road continues to the wider network, e.g. towards Kathmandu).
- A settlement is judged by up to SAMPLE of its own buildings, each snapped to its nearest road:
  cut off = none of them can still reach a destination (one flooded junction next to the place
  point must not strand a whole suburb). "people stranded" = people x share of buildings cut off.
- Settlements: OSM place points (village, hamlet, town...) plus unnamed clusters of >= MIN_CLUSTER
  buildings that have no named place nearby, so unmapped hamlets are not missed.
- People: estimated as all buildings x NEPAL_HH_SIZE (2021 census average household size).
  This is an assumption, stated wherever the number is shown.
"""
import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import LineString, Point

VEHICLE = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
           "service", "track"}
FOOT = VEHICLE | {"path", "footway"}
SNAP_M = 400            # settlement -> road snapping distance
EXIT_MARGIN_M = 150     # a road vertex this close to the area edge is an exit to the outside network
CLUSTER_EPS_M = 120
MIN_CLUSTER = 8
NEPAL_HH_SIZE = 4.37    # persons per household, National Population and Housing Census 2021
MAIN_PLACES = ("city", "town")
SAMPLE = 25             # buildings sampled per settlement for the reachability test


def _key(x, y):
    return (round(x, 1), round(y, 1))


def build_graph(roads: gpd.GeoDataFrame, classes) -> tuple[nx.Graph, gpd.GeoDataFrame]:
    G = nx.Graph()
    segs = []
    for row in roads[roads["highway"].isin(classes)].itertuples():
        geoms = getattr(row.geometry, "geoms", [row.geometry])
        for line in geoms:
            c = list(line.coords)
            for a, b in zip(c[:-1], c[1:]):
                ka, kb = _key(*a[:2]), _key(*b[:2])
                if ka == kb:
                    continue
                L = float(np.hypot(kb[0] - ka[0], kb[1] - ka[1]))
                G.add_edge(ka, kb, length=L, osm_id=row.osm_id, name=row.name, highway=row.highway)
                segs.append((ka, kb, LineString([ka, kb])))
    seg_gdf = gpd.GeoDataFrame({"u": [s[0] for s in segs], "v": [s[1] for s in segs]},
                               geometry=[s[2] for s in segs], crs=roads.crs)
    return G, seg_gdf


def settlements(osm, crs, boundary) -> gpd.GeoDataFrame:
    p = osm.places.to_crs(crs)
    p = p[p["place"].isin(["city", "town", "village", "hamlet", "suburb", "neighbourhood",
                           "isolated_dwelling"])].copy()
    p["geometry"] = p.geometry.representative_point()
    p = p[p.within(boundary)]
    b = osm.buildings.to_crs(crs)
    pts = b.geometry.representative_point()
    xy = np.c_[pts.x, pts.y]
    rows = []
    # assign buildings to nearest named place within 1 km; cluster the rest
    if len(p):
        tree = STRtree(p.geometry.values)
        idx, dist = tree.query_nearest(pts.values, return_distance=True, max_distance=1000, all_matches=False)
        owner = np.full(len(b), -1)
        owner[idx[0]] = idx[1]
    else:
        owner = np.full(len(b), -1)
    counts = np.bincount(owner[owner >= 0], minlength=len(p)) if len(p) else []
    def sample(pts_xy, anchor):
        if len(pts_xy) == 0:
            return [anchor]
        k = np.linspace(0, len(pts_xy) - 1, min(SAMPLE, len(pts_xy))).astype(int)
        return [tuple(v) for v in pts_xy[k]]
    for i, r in enumerate(p.itertuples()):
        rows.append({"name": r.name, "name_ne": r.name_ne, "kind": r.place,
                     "buildings": int(counts[i]) if len(p) else 0, "geometry": r.geometry,
                     "sample": sample(xy[owner == i], (r.geometry.x, r.geometry.y))})
    rest = owner < 0
    if rest.sum() >= MIN_CLUSTER:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        from scipy.spatial import cKDTree
        sub = xy[rest]
        if len(sub) > 1:
            # single-linkage clusters (buildings chained within CLUSTER_EPS_M), linear memory
            pairs = cKDTree(sub).query_pairs(CLUSTER_EPS_M, output_type="ndarray")
            adj = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(sub), len(sub)))
            _, lab = connected_components(adj, directed=False)
            for c in np.unique(lab):
                m = lab == c
                if m.sum() >= MIN_CLUSTER:
                    cx, cy = sub[m].mean(0)
                    rows.append({"name": None, "name_ne": None, "kind": "building cluster",
                                 "buildings": int(m.sum()), "geometry": Point(cx, cy), "sample": sample(sub[m], (cx, cy))})
    s = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    s["people_est"] = (s["buildings"] * NEPAL_HH_SIZE).round().astype(int)
    return s


def _component_reach(G, sources):
    """Node -> True if connected to any source node."""
    reach = set()
    for comp in nx.connected_components(G):
        if comp & sources:
            reach |= comp
    return reach


def analyse(osm, damage: dict, impact: gpd.GeoDataFrame, grid_crs, boundary) -> dict:
    roads = osm.roads.to_crs(grid_crs)
    broken_bridges = damage["bridges"]
    broken_bridges = broken_bridges[broken_bridges["status"] == "likely damaged"]
    blockers = list(impact.geometry) + list(broken_bridges.geometry.buffer(5))
    S = settlements(osm, grid_crs, boundary)
    health = damage["health"].copy()
    health["geometry"] = health.geometry.representative_point()
    towns = S[S["kind"].isin(MAIN_PLACES)]

    edge_zone = boundary.exterior.buffer(EXIT_MARGIN_M)
    out = {"settlements": S}
    for mode, classes in (("vehicle", VEHICLE), ("foot", FOOT)):
        G, segs = build_graph(roads, classes)
        if G.number_of_nodes() == 0:
            S[f"{mode}_status"] = "no mapped road"
            continue
        nodes = list(G.nodes)
        node_xy = np.array(nodes)
        node_tree = STRtree([Point(n) for n in nodes])

        def snap(geoms, max_d=SNAP_M):
            idx, d = node_tree.query_nearest(list(geoms), return_distance=True, max_distance=max_d,
                                             all_matches=False)
            res = [None] * len(geoms)
            for i, j in zip(idx[0], idx[1]):
                res[i] = nodes[j]
            return res

        import shapely
        exits = {nodes[i] for i in np.nonzero(shapely.contains_xy(edge_zone, node_xy[:, 0], node_xy[:, 1]))[0]}
        dest = {"town": set(n for n in snap(towns.geometry) if n),
                "health": set(n for n in snap(health.geometry) if n),
                "exit": exits}
        # cut edges
        H = G.copy()
        if blockers:
            btree = STRtree(blockers)
            hit = btree.query(segs.geometry.values, predicate="intersects")
            cut_idx = np.unique(hit[0])
            H.remove_edges_from([(segs.u.iloc[i], segs.v.iloc[i]) for i in cut_idx])
            out[f"{mode}_segments_cut"] = segs.iloc[cut_idx]
        before = {k: _component_reach(G, v) for k, v in dest.items()}
        after = {k: _component_reach(H, v) for k, v in dest.items()}
        anyd = set().union(*dest.values())
        before_any, after_any = _component_reach(G, anyd), _component_reach(H, anyd)

        # road distance to nearest health facility, before/after (multi-source Dijkstra)
        def dist_to(Gx, src):
            src = [s for s in src if s in Gx]
            return nx.multi_source_dijkstra_path_length(Gx, src, weight="length") if src else {}
        dh_b, dh_a = dist_to(G, dest["health"]), dist_to(H, dest["health"])

        flat = [(i, Point(xy_)) for i, smp in enumerate(S["sample"]) for xy_ in smp]
        snapped = snap([g for _, g in flat])
        per = {}
        for (i, _), n in zip(flat, snapped):
            if n is not None:
                per.setdefault(i, []).append(n)
        status, km_b, km_a, lost, stranded = [], [], [], [], []
        for i in range(len(S)):
            ns = per.get(i, [])
            if not ns:
                status.append("no mapped road"); km_b.append(None); km_a.append(None); lost.append(""); stranded.append(0.0)
                continue
            reach_b = [n for n in ns if n in before_any]
            if not reach_b:
                status.append("isolated before event"); km_b.append(None); km_a.append(None); lost.append(""); stranded.append(0.0)
                continue
            still = [n for n in reach_b if n in after_any]
            frac = len(still) / len(reach_b)
            l = [k for k in dest if any(n in before[k] for n in reach_b) and not any(n in after[k] for n in reach_b)]
            if frac == 0:
                st = "cut off"
            elif l or frac < 0.5:
                st = "partly cut"     # still reaches something, lost something
            else:
                st = "connected"
            status.append(st)
            lost.append(", ".join(l))
            stranded.append(round(1 - frac, 2))
            db = [dh_b[n] for n in reach_b if n in dh_b]
            da = [dh_a[n] for n in still if n in dh_a]
            km_b.append(round(float(np.median(db)) / 1000, 1) if db else None)
            km_a.append(round(float(np.median(da)) / 1000, 1) if da else None)
        S[f"{mode}_stranded_share"] = stranded
        S[f"{mode}_status"] = status
        S[f"{mode}_lost"] = lost
        S[f"{mode}_health_km_before"] = km_b
        S[f"{mode}_health_km_after"] = km_a

    S["is_named"] = S["name"].notna()
    S = S.drop(columns=["sample"])
    out["settlements"] = S
    v = S.get("vehicle_status", pd.Series(dtype=str))
    f = S.get("foot_status", pd.Series(dtype=str))
    out["summary"] = {
        "settlements_total": int(len(S)),
        "settlements_cut_off_vehicle": int((v == "cut off").sum()),
        "settlements_partly_cut_vehicle": int((v == "partly cut").sum()),
        "settlements_cut_off_foot": int((f == "cut off").sum()),
        "people_est_cut_off_vehicle": int(S.loc[v == "cut off", "people_est"].sum()),
        "people_est_stranded_vehicle": int((S["people_est"] * S.get("vehicle_stranded_share", 0)).sum()),
        "people_est_cut_off_foot": int(S.loc[f == "cut off", "people_est"].sum()),
        "people_estimate_method": f"buildings x {NEPAL_HH_SIZE} persons/household (Nepal census 2021 average)",
    }
    return out
