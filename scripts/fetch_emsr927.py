"""Download the Copernicus EMS EMSR927 reference vectors into data/validation/emsr927/.

VALIDATION ONLY (project data rule): these files are read by waterguard/validate.py to check our
results and are never used as pipeline inputs. Credit: European Union, Copernicus Emergency
Management Service data.
    python scripts/fetch_emsr927.py
"""
import json
from pathlib import Path

import requests
from shapely import wkt

OUT = Path(__file__).resolve().parent.parent / "data" / "validation" / "emsr927"
API = "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR927"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    act = requests.get(API, timeout=60).json()
    (OUT / "activation.json").write_text(json.dumps(act), encoding="utf-8")
    d = act["results"][0]
    for a in d["aois"]:
        for p in a["products"]:
            for layer in p.get("layers", []):
                if layer.get("json"):
                    f = OUT / layer["json"].rsplit("/", 1)[1]
                    f.write_bytes(requests.get(layer["json"], timeout=120).content)
                    print(f.name)
    aois = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"aoi": a["number"], "name": a["name"]},
         "geometry": wkt.loads(a["extent"]).__geo_interface__} for a in d["aois"]]}
    (OUT / "aois.geojson").write_text(json.dumps(aois), encoding="utf-8")


if __name__ == "__main__":
    main()
