"""Real numbers for the product film -> video/public/data/product.json (proof, inspection, ledger, payouts)."""
import json
from pathlib import Path

R = Path(__file__).resolve().parents[2]
RUN = R / "data/runs/e34c30aded"
proof = json.loads((RUN / "proof.json").read_text(encoding="utf-8"))
ins = json.loads((RUN / "inspection.json").read_text(encoding="utf-8"))
facts = json.loads((RUN / "facts.json").read_text(encoding="utf-8"))
val = json.loads((R / "docs/validation_emsr927.json").read_text(encoding="utf-8"))
vi = json.loads((R / "docs/validation_inspector.json").read_text(encoding="utf-8"))
out = {
    "files": [f["name"] for f in proof["files"]],
    "report_root": proof["report_root"], "claims_root": proof["claims_root"], "key": proof["key"],
    "settlements": [{"name": s["name"], "status": s["status"], "people": s["people_stranded"]} for s in proof["settlements"]],
    "facts": {"impact_ha": facts["impact"]["impact_ha"], "cut": facts["access"]["settlements_cut_off_vehicle"],
              "stranded": facts["access"]["people_est_stranded_vehicle"], "buildings": facts["damage"]["buildings_likely_affected"],
              "bridges": facts["damage"]["bridges_likely_damaged"]},
    "inspection": ins["summary"] | {"later_looks": ins["later_looks"], "cells": ins["cells_inspected"]},
    "inspector_eval": vi,
    "validation": [{"aoi": v["aoi"], "name": v["name"], "split": v["split"], "f1": v["area"]["f1"]} for v in val if "aoi" in v],
    "ledger": {
        "registry": "0x4Ed7bD30798a9878Daa67FBE5e07B6f0ab9F8d18", "relief": "0x6aaC76b526cA2a61Da8b5c86a75f8917cA1dedce",
        "published_v1": "0x245455313f29e2164232f0cbad4d33b33b2f393a4818a50000c4ba1aa9cc3130",
        "disputed": "0x4f0aa03980576c10eec9827e1cef8f21d144d2c8ca978b831907975cc505eb0b",
        "upheld": "0x0e0ec62271f3a2baef2a349df24aee887c8b62d702e0ac9b5e3d564c6960a085",
        "published_v2": "0x598ba126897b7adb20263f1bb8a81685025fe9ea1cc663d2b3d5a8bfb8b57ff3",
        "confirmed_laptop": "0xc97161fe3531a72ba9480db571b28cb557e8b1f69eeacba19704cdae7492c1a3",
        "confirmed_aws": "0xda957c764b158c4c2628f460a527e4c79a8c7cb192201ab3903212e18d0d8342",
        "fund": "0x5342d84acf7fde19f72a3343c0a8cd6cacf56cf500f5673328ba0b2a142a01a4",
        "dispute": {"village": "Syabru Bensi", "ours": 1200, "verifier": 988},
        "payouts": [
            {"name": "Syabru Bensi", "people": 1130, "eth": 0.005, "capped": True, "tx": "0xa9da77b80e944f0c4839f0f1883fc07ccea411baea81e03c060a814f6a7bb5b8"},
            {"name": "Hamlet · 36 buildings", "people": 157, "eth": 0.00157, "capped": False, "tx": "0xaee92ccad7f1f1a9b9b922198fc94811aeba8df1c7cbb62e24c2cb993bd279f3"},
            {"name": "Hamlet · 33 buildings", "people": 144, "eth": 0.00144, "capped": False, "tx": "0x4c9c6ea8bb2cfb03f8855d3345339df346ee4ec5da6bd2b08f02a6530e1be6be"},
        ],
        "fund_terms": {"per_person": 0.00001, "cap": 0.005, "deposit": 0.02},
    },
    "ui": json.loads((R / "video/public/ui/ui.json").read_text(encoding="utf-8")),
}
(R / "video/public/data/product.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print("files", len(out["files"]), "settlements", len(out["settlements"]), "states", len(out["ui"]["states"]))
