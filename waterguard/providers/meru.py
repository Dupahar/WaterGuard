"""Meru Labs EO API (app.merulabs.space). Secondary provider: quick previews and a fallback
when Planetary Computer is unavailable.

Quirks (verified 2026-10-06): one GeoTIFF per request is capped at ~1024 px, so areas are
fetched as 0.1 degree tiles (~10 m) and mosaicked; recipes expire within a day; no orbit
metadata, so same-track pairing uses acquisition time-of-day; free tier = 1000 calls/month.
"""
import hashlib
import math
from datetime import timedelta

import numpy as np
import requests
from rasterio.enums import Resampling

from ..config import CACHE_DIR, MERU_API_KEY, MERU_BASE_URL
from .base import Scene, as_utc

TILE_DEG = 0.1

# our collection names -> (meru source, {band: meru product})
COLLECTIONS = {
    "sentinel-1-rtc": ("sentinel-1-rtc", {"vv": "backscatter", "vh": "backscatter_vh"}),
    "cop-dem-glo-30": ("dem", {"elevation": "elevation"}),
}

# Meru returns dB; Planetary Computer RTC returns linear power. Normalise to linear.
DB_PRODUCTS = {"backscatter", "backscatter_vh"}


class MeruError(RuntimeError):
    pass


class MeruProvider:
    name = "meru"

    def __init__(self, api_key=MERU_API_KEY, base_url=MERU_BASE_URL):
        if not api_key:
            raise MeruError("MERU_API_KEY not set")
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {api_key}"

    def _recipe(self, source, product, bbox, time):
        r = self.s.post(f"{self.base}/v1/recipes", timeout=300,
                        json={"source": source, "product": product,
                              "aoi": [round(v, 5) for v in bbox], "time": time})
        if r.status_code != 200:
            raise MeruError(f"recipe {source}/{product}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    def usage(self) -> dict:
        return self.s.get(f"{self.base}/v1/usage", timeout=30).json()

    def search(self, collection, bbox, start, end) -> list[Scene]:
        source, products = COLLECTIONS[collection]
        product = next(iter(products.values()))
        time = f"{as_utc(start):%Y-%m-%d}/{as_utc(end):%Y-%m-%d}"
        rec = self._recipe(source, product, bbox, time)
        return [Scene(provider=self.name, collection=collection, scene_id=t["scene_id"],
                      datetime=as_utc(t["datetime"]), cloud_cover=t.get("cloud_cover"),
                      assets={"time": time, "index": i})
                for i, t in enumerate(rec.get("timeline", []))]

    def search_around(self, collection, bbox, event, days_before=24, days_after=14):
        event = as_utc(event)
        return self.search(collection, bbox, event - timedelta(days=days_before), event + timedelta(days=days_after))

    def _tile_tif(self, source, product, tile_bbox, time, scene_id):
        key = hashlib.sha1(f"{source}|{product}|{tile_bbox}|{scene_id}".encode()).hexdigest()[:16]
        path = CACHE_DIR / f"meru_{key}.tif"
        if path.exists():
            return path
        rec = self._recipe(source, product, tile_bbox, time)
        ids = [t["scene_id"] for t in rec.get("timeline", [])]
        if scene_id not in ids:
            raise MeruError(f"scene {scene_id} not covering tile {tile_bbox}")
        r = self.s.get(f"{self.base}/v1/recipes/{rec['id']}/download.tif",
                       params={"i": ids.index(scene_id)}, timeout=300)
        if r.status_code != 200:
            raise MeruError(f"download HTTP {r.status_code}")
        path.write_bytes(r.content)
        return path

    def read(self, scene: Scene, band: str, grid, resampling=Resampling.bilinear):
        source, products = COLLECTIONS[scene.collection]
        product = products[band]
        w, s, e, n = grid.bbox
        out = np.full(grid.shape, np.nan, dtype="float32")
        for i in range(math.ceil((e - w) / TILE_DEG - 1e-9)):
            for j in range(math.ceil((n - s) / TILE_DEG - 1e-9)):
                tb = (w + i * TILE_DEG, s + j * TILE_DEG,
                      min(e, w + (i + 1) * TILE_DEG), min(n, s + (j + 1) * TILE_DEG))
                arr = grid.read(str(self._tile_tif(source, product, tb, scene.assets["time"], scene.scene_id)),
                                resampling=resampling)
                fill = np.isnan(out) & np.isfinite(arr)
                out[fill] = arr[fill]
        if product in DB_PRODUCTS:
            out = np.power(10.0, out / 10.0, dtype="float32")
        return out
