"""A common analysis grid: every raster in a run is warped onto the same UTM pixel grid,
so pre/post images, DEM and masks line up pixel-for-pixel."""
from dataclasses import dataclass

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

from .config import PIXEL_SIZE_M


def utm_crs_for(lon: float, lat: float) -> CRS:
    zone = int((lon + 180) // 6) + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


@dataclass(frozen=True)
class Grid:
    crs: CRS
    transform: rasterio.Affine
    width: int
    height: int
    bbox: tuple  # lon/lat (w, s, e, n) the grid was built from

    @classmethod
    def from_bbox(cls, bbox, res=PIXEL_SIZE_M) -> "Grid":
        w, s, e, n = bbox
        crs = utm_crs_for((w + e) / 2, (s + n) / 2)
        tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        xs, ys = tr.transform([w, e, w, e], [s, s, n, n])
        x0, x1 = np.floor(min(xs) / res) * res, np.ceil(max(xs) / res) * res
        y0, y1 = np.floor(min(ys) / res) * res, np.ceil(max(ys) / res) * res
        return cls(crs, from_origin(x0, y1, res, res), int((x1 - x0) / res), int((y1 - y0) / res), tuple(bbox))

    def with_res(self, res: float) -> "Grid":
        """Same footprint at another resolution (e.g. 30 m for DEM hydrology)."""
        x0, y1 = self.transform.c, self.transform.f
        w = int(np.ceil(self.width * self.res / res))
        h = int(np.ceil(self.height * self.res / res))
        return Grid(self.crs, from_origin(x0, y1, res, res), w, h, self.bbox)

    def lonlat_to_rowcol(self, lon, lat):
        tr = Transformer.from_crs("EPSG:4326", self.crs, always_xy=True)
        x, y = tr.transform(lon, lat)
        c, r = ~self.transform * (x, y)
        return int(r), int(c)

    def rowcol_to_lonlat(self, rows, cols):
        tr = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True)
        xs, ys = self.transform * (np.asarray(cols) + 0.5, np.asarray(rows) + 0.5)
        return tr.transform(xs, ys)

    @property
    def shape(self):
        return (self.height, self.width)

    @property
    def res(self) -> float:
        return self.transform.a

    def profile(self, dtype="float32", count=1, nodata=np.nan) -> dict:
        return dict(driver="GTiff", crs=self.crs, transform=self.transform, width=self.width,
                    height=self.height, count=count, dtype=dtype, nodata=nodata,
                    compress="deflate", tiled=True)

    def read(self, src_path_or_url: str, band: int = 1, resampling=Resampling.bilinear) -> np.ndarray:
        """Warp one band of any raster (local path or signed COG URL) onto this grid."""
        with rasterio.open(src_path_or_url) as src:
            with WarpedVRT(src, crs=self.crs, transform=self.transform, width=self.width,
                           height=self.height, resampling=resampling, src_nodata=src.nodata,
                           nodata=np.nan, dtype="float32") as vrt:
                return vrt.read(band)

    def save(self, path, arr: np.ndarray, **kw):
        arr = np.asarray(arr)
        count = 1 if arr.ndim == 2 else arr.shape[0]
        prof = self.profile(dtype=str(arr.dtype), count=count,
                            nodata=kw.pop("nodata", np.nan if arr.dtype.kind == "f" else None))
        with rasterio.open(path, "w", **prof) as dst:
            dst.write(arr if arr.ndim == 3 else arr[None])
