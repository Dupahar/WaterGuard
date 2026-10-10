"""Parallel, disk-cached reads of scene bands onto an analysis grid."""
import hashlib
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from rasterio.enums import Resampling

from .config import CACHE_DIR, READ_WORKERS

BAND_CACHE = CACHE_DIR / "bands"
BAND_CACHE.mkdir(parents=True, exist_ok=True)


def _key(provider, scene, band, grid, resampling):
    raw = f"{provider.name}|{scene.scene_id}|{band}|{grid.crs.to_epsg()}|{tuple(grid.transform)[:6]}|{grid.shape}|{resampling}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def read(provider, scene, band, grid, resampling=Resampling.bilinear) -> np.ndarray:
    path = BAND_CACHE / f"{_key(provider, scene, band, grid, resampling)}.npy"
    if path.exists():
        return np.load(path)
    arr = provider.read(scene, band, grid, resampling).astype("float32")
    np.save(path, arr)
    return arr


def read_many(provider, jobs, grid) -> list[np.ndarray]:
    """jobs: list of (scene, band) or (scene, band, resampling). Order preserved."""
    def one(j):
        scene, band, *rs = j
        return read(provider, scene, band, grid, rs[0] if rs else Resampling.bilinear)
    with ThreadPoolExecutor(READ_WORKERS) as ex:
        return list(ex.map(one, jobs))


def prefetch(provider, jobs, grid) -> None:
    """Download + warp in parallel into the disk cache without holding results in memory."""
    def one(j):
        scene, band, *rs = j
        read(provider, scene, band, grid, rs[0] if rs else Resampling.bilinear)
    with ThreadPoolExecutor(READ_WORKERS) as ex:
        list(ex.map(one, jobs))
