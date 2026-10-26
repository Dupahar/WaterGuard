"""Real Nemotron outputs for the film's Nemotron chapter -> public/data/nemotron/ (nemotron.json + the chip).

  planner      Nemotron 3 Ultra (Nebius Token Factory) settles one inspection cell; every decision and
               the model's own reason are kept (inspector.settle with the LLM planner)
  second look  Nemotron 3.5 Super VL's read of a cell's analyst chip, from the run's inspection
  copilot      answers from the Nemotron copilot evaluation (docs/copilot_eval_nemotron.json)
Needs NEBIUS_API_KEY. Run from the repo root:  .venv\\Scripts\\python -X utf8 video/scripts/export_nemotron.py
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv   # noqa: E402
load_dotenv(ROOT / ".env")
from waterguard import inspector, second_look, vision   # noqa: E402
from waterguard.config import CACHE_DIR, DATA_DIR   # noqa: E402

OUT = ROOT / "video/public/data/nemotron"
LOOK_RUN = "ea62d79b3a"          # Syapru Besi with open footprints + WorldPop, inspected with the second look
PLAN_RUN, PLAN_CELL = "58052edd5e", "r840c660"   # Bidur (held-out): the cell of the OpenCV chapter

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    # planner: Nemotron Ultra settles one cell, second look allowed
    ev = vision.load(DATA_DIR / "runs" / PLAN_RUN)
    cell = next(c for c in vision.cells(DATA_DIR / "runs" / PLAN_RUN, ev) if c["id"] == PLAN_CELL)
    P = inspector.LLMPlanner()
    chips = CACHE_DIR / "nemotron_film"
    chips.mkdir(parents=True, exist_ok=True)
    res = inspector.settle(ev, cell, P, chips=chips, look=second_look.read)
    if res["chip"]:
        shutil.copy(chips / res["chip"], OUT / "plan_chip.png")
    plan = {"model": P.model, "cell": PLAN_CELL, "area": "Bidur (held-out)", "verdict": res["verdict"],
            "trace": res["trace"], "stats": P.stats, "chip": "plan_chip.png" if res["chip"] else None}

    # second look: the strongest read on a cell that went to a person
    ins = json.loads((DATA_DIR / "runs" / LOOK_RUN / "inspection.json").read_text(encoding="utf-8"))
    looked = [c for c in ins["cells"] if c.get("second_look") and "error" not in c["second_look"]]
    c = max(looked, key=lambda x: (x["second_look"]["confidence"], x["impact_ha"]))
    shutil.copy(DATA_DIR / "runs" / LOOK_RUN / c["chip"], OUT / "chip.png")
    look = {"cell": c["id"], "area": "Syapru Besi", "impact_ha": c["impact_ha"], "verdict": c["verdict"],
            "lines": inspector.lines(c["measurements"]), "read": c["second_look"], "reason": c["reason"]}

    # copilot: one map answer and one web answer from the evaluation
    ce = json.loads((ROOT / "docs/copilot_eval_nemotron.json").read_text(encoding="utf-8"))
    pick = lambda pred: next(x for x in ce["items"] if pred(x))
    cop = {"summary": ce["summary"],
           "map": pick(lambda x: x["q"].startswith("What is the status of Syabru")),
           "web": pick(lambda x: x["sources"])}
    (OUT / "nemotron.json").write_text(json.dumps({"planner": plan, "look": look, "copilot": cop}, indent=1,
                                                  ensure_ascii=False, default=str), encoding="utf-8")
    print("planner", P.model, res["verdict"], [t.get("action") or t.get("tool") for t in res["trace"]], P.stats)
    print("look", c["id"], c["second_look"]["cause"], c["second_look"]["confidence"])
    print("copilot", cop["summary"])
