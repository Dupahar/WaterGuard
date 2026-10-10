"""Runtime configuration loaded from environment / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("WATERGUARD_DATA", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"

MERU_BASE_URL = os.getenv("MERU_BASE_URL", "https://app.merulabs.space")
MERU_API_KEY = os.getenv("MERU_API_KEY")
OHSOME_BASE_URL = os.getenv("OHSOME_BASE_URL", "https://api.heigit.org/ohsome-api/v2-rc")
OHSOME_API_KEY = os.getenv("OHSOME_API_KEY")

# Working resolution for all rasters (metres). Sentinel-1 RTC and Sentinel-2 are native 10 m.
PIXEL_SIZE_M = 10.0

for d in (DATA_DIR, CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Remote COG reads: avoid directory listings, merge range requests, reuse HTTP/2 connections.
for k, v in {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
             "GDAL_HTTP_MULTIPLEX": "YES", "GDAL_HTTP_VERSION": "2", "VSI_CACHE": "TRUE",
             "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff", "GDAL_HTTP_MAX_RETRY": "4",
             "GDAL_HTTP_RETRY_DELAY": "1"}.items():
    os.environ.setdefault(k, v)

READ_WORKERS = int(os.getenv("WATERGUARD_READ_WORKERS", "24"))
