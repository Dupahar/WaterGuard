"""Inspector agent: looks again at every part of the impact map that matters, before a report goes out.

    python -m waterguard.inspector <run_id> [--max-cells 40] [--planner rules|llm]

A loop of perception -> decision -> action per inspection cell (600 m), most exposed first:

  perceive   vision.measure(): co-registration, colour / structure / texture / vegetation / radar
             contrast against nearby unflagged ground, edge artefacts, patch shape (OpenCV 5)
  decide     how many independent lines of evidence agree, and whether the sky was clear enough
  act        confirm the cell                         (strong, multi-sensor agreement)
             look_later: fetch a fresh cloud-free Sentinel-2 composite of just this cell weeks later
                         and measure again (debris persists; wet soil, turbid water, green-up fade)
             ask_human:  send the chip and the measurements to an analyst queue
             flag:       likely false alarm (change reverted); a human still makes the call

Nothing is removed from the map by the agent. Only an analyst's decision in the review queue does
(apply_review(), which re-runs the pipeline with the rejected cells vetoed), and the report is
anchored on the public ledger only once the queue is empty. The planner is a fixed rule set by
default; with --planner llm a language model chooses the next tool from the same measurements,
under the same guard rails (it cannot confirm without enough evidence and cannot remove anything).

Thresholds were set on EMSR927 AOI01 + AOI02 and the Tadi Khola control; AOI03 + AOI05 held out
(see validate.inspection_check()).
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import vision
from .pipeline import RUNS_DIR

# evidence lines: a flagged cell vs unflagged valley ground nearby (set on AOI01 + AOI02 + Tadi Khola control)
LINE_DELTA_E = 12.0         # CIELAB colour change
LINE_NDVI = 0.10            # vegetation loss
LINE_SSIM = 0.15            # structural change
LINE_SAR = 0.80             # radar |z|
CONFIRM_LINES = 4           # all four agree -> confirm on first look
LATER_LINES = 3             # three agree -> a later look can confirm, if the colour change persists
CLOUDY = 0.5                # less than half the flagged ground seen clear -> look again
PERSIST_DELTA_E = 8.0       # colour contrast still there weeks later
REVERTED_DELTA_E = 4.0      # ... or gone, and the vegetation is back
REVERTED_NDVI = 0.03
MAX_FETCHES = 40


def lines(m: dict) -> dict:
    v = lambda k: m.get(k) if m.get(k) is not None else -9
    return {"colour": v("delta_e_contrast") >= LINE_DELTA_E, "vegetation": v("ndvi_drop_contrast") >= LINE_NDVI,
            "structure": v("ssim_dissimilarity_contrast") >= LINE_SSIM, "radar": v("sar_z_contrast") >= LINE_SAR}


def persistence(later: dict) -> str:
    de, nd = later.get("delta_e_contrast"), later.get("ndvi_drop_contrast")
    if de is None or nd is None or (later.get("clear_share") or 0) < CLOUDY:
        return "unseen"
    if de >= PERSIST_DELTA_E:
        return "persists"
    if de < REVERTED_DELTA_E and nd < REVERTED_NDVI:
        return "reverted"
    return "unclear"


class RulePlanner:
    name = "rules"

    def decide(self, cell, m, later, can_fetch):
        L = lines(m)
        n = sum(L.values())
        cloudy = (m.get("clear_share") or 0) < CLOUDY
        if later is None:
            if n >= CONFIRM_LINES:
                return "confirm", f"all {n} evidence lines agree ({', '.join(k for k, x in L.items() if x)})"
            # only spend a download where a second look can change the outcome
            if can_fetch and (n >= LATER_LINES or cloudy):
                why = "clouds hid most of it" if cloudy else f"{n} of 4 evidence lines agree ({', '.join(k for k, x in L.items() if not x)} missing)"
                return "look_later", f"{why}: fetch a later cloud-free image to see whether the change persists"
            agree = f"{n} of 4 evidence lines agree ({', '.join(k for k, x in L.items() if x) or 'none'})"
            if n >= LATER_LINES or cloudy:
                return "ask_human", f"{agree}; a later look could settle it but the download budget is used up"
            return "ask_human", f"only {agree}: too weak for a later image to confirm"
        p = persistence(later)
        if p == "persists" and (n >= LATER_LINES or (cloudy and n >= 2)):
            return "confirm", f"{n} of 4 evidence lines agree and the colour change persists weeks later"
        if p == "reverted":
            return "flag", "the ground looks like it did before the flood again: probably seasonal, not flood damage"
        return "ask_human", {"persists": f"the change persists but only {n} of 4 evidence lines agree",
                             "unseen": "still no clear later view", "unclear": "later image is ambiguous"}[p]


class LLMPlanner:
    """A language model picks the next action from the measurements. Guard rails are enforced here,
    not trusted to the model."""
    name = "llm"
    TOOLS = [{"name": a, "description": d, "parameters": {"type": "object", "properties": {
        "reason": {"type": "string", "description": "one sentence, citing the measurements"}}, "required": ["reason"]}}
        for a, d in (("confirm", "The flagged ground is flood/debris damage."),
                     ("look_later", "Fetch a fresh cloud-free image of this cell from weeks later and measure again."),
                     ("ask_human", "Send to an analyst: evidence is mixed or insufficient."),
                     ("flag", "Likely false alarm (e.g. the change reverted). An analyst still decides."))]
    SYSTEM = ("You inspect one 600 m cell of a satellite flood-impact map. You get OpenCV measurements of the flagged "
              "ground compared with nearby unflagged valley ground ('contrast' = flagged minus reference), the four "
              "evidence lines (colour, vegetation, structure, radar), and, if fetched, the same measurements from a "
              "later image. Debris and scour persist for months; wet soil, turbid water and seasonal green-up do not. "
              "Call exactly one tool.")

    def __init__(self):
        from .copilot import _backend, _call_bedrock, _call_openai
        b = _backend()
        if b is None:
            raise RuntimeError("no LLM backend configured (see copilot.py)")
        self.call = _call_openai if b == "openai" else _call_bedrock
        self.name = f"llm ({b})"
        self.fallback = RulePlanner()

    def decide(self, cell, m, later, can_fetch):
        L = lines(m)
        payload = {"cell": {k: cell[k] for k in ("impact_ha", "buildings_hit", "road_segments_cut", "people_nearby_est")},
                   "measurements": m, "evidence_lines": L, "later_look": later,
                   "later_persistence": persistence(later) if later else None, "can_fetch_more_imagery": can_fetch}
        msgs = [{"role": "system", "content": self.SYSTEM},
                {"role": "user", "content": json.dumps(payload, default=str)}]
        try:
            _, calls, _ = self.call(msgs, self.TOOLS)
            action, reason = calls[0][1], calls[0][2].get("reason", "")
        except Exception as e:
            a, r = self.fallback.decide(cell, m, later, can_fetch)
            return a, f"{r} (rules; model unavailable: {str(e)[:60]})"
        n = sum(L.values())
        cloudy = (m.get("clear_share") or 0) < CLOUDY
        if action == "confirm" and not (n >= CONFIRM_LINES or (later and persistence(later) == "persists"
                                                                 and (n >= LATER_LINES or (cloudy and n >= 2)))):
            return "ask_human", f"model wanted to confirm ({reason}) but only {n} of 4 lines agree: needs an analyst"
        if action == "look_later" and (not can_fetch or later is not None):
            return "ask_human", f"model asked for more imagery ({reason}); none available: needs an analyst"
        if action not in {"confirm", "look_later", "ask_human", "flag"}:
            return "ask_human", "model gave no valid action"
        return action, reason


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def inspect(run_id: str, max_cells: int = 40, planner: str = "rules", max_fetches: int = MAX_FETCHES,
            provider=None, progress=lambda msg, pct: None) -> dict:
    d = RUNS_DIR / run_id
    facts = json.loads((d / "facts.json").read_text(encoding="utf-8"))
    ev = vision.load(d)
    todo = vision.cells(d, ev)
    P = LLMPlanner() if planner == "llm" else RulePlanner()
    chips = d / "inspect"
    chips.mkdir(exist_ok=True)
    if provider is None:
        from .providers import providers
        provider = providers()[0]
    fetches, out, t0 = 0, [], time.time()
    for i, cell in enumerate(todo[:max_cells]):
        progress(f"inspecting cell {i + 1}/{min(len(todo), max_cells)}", int(100 * i / max(min(len(todo), max_cells), 1)))
        trace = []
        m = vision.measure(ev, cell, chips / f"{cell['id']}.png")
        trace.append({"step": "perceive", "tool": "vision.measure", "lines": lines(m)})
        later = None
        action, why = P.decide(cell, m, None, fetches < max_fetches)
        trace.append({"step": "decide", "action": action, "reason": why})
        if action == "look_later":
            fetches += 1
            ov, used = vision.later_look(ev, cell, facts["event_time_utc"], provider)
            later = vision.measure(ev, cell, chips / f"{cell['id']}_later.png", rgb_override=ov) if ov else {}
            later["scenes"] = [u["date"] for u in used]
            trace.append({"step": "act", "tool": "vision.later_look", "scenes": later["scenes"],
                          "persistence": persistence(later)})
            action, why = P.decide(cell, m, later, False)
            trace.append({"step": "decide", "action": action, "reason": why})
        verdict = {"confirm": "confirmed", "ask_human": "needs_review", "flag": "likely_false_alarm"}[action]
        out.append({**cell, "verdict": verdict, "reason": why, "measurements": m, "later": later, "trace": trace,
                    "chip": f"inspect/{cell['id']}.png",
                    "chip_later": f"inspect/{cell['id']}_later.png" if later else None, "review": None})
    old = load(run_id)
    if old:   # keep analyst decisions already made on the same cells
        prev = {c["id"]: c.get("review") for c in old["cells"]}
        for c in out:
            c["review"] = prev.get(c["id"])
    res = {"run_id": run_id, "planner": P.name, "inspected_utc": _now(), "runtime_s": round(time.time() - t0, 1),
           "cells_total": len(todo), "cells_inspected": len(out), "later_looks": fetches, "cells": out}
    res["summary"] = summary(res)
    save(run_id, res)
    progress("done", 100)
    return res


def summary(res: dict) -> dict:
    c = res["cells"]
    count = lambda v: sum(1 for x in c if x["verdict"] == v)
    ha = lambda v: round(sum(x["impact_ha"] for x in c if x["verdict"] == v), 1)
    pending = [x["id"] for x in c if x["verdict"] != "confirmed" and not x.get("review")]
    return {"confirmed": count("confirmed"), "needs_review": count("needs_review"),
            "likely_false_alarm": count("likely_false_alarm"), "confirmed_ha": ha("confirmed"),
            "review_ha": round(ha("needs_review") + ha("likely_false_alarm"), 1),
            "pending_review": len(pending),
            "removed_by_analyst": sum(1 for x in c if (x.get("review") or {}).get("decision") == "remove")}


def load(run_id: str) -> dict | None:
    p = RUNS_DIR / run_id / "inspection.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save(run_id: str, res: dict):
    (RUNS_DIR / run_id / "inspection.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


def review(run_id: str, cell_id: str, decision: str, by: str = "analyst", note: str = "") -> dict:
    """An analyst keeps or removes a cell. Removal takes effect in apply_review()."""
    if decision not in ("keep", "remove"):
        raise ValueError("decision must be keep or remove")
    res = load(run_id)
    for c in res["cells"]:
        if c["id"] == cell_id:
            c["review"] = {"decision": decision, "by": by, "note": note, "utc": _now()}
            break
    else:
        raise KeyError(cell_id)
    res["summary"] = summary(res)
    save(run_id, res)
    return res["summary"]


def apply_review(run_id: str) -> dict:
    """Re-run the pipeline with the analyst-removed cells vetoed. Damage, access and the report follow."""
    from .pipeline import run
    res = load(run_id)
    removed = [c for c in res["cells"] if (c.get("review") or {}).get("decision") == "remove"]
    facts = json.loads((RUNS_DIR / run_id / "facts.json").read_text(encoding="utf-8"))
    veto = [{"rows": c["rows"], "cols": c["cols"], "id": c["id"]} for c in removed]
    return run(facts["area"]["bbox"], facts["event_time_utc"], veto=veto)


def ready_to_publish(run_id: str) -> tuple[bool, str]:
    res = load(run_id)
    if res is None:
        return False, "not inspected yet"
    s = res["summary"]
    if s["pending_review"]:
        return False, f"{s['pending_review']} cells await an analyst"
    return True, "inspection complete"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--max-cells", type=int, default=40)
    ap.add_argument("--planner", choices=["rules", "llm"], default=os.getenv("WATERGUARD_INSPECTOR", "rules"))
    a = ap.parse_args()
    res = inspect(a.run_id, a.max_cells, a.planner, progress=lambda m, p: print(f"{p:3d}% {m}", flush=True))
    print(json.dumps(res["summary"], indent=1))
    for c in res["cells"]:
        print(f"{c['id']:>12} {c['verdict']:>18}  {c['impact_ha']:>6} ha  {c['reason']}")


if __name__ == "__main__":
    main()
