"""Satellite data providers. Planetary Computer first, Meru as fallback."""
import logging

from .base import Scene, ScenePair, select_pairs  # noqa: F401
from .planetary import PlanetaryProvider

log = logging.getLogger(__name__)


def providers():
    out = [PlanetaryProvider()]
    try:
        from .meru import MeruProvider
        out.append(MeruProvider())
    except Exception as e:  # missing key etc. -- Meru is optional
        log.info("Meru provider disabled: %s", e)
    return out


def find_sar_pairs(bbox, event_date):
    """Try each provider in order; return (provider, pairs) from the first that yields pairs."""
    errors = []
    for p in providers():
        try:
            scenes = p.search_around("sentinel-1-rtc", bbox, event_date)
            pairs = select_pairs(scenes, event_date)
            if pairs:
                return p, pairs
            errors.append(f"{p.name}: no same-track pre/post pair")
        except Exception as e:
            errors.append(f"{p.name}: {e}")
            log.warning("provider %s failed: %s", p.name, e)
    raise RuntimeError("No Sentinel-1 pair found. " + "; ".join(errors))
