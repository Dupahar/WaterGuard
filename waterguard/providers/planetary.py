"""Microsoft Planetary Computer: free, full-resolution COGs with orbit metadata. Primary provider."""
from datetime import timedelta

import planetary_computer as pc
import pystac_client

from .base import Scene, as_utc

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

# collection -> {our band name: STAC asset key}
COLLECTIONS = {
    "sentinel-1-rtc": {"vv": "vv", "vh": "vh"},
    "sentinel-2-l2a": {"blue": "B02", "green": "B03", "red": "B04", "nir": "B08", "swir1": "B11", "scl": "SCL"},
    "cop-dem-glo-30": {"elevation": "data"},
}


class PlanetaryProvider:
    name = "planetary-computer"

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = pystac_client.Client.open(STAC_URL)
        return self._client

    def search(self, collection: str, bbox, start, end, max_items=200) -> list[Scene]:
        """Cached on disk, so areas already analysed rerun with no network at all. A window that has not
        closed yet (plus two days for ingestion) is not cached: later images are still arriving."""
        import hashlib, json, dataclasses, os
        from datetime import datetime, timedelta, timezone
        from ..config import CACHE_DIR
        key = hashlib.sha1(f"{collection}|{[round(v, 5) for v in bbox]}|{start}|{end}".encode()).hexdigest()[:16]
        path = CACHE_DIR / f"stac_{key}.json"
        if path.exists():
            return [Scene(**{**d, "datetime": as_utc(d["datetime"])}) for d in json.loads(path.read_text())]
        scenes = self._search(collection, bbox, start, end, max_items)
        if end is not None and as_utc(end) + timedelta(days=2) > datetime.now(timezone.utc):
            return scenes
        tmp = path.with_suffix(".part")
        tmp.write_text(json.dumps([{**dataclasses.asdict(s), "datetime": s.datetime.isoformat()} for s in scenes]))
        os.replace(tmp, path)
        return scenes

    def _search(self, collection: str, bbox, start, end, max_items=200) -> list[Scene]:
        bands = COLLECTIONS[collection]
        items = self.client.search(collections=[collection], bbox=list(bbox),
                                   datetime=None if collection.startswith("cop-dem") else
                                   f"{as_utc(start):%Y-%m-%dT%H:%M:%SZ}/{as_utc(end):%Y-%m-%dT%H:%M:%SZ}",
                                   max_items=max_items).items()
        scenes = []
        for it in items:
            p = it.properties
            scenes.append(Scene(
                provider=self.name, collection=collection, scene_id=it.id,
                datetime=as_utc(it.datetime or p.get("start_datetime")),
                relative_orbit=p.get("sat:relative_orbit"), orbit_state=p.get("sat:orbit_state"),
                cloud_cover=p.get("eo:cloud_cover"),
                assets={b: it.assets[k].href for b, k in bands.items() if k in it.assets},
                props={k: p[k] for k in ("s2:processing_baseline",) if k in p},
            ))
        return scenes

    def search_around(self, collection, bbox, event, days_before=24, days_after=14):
        event = as_utc(event)
        return self.search(collection, bbox, event - timedelta(days=days_before), event + timedelta(days=days_after))

    def href(self, scene: Scene, band: str) -> str:
        """Signed URL (SAS tokens expire, so sign at read time, not at search time)."""
        return pc.sign(scene.assets[band])

    def read(self, scene: Scene, band: str, grid, resampling=None):
        from rasterio.enums import Resampling
        return grid.read(self.href(scene, band), resampling=resampling or Resampling.bilinear)
