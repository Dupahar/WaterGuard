"""Terrain layers from Copernicus DEM GLO-30 (the only elevation input).

- HAND (height above nearest drainage): how far above the river a pixel sits. A glacier-outburst
  surge is metres to tens of metres deep, so it can only reach low-HAND valley floor.
- Slope / aspect: used to predict where Sentinel-1 cannot see the ground (radar layover and
  shadow on steep Himalayan slopes), so we never report change there.
- D8 flow directions and stream network: used to trace a flood path from any upstream point.
Hydrology runs on a 30 m grid (native DEM resolution) with WhiteboxTools, then is resampled
onto the 10 m analysis grid.
"""
import hashlib
from pathlib import Path

import numpy as np
from rasterio.enums import Resampling

from .config import CACHE_DIR
from .grid import Grid

STREAM_THRESHOLD_KM2 = 2.0   # upstream area that makes a "river" (keeps side streams, drops gullies)


def _dem30(provider, g30: Grid) -> np.ndarray:
    tiles = provider.search("cop-dem-glo-30", g30.bbox, None, None)
    if not tiles:
        raise RuntimeError("No Copernicus DEM tiles for this area")
    dem = np.full(g30.shape, np.nan, dtype="float32")
    for t in tiles:
        a = provider.read(t, "elevation", g30)
        fill = np.isnan(dem) & np.isfinite(a)
        dem[fill] = a[fill]
    return dem


def build(grid: Grid, provider, pad_deg: float = 0.03) -> dict:
    """Terrain on `grid`. Hydrology is computed on a padded box so rivers entering the area
    are traced correctly. Cached per bbox."""
    import whitebox

    w, s, e, n = grid.bbox
    big = Grid.from_bbox((w - pad_deg, s - pad_deg, e + pad_deg, n + pad_deg)).with_res(30.0)
    key = hashlib.sha1(f"{big.bbox}|{STREAM_THRESHOLD_KM2}".encode()).hexdigest()[:12]
    wd = (CACHE_DIR / f"terrain_{key}").resolve()
    wd.mkdir(parents=True, exist_ok=True)
    if not (wd / "dem.tif").exists():
        big.save(wd / "dem.tif", np.nan_to_num(_dem30(provider, big), nan=-9999).astype("float32"),
                 nodata=-9999)

    wbt = whitebox.WhiteboxTools()
    wbt.set_verbose_mode(False)
    wbt.set_working_dir(str(wd))
    thr_cells = int(STREAM_THRESHOLD_KM2 * 1e6 / 900)
    steps = [
        ("breached.tif", lambda o: wbt.breach_depressions_least_cost("dem.tif", o, dist=100, fill=True)),
        ("d8.tif", lambda o: wbt.d8_pointer("breached.tif", o, esri_pntr=False)),
        ("acc.tif", lambda o: wbt.d8_flow_accumulation("breached.tif", o, out_type="cells")),
        ("streams.tif", lambda o: wbt.extract_streams("acc.tif", o, threshold=thr_cells)),
        ("hand.tif", lambda o: wbt.elevation_above_stream("breached.tif", "streams.tif", o)),
        ("slope.tif", lambda o: wbt.slope("dem.tif", o, units="degrees")),
        ("aspect.tif", lambda o: wbt.aspect("dem.tif", o)),
    ]
    for out, fn in steps:
        if not (wd / out).exists():
            fn(out)
            if not (wd / out).exists():
                raise RuntimeError(f"WhiteboxTools step failed: {out}")

    def up(name, resampling=Resampling.bilinear):
        return grid.read(str(wd / name), resampling=resampling)

    return {
        "dem": up("dem.tif"),
        "hand": np.clip(up("hand.tif"), 0, None),
        "slope": up("slope.tif"),
        "aspect": up("aspect.tif", Resampling.nearest),
        "streams": up("streams.tif", Resampling.nearest) > 0,
        "workdir": wd,
        "grid30": big,
    }


def radar_blind(slope_deg, aspect_deg, orbit_state: str, incidence_deg: float = 39.0) -> np.ndarray:
    """Pixels where Sentinel-1 cannot see the ground: layover (slope facing the radar steeper than
    the incidence angle) or shadow (slope facing away steeper than 90 deg - incidence).
    Sentinel-1 is right-looking; on the ascending pass it looks roughly east (~ 80 deg azimuth),
    on the descending pass roughly west (~ 280 deg). A 5 deg safety margin is applied."""
    look_az = 80.0 if str(orbit_state).lower().startswith("asc") else 280.0
    s = np.nan_to_num(slope_deg, nan=0.0)
    # slope component along the radar's line of sight (+ = facing the radar)
    facing = np.cos(np.radians(np.nan_to_num(aspect_deg, nan=0.0) - (look_az + 180.0)))
    s_los = np.degrees(np.arctan(np.tan(np.radians(s)) * facing))
    layover = s_los > incidence_deg - 5
    shadow = -s_los > (90 - incidence_deg) - 5
    return layover | shadow
