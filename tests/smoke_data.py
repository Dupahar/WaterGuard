"""Live smoke test of the data layer on the Trishuli case study (needs network + keys)."""
import time

import numpy as np

from waterguard.grid import Grid
from waterguard.osm import load_pre_event_osm
from waterguard.providers import find_sar_pairs
from waterguard.providers.meru import MeruProvider

BBOX = (85.15, 27.92, 85.25, 28.02)  # Betrawati confluence
EVENT = "2026-08-25T22:00:00Z"       # EMSR927 event time

grid = Grid.from_bbox(BBOX)
print("grid", grid.crs, grid.shape)

prov, pairs = find_sar_pairs(BBOX, EVENT)
for p in pairs:
    print("pair", p.describe())
best = pairs[0]

t = time.time()
pc = {k: prov.read(s, "vv", grid) for k, s in (("pre", best.pre), ("post", best.post))}
print(f"PC read {time.time() - t:.1f}s", {k: (np.nanmedian(v), np.isnan(v).mean()) for k, v in pc.items()})

# Meru must agree with Planetary Computer on the same scene (sanity check of the fallback).
meru = MeruProvider()
ms = [s for s in meru.search_around("sentinel-1-rtc", BBOX, EVENT)
      if abs((s.datetime - best.post.datetime).total_seconds()) < 120]
if ms:
    mv = meru.read(ms[0], "vv", grid)
    ok = np.isfinite(mv) & np.isfinite(pc["post"])
    d = 10 * np.log10(mv[ok]) - 10 * np.log10(pc["post"][ok])
    print(f"Meru vs PC post VV: median diff {np.median(d):.2f} dB, corr "
          f"{np.corrcoef(mv[ok], pc['post'][ok])[0, 1]:.3f}")
print("meru usage", meru.usage())

osm = load_pre_event_osm(BBOX, EVENT)
print("osm audit", osm.audit)
print({k: len(getattr(osm, k)) for k in ("buildings", "roads", "bridges", "health", "places")})
