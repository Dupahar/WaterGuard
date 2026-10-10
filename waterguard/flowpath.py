"""Bonus: from any point upstream, trace the flood path down the valley on the Copernicus DEM
(D8 steepest-descent flow directions) and list the settlements along it, in order.

A glacier-outburst surge follows the river channel but spills over the valley floor, so a settlement
counts as "on the path" if it is within REACH_M of the traced channel AND its lowest part (lowest
HAND within LOW_PART_M of the settlement point) is less than HAND_MAX_M above the nearest river. Arrival times are NOT predicted from physics;
we show distance downstream and, separately labelled, a time at an assumed surge speed.
"""
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import LineString, Point

# WhiteboxTools D8 pointer encoding (esri_pntr=False): value -> (drow, dcol)
D8 = {1: (-1, 1), 2: (0, 1), 4: (1, 1), 8: (1, 0), 16: (1, -1), 32: (0, -1), 64: (-1, -1), 128: (-1, 0)}
REACH_M = 400
HAND_MAX_M = 80          # same valley-floor limit as the impact detector
LOW_PART_M = 150
ASSUMED_SPEED_MS = 4.0   # order of magnitude for Himalayan GLOF surges; an assumption, not a forecast
SNAP_TO_STREAM_PX = 10   # snap the clicked point to the nearest stream cell within 300 m


def trace(workdir, lon: float, lat: float, max_km: float = 200.0):
    """Returns (LineString in the DEM grid CRS, exited_area: bool)."""
    from .grid import Grid
    wd = Path(workdir)
    with rasterio.open(wd / "d8.tif") as src:
        d8 = src.read(1)
        g30 = Grid(src.crs, src.transform, src.width, src.height, None)
    with rasterio.open(wd / "streams.tif") as src:
        streams = src.read(1) > 0
    r, c = g30.lonlat_to_rowcol(lon, lat)
    H, W = d8.shape
    if not (0 <= r < H and 0 <= c < W):
        raise ValueError("Point is outside the analysed area")
    # snap to nearest stream cell
    k = SNAP_TO_STREAM_PX
    win = streams[max(0, r - k):r + k + 1, max(0, c - k):c + k + 1]
    if win.any():
        rr, cc = np.nonzero(win)
        i = np.argmin((rr + max(0, r - k) - r) ** 2 + (cc + max(0, c - k) - c) ** 2)
        r, c = rr[i] + max(0, r - k), cc[i] + max(0, c - k)
    rows, cols, seen = [r], [c], {(r, c)}
    step_m = g30.res
    for _ in range(int(max_km * 1000 / step_m)):
        v = int(d8[r, c])
        if v not in D8:
            break
        dr, dc = D8[v]
        r, c = r + dr, c + dc
        if not (0 <= r < H and 0 <= c < W) or (r, c) in seen:
            break
        seen.add((r, c))
        rows.append(r)
        cols.append(c)
    xs, ys = g30.transform * (np.array(cols) + 0.5, np.array(rows) + 0.5)
    line = LineString(np.c_[xs, ys]) if len(xs) > 1 else None
    exited = not (0 < rows[-1] < H - 1 and 0 < cols[-1] < W - 1)
    return line, exited


def along(line: LineString, settlements: gpd.GeoDataFrame, hand: np.ndarray, grid) -> gpd.GeoDataFrame:
    if line is None or settlements.empty:
        return settlements.iloc[:0]
    s = settlements[settlements.distance(line) <= REACH_M].copy()
    if s.empty:
        return s
    cols, rows = ~grid.transform * (s.geometry.x.values, s.geometry.y.values)
    k = int(LOW_PART_M / grid.res)
    lows = []
    for r, c in zip(rows.astype(int), cols.astype(int)):
        win = hand[max(0, r - k):r + k + 1, max(0, c - k):c + k + 1]
        lows.append(float(np.nanmin(win)) if win.size and np.isfinite(win).any() else np.nan)
    s["hand_m"] = np.round(lows, 1)
    s = s[s["hand_m"] <= HAND_MAX_M].copy()
    s["km_downstream"] = [round(line.project(Point(p)) / 1000, 1) for p in zip(s.geometry.x, s.geometry.y)]
    s["minutes_at_assumed_speed"] = (s["km_downstream"] * 1000 / ASSUMED_SPEED_MS / 60).round().astype(int)
    return s.sort_values("km_downstream")
