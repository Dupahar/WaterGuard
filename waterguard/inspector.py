"""Inspector agent: looks again at every part of the impact map that matters, before a report goes out.

    python -m waterguard.inspector <run_id> [--max-cells 40] [--planner rules|llm]

A loop of perception -> decision -> action per inspection cell (600 m), most exposed first, repeated
until the cell is settled (at most MAX_STEPS tool calls):

  perceive   vision.measure(): ECC co-registration, colour / structure / texture / vegetation / radar
             contrast against nearby unflagged ground, dense-flow residual misalignment, edge
             artefacts, patch shape (OpenCV 5)
  decide     how many independent lines of evidence agree, whether the images line up, and whether
             the sky was clear enough
  act        realign:    the images do not line up: re-align on SIFT keypoints with USAC MAGSAC++
                         (robust to the changed ground) and measure again
             zoom:       evidence is mixed: measure the cell's four 300 m quadrants separately
             look_later: fetch a fresh cloud-free Sentinel-2 composite of just this cell weeks later
                         and measure again (debris persists; wet soil, turbid water, green-up fade)
             confirm:    strong, multi-sensor agreement
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

from . import second_look, telemetry, vision
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
MAX_STEPS = 4               # tool calls per cell; after that it goes to a person
MISALIGNED_PX = 1.5         # dense-flow shift left over unflagged ground that calls for a re-alignment
ZOOM_MIN_LINES = 2          # mixed evidence worth a closer look
ZOOM_CONFIRM_SHARE = 0.6    # quadrants where all four lines agree must hold this share of the flagged ground


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


def misaligned(m: dict) -> bool:
    """Clear enough to judge, and ECC did not lock on or the dense flow over unflagged ground still shows a shift."""
    if (m.get("clear_share") or 0) < CLOUDY:
        return False
    return m.get("coreg_shift_px") is None or (m.get("residual_flow_px") or 0) > MISALIGNED_PX


def strong_parts(parts: list) -> tuple[list, float]:
    """Quadrants where all four lines agree, and their share of the cell's flagged ground."""
    tot = sum(p["impact_ha"] for p in parts)
    strong = [p for p in parts if sum(lines(p["measurements"]).values()) >= CONFIRM_LINES]
    return [p["part"] for p in strong], (sum(p["impact_ha"] for p in strong) / tot if tot else 0.0)


def can_confirm(s: dict) -> bool:
    """The evidence bar for 'confirmed', whoever plans (rules or a language model)."""
    n = sum(lines(s["m"]).values())
    if n >= CONFIRM_LINES:
        return True
    if s.get("zoom") and strong_parts(s["zoom"])[1] >= ZOOM_CONFIRM_SHARE:
        return True
    later = s.get("later")
    cloudy = (s["m"].get("clear_share") or 0) < CLOUDY
    return bool(later) and persistence(later) == "persists" and (n >= LATER_LINES or (cloudy and n >= 2))


def _names(L, yes=True):
    return ", ".join(k for k, x in L.items() if x == yes) or "none"


def look_twice(s, action, why):
    """Before a cell goes to a person, a vision-language model may read its chip (second_look.py).
    Its read can only turn 'ask a human' into 'flag as a likely false alarm' (a person still decides),
    and only when the colour line is absent too; otherwise it is attached to the review card. It can
    never confirm."""
    if action != "ask_human":
        return action, why
    sl = s.get("second_look")
    if sl is None and s.get("can_look"):
        return "second_look", f"{why}: let Nemotron VL read the chip before it goes to a person"
    if sl and "error" not in sl:
        read = f"Nemotron VL reads {sl['cause']} ({sl['confidence']:.0%}): {sl['explanation']}"
        if second_look.says_not_flood(sl) and not lines(s["m"])["colour"]:
            return "flag", f"{why}; {read}"
        return "ask_human", f"{why}; {read}"
    return action, why


class RulePlanner:
    """s = the cell's state: m (latest measurements), realign (None | 'ok' | 'failed'),
    zoom (None | quadrant measurements), later (None | measurements of a later image), can_fetch,
    second_look (None | the vision-language model's read), can_look."""
    name = "rules"

    def decide(self, cell, s):
        return look_twice(s, *self._decide(cell, s))

    def _decide(self, cell, s):
        m, later = s["m"], s.get("later")
        L = lines(m)
        n = sum(L.values())
        cloudy = (m.get("clear_share") or 0) < CLOUDY
        if later is None:
            if n >= CONFIRM_LINES:
                return "confirm", f"all {n} evidence lines agree ({_names(L)})"
            if s.get("realign") is None and misaligned(m):
                why = ("ECC could not lock on" if m.get("coreg_shift_px") is None
                       else f"{m['residual_flow_px']:.2f} px of shift left over unflagged ground")
                return "realign", f"before and after do not line up ({why}): re-align on SIFT keypoints and measure again"
            if s.get("zoom") is None and not cloudy and n >= ZOOM_MIN_LINES:
                return "zoom", (f"{n} of 4 evidence lines agree ({_names(L, False)} missing): "
                                "measure the four 300 m quadrants separately")
            if s.get("zoom"):
                strong, share = strong_parts(s["zoom"])
                if share >= ZOOM_CONFIRM_SHARE:
                    return "confirm", (f"all 4 evidence lines agree in the {', '.join(strong)} quadrant"
                                       f"{'s' if len(strong) > 1 else ''}, {share:.0%} of the flagged ground")
            # only spend a download where a second look can change the outcome
            if s["can_fetch"] and (n >= LATER_LINES or cloudy):
                why = "clouds hid most of it" if cloudy else f"{n} of 4 evidence lines agree ({_names(L, False)} missing)"
                return "look_later", f"{why}: fetch a later cloud-free image to see whether the change persists"
            agree = f"{n} of 4 evidence lines agree ({_names(L)})"
            if n >= LATER_LINES or cloudy:
                return "ask_human", f"{agree}; a later look could settle it but the download budget is used up"
            return "ask_human", f"only {agree}: too weak for a later image to confirm"
        p = persistence(later)
        if p == "persists" and can_confirm(s):
            return "confirm", f"{n} of 4 evidence lines agree and the colour change persists weeks later"
        if p == "reverted":
            return "flag", "the ground looks like it did before the flood again: probably seasonal, not flood damage"
        return "ask_human", {"persists": f"the change persists but only {n} of 4 evidence lines agree",
                             "unseen": "still no clear later view", "unclear": "later image is ambiguous"}[p]


class LLMPlanner:
    """A language model picks the next tool from the measurements. Guard rails are enforced here,
    not trusted to the model."""
    name = "llm"
    TOOLS = [{"name": a, "description": d, "parameters": {"type": "object", "properties": {
        "reason": {"type": "string", "description": "one sentence, citing the measurements"}}, "required": ["reason"]}}
        for a, d in (("realign", "Before and after images may not line up: re-align on SIFT keypoints and measure again."),
                     ("zoom", "Measure the cell's four 300 m quadrants separately (mixed ground)."),
                     ("look_later", "Fetch a fresh cloud-free image of this cell from weeks later and measure again."),
                     ("confirm", "The flagged ground is flood/debris damage."),
                     ("second_look", "Show the analyst chip (before | after | colour change) to a vision-language model "
                                     "and get its independent read of what caused the change. It cannot confirm."),
                     ("ask_human", "Send to an analyst: evidence is mixed or insufficient."),
                     ("flag", "Likely false alarm (e.g. the change reverted). An analyst still decides."))]
    SYSTEM = ("You inspect one 600 m cell of a satellite flood-impact map. You get OpenCV measurements of the flagged "
              "ground compared with nearby unflagged valley ground ('contrast' = flagged minus reference), the four "
              "evidence lines (colour, vegetation, structure, radar), how well before and after line up "
              "(coreg_shift_px, residual_flow_px), and the results of tools you already used: realign, zoom "
              "(per-quadrant evidence lines), look_later (the same measurements on a later image) and second_look "
              "(a vision-language model's read of the chip). Debris and scour persist for months; wet soil, turbid "
              "water and seasonal green-up do not. Each tool can be used once per cell. Call exactly one tool.")
    PLANNER_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"   # reasoning model for the planner (Nebius Token Factory)

    def __init__(self):
        from .copilot import _backend, _call_bedrock, _call_openai
        b = _backend()
        if b is None:
            raise RuntimeError("no LLM backend configured (see copilot.py)")
        if b == "bedrock":
            self.call, self.model = _call_bedrock, os.getenv("BEDROCK_MODEL", "bedrock default")
        else:
            self.model = (os.getenv("NEBIUS_PLANNER_MODEL", self.PLANNER_MODEL) if b == "nebius"
                          else os.getenv("OPENAI_MODEL"))
            self.call = lambda msgs, tools: _call_openai(msgs, tools, model=self.model)
        self.name = f"llm ({b}: {self.model})"
        self.fallback = RulePlanner()

    def decide(self, cell, s):
        self.__dict__.setdefault("stats", {"decisions": 0, "overruled": 0, "fallback": 0, "seconds": 0.0})
        self.stats["decisions"] += 1
        t = time.time()
        try:
            return self._decide(cell, s)
        finally:
            self.stats["seconds"] = round(self.stats["seconds"] + time.time() - t, 1)

    def _overrule(self, why):
        self.stats["overruled"] += 1
        return "ask_human", why

    def _decide(self, cell, s):
        m, later = s["m"], s.get("later")
        L = lines(m)
        payload = {"cell": {k: cell.get(k) for k in ("impact_ha", "buildings_hit", "road_segments_cut", "people_nearby_est")},
                   "measurements": m, "evidence_lines": L, "misaligned": misaligned(m), "realign": s.get("realign"),
                   "zoom": _lines_brief(s["zoom"]) if s.get("zoom") else None,
                   "later_look": later, "later_persistence": persistence(later) if later else None,
                   "can_fetch_more_imagery": s["can_fetch"],
                   "second_look": s.get("second_look"), "can_use_second_look": bool(s.get("can_look"))}
        msgs = [{"role": "system", "content": self.SYSTEM},
                {"role": "user", "content": json.dumps(payload, default=str)}]
        try:
            _, calls, _ = self.call(msgs, self.TOOLS)
            action, reason = calls[0][1], calls[0][2].get("reason", "")
        except Exception as e:
            self.stats["fallback"] += 1
            a, r = self.fallback.decide(cell, s)
            return a, f"{r} (rules; model unavailable: {str(e)[:60]})"
        n = sum(L.values())
        if action == "confirm" and not can_confirm(s):
            return self._overrule(f"model wanted to confirm ({reason}) but only {n} of 4 lines agree: needs an analyst")
        if action == "look_later" and (not s["can_fetch"] or later is not None):
            return self._overrule(f"model asked for more imagery ({reason}); none available: needs an analyst")
        if (action == "realign" and s.get("realign")) or (action == "zoom" and s.get("zoom") is not None):
            return self._overrule(f"model asked for {action} again ({reason}): needs an analyst")
        if action == "second_look" and not s.get("can_look"):
            return self._overrule(f"model asked for a second look ({reason}); not available or already used: needs an analyst")
        if action not in {"realign", "zoom", "look_later", "second_look", "confirm", "ask_human", "flag"}:
            return self._overrule("model gave no valid action")
        return action, reason


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lines_brief(parts):
    return [{"part": p["part"], "impact_ha": p["impact_ha"], "lines": lines(p["measurements"])} for p in parts]


def settle(ev, cell: dict, P, chips: Path | None = None, later_look=None, tools=("realign", "zoom"),
           look="auto") -> dict:
    """Run the perceive -> decide -> act loop on one cell until it is settled.
    later_look: callable(cell) -> (band overrides, scenes) or None when no more downloads are allowed.
    tools: which OpenCV tools the agent may use (the others count as already tried).
    look: callable(chip path) -> a vision-language model's read (second_look.read), None for no second
    look; "auto" uses Nemotron VL when a Nebius key is set. Needs chips (it reads the chip)."""
    if look == "auto":
        look = second_look.read if second_look.available() else None
    chip = chips / f"{cell['id']}.png" if chips else None
    m = vision.measure(ev, cell, chip)
    trace = [{"step": "perceive", "tool": "vision.measure", "lines": lines(m),
              "coreg_shift_px": m.get("coreg_shift_px"), "residual_flow_px": m.get("residual_flow_px")}]
    s = {"m": m, "realign": None if "realign" in tools else "off", "zoom": None if "zoom" in tools else [],
         "later": None, "second_look": None}
    for step in range(MAX_STEPS + 1):
        s["can_fetch"] = later_look is not None and s["later"] is None
        s["can_look"] = look is not None and chip is not None and s["second_look"] is None
        action, why = P.decide(cell, s)
        if action not in ("confirm", "ask_human", "flag") and step == MAX_STEPS:
            action, why = "ask_human", f"{why} (step budget used up: needs an analyst)"
        trace.append({"step": "decide", "action": action, "reason": why})
        if action in ("confirm", "ask_human", "flag"):
            break
        if action == "realign":
            aligned = chips / f"{cell['id']}_aligned.png" if chips else None
            mf = vision.measure(ev, cell, aligned, features=True)
            ok = mf.get("coreg_shift_px") is not None
            s["realign"] = "ok" if ok else "failed"
            if ok:
                s["m"], chip = mf, aligned
            trace.append({"step": "act", "tool": "vision.realign", "ok": ok, "inliers": mf.get("coreg_inliers"),
                          "shift_px": mf.get("coreg_shift_px"), "residual_flow_px": mf.get("residual_flow_px"),
                          "lines": lines(s["m"])})
        elif action == "zoom":
            s["zoom"] = vision.zoom(ev, cell, features=s["realign"] == "ok")
            strong, share = strong_parts(s["zoom"])
            trace.append({"step": "act", "tool": "vision.zoom", "parts": _lines_brief(s["zoom"]),
                          "strong_parts": strong, "strong_share": round(share, 3)})
        elif action == "look_later":
            ov, scenes = later_look(cell)
            later = vision.measure(ev, cell, chips / f"{cell['id']}_later.png" if chips else None, rgb_override=ov,
                                   features=s["realign"] == "ok") if ov else {}
            later["scenes"] = scenes
            s["later"] = later
            trace.append({"step": "act", "tool": "vision.later_look", "scenes": scenes,
                          "persistence": persistence(later)})
        elif action == "second_look":
            s["second_look"] = sl = look(chip)
            trace.append({"step": "act", "tool": "nemotron.second_look",
                          **{k: sl.get(k) for k in ("cause", "confidence", "explanation", "debris_visible",
                                                    "vegetation_lost", "model", "seconds", "error")}})
    verdict = {"confirm": "confirmed", "ask_human": "needs_review", "flag": "likely_false_alarm"}[action]
    return {"verdict": verdict, "reason": why, "state": s, "trace": trace,
            "chip": chip.name if chip else None}


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

    def later_look(cell):
        nonlocal fetches
        fetches += 1
        ov, used = vision.later_look(ev, cell, facts["event_time_utc"], provider)
        return ov, [u["date"] for u in used]

    for i, cell in enumerate(todo[:max_cells]):
        progress(f"inspecting cell {i + 1}/{min(len(todo), max_cells)}", int(100 * i / max(min(len(todo), max_cells), 1)))
        tc = time.time()
        r = settle(ev, cell, P, chips, later_look if fetches < max_fetches else None)
        s, verdict, why = r["state"], r["verdict"], r["reason"]
        tools_used = [t["tool"] for t in r["trace"] if t["step"] == "act"]
        out.append({**cell, "verdict": verdict, "reason": why, "measurements": s["m"], "realign": s["realign"],
                    "zoom": _lines_brief(s["zoom"]) if s["zoom"] else None, "later": s["later"],
                    "second_look": s["second_look"], "trace": r["trace"],
                    "chip": f"inspect/{r['chip']}",
                    "chip_later": f"inspect/{cell['id']}_later.png" if s["later"] else None,
                    "review": None})
        telemetry.emit("inspect_cell", {"Planner": P.name.split(" ")[0], "Verdict": verdict},
                       {"Cells": (1, "Count"), "ToolCalls": (len(tools_used), "Count"),
                        "CellSeconds": (round(time.time() - tc, 2), "Seconds")},
                       run_id=run_id, cell=cell["id"], tools=tools_used, reason=why)
    old = load(run_id)
    if old:   # keep analyst decisions already made on the same cells
        prev = {c["id"]: c.get("review") for c in old["cells"]}
        for c in out:
            c["review"] = prev.get(c["id"])
    tool_calls = {}
    for c in out:
        for t in c["trace"]:
            if t["step"] == "act":
                tool_calls[t["tool"]] = tool_calls.get(t["tool"], 0) + 1
    res = {"run_id": run_id, "planner": P.name, "inspected_utc": _now(), "runtime_s": round(time.time() - t0, 1),
           "cells_total": len(todo), "cells_inspected": len(out), "later_looks": fetches, "tool_calls": tool_calls,
           "planner_stats": getattr(P, "stats", None), "cells": out}
    res["summary"] = summary(res)
    save(run_id, res)
    s = res["summary"]
    telemetry.emit("inspect_run", {"Planner": P.name.split(" ")[0]},
                   {"RunSeconds": (res["runtime_s"], "Seconds"), "CellsConfirmed": (s["confirmed"], "Count"),
                    "CellsToAnalyst": (s["needs_review"] + s["likely_false_alarm"], "Count"),
                    "LaterLooks": (fetches, "Count")}, run_id=run_id, tool_calls=tool_calls)
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
    return run(facts["area"]["bbox"], facts["event_time_utc"], veto=veto,
               exposure=facts.get("method", {}).get("exposure", "osm"))


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
