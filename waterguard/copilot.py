"""Situation-report copilot: answers rescuers' questions in English or Nepali.

Core rule: every number must come from the system's maps, never from the language model.
How we enforce it:
  1. The model has no data of its own; it can only call tools that read this run's facts.json and
     GeoJSON layers (and the flood-path tracer).
  2. A verifier extracts every number from the draft answer (ASCII or Devanagari digits) and checks
     that it appears in a tool result of this conversation (or is trivially safe: list ordinals,
     emergency numbers, dates/times of the event). Unverified numbers -> the model gets one retry
     with the list of offending numbers; if it still fails, those numbers are masked and flagged.
  3. If no LLM is configured, a deterministic intent router answers from the same tools, so the
     copilot always works offline.

LLM backends (first available wins): WATERGUARD_LLM=bedrock (Amazon Bedrock Converse, AWS creds)
or openai (any OpenAI-compatible endpoint: OPENAI_BASE_URL + OPENAI_API_KEY + OPENAI_MODEL, e.g.
Nebius Token Factory with an NVIDIA Nemotron model). WATERGUARD_LLM=offline forces the router.
"""
import json
import os
import re
from pathlib import Path

import geopandas as gpd

from . import flowpath
from .config import DATA_DIR

RUNS_DIR = DATA_DIR / "runs"
DEV = str.maketrans("०१२३४५६७८९", "0123456789")
ASCII2DEV = str.maketrans("0123456789", "०१२३४५६७८९")
SAFE_NUMBERS = {"112", "100", "101", "102", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}

SYSTEM = """You are WaterGuard, a flood-damage copilot for rescue teams in Nepal. You answer questions about
ONE analysed area using ONLY the tools. Satellite analysis already ran; tools return its results.

HARD RULES
- Every number you write (counts, km, hectares, people, dates) must be copied from a tool result in this
  conversation. Never estimate, add up or convert numbers yourself; if a figure is not in a tool result, say
  it is not available. If you need a total, call a tool that gives it.
- Language: reply in the language of the user's latest message. Nepali (Devanagari) -> Nepali; English -> English.
  In Nepali you may write digits as Devanagari or ASCII, but the values must be identical.
- People counts are ESTIMATES (buildings x average household size); always say "estimated"/"अनुमानित".
- Buildings/bridges "likely affected/damaged" are inferred from satellite change, not ground-confirmed. Say so
  briefly when relevant.
- Be short and operational: rescuers read on a phone. Bullets, names, numbers, next actions. ~120 words.
- If asked about something outside this area/event, or for medical/legal advice, say you only have the map results.
- Never do arithmetic (no multiplying buildings by household size, no sums). Quote the tool's own totals.
- Never use or mention Copernicus EMS / UNOSAT maps; you do not have them.
"""


# ---------------------------------------------------------------- tools (read-only over a run)
def _clean(obj):
    """numpy scalars -> Python, NaN -> None, so tool results are plain JSON."""
    import math

    def conv(o):
        if hasattr(o, "item"):
            o = o.item()
        if isinstance(o, float) and math.isnan(o):
            return None
        return o if isinstance(o, (int, float, str, bool)) or o is None else str(o)
    return json.loads(json.dumps(obj, default=conv, allow_nan=True).replace("NaN", "null"))


class RunTools:
    def __init__(self, run_id: str):
        self.dir = RUNS_DIR / run_id
        self.facts = json.loads((self.dir / "facts.json").read_text(encoding="utf-8"))
        self._settlements = None
        self.actions = []   # map actions for the dashboard (fly to, highlight, draw path)

    @property
    def settlements(self):
        if self._settlements is None:
            self._settlements = gpd.read_file(self.dir / "settlements.geojson")
        return self._settlements

    # each tool returns a JSON-serialisable dict
    def get_overview(self) -> dict:
        f = self.facts
        return {"area_km2": f["area"]["area_km2"], "event_time_utc": f["event_time_utc"],
                "impact": f["impact"], "damage": {k: v for k, v in f["damage"].items() if k != "road_km_in_impact_by_class"},
                "access": f["access"],
                "satellite_images_used": {
                    "sentinel1_post": [s["post_time"] for s in f["inputs"]["sentinel1"]],
                    "sentinel2_post_dates": sorted({s["date"] for s in f["inputs"]["sentinel2"] if s["role"] == "post"}),
                    "osm_snapshot": f["inputs"]["osm"]["snapshot_time"]}}

    def list_cut_off(self, include_partly: bool = False) -> dict:
        f = self.facts
        out = {"cut_off_by_road": f["cut_off_settlements"],
               "most_stranded": f.get("most_stranded_settlements", []),
               "estimated_people_stranded_by_road": f["access"].get("people_est_stranded_vehicle"),
               "count_cut_off_by_road": f["access"]["settlements_cut_off_vehicle"],
               "estimated_people_cut_off_by_road": f["access"]["people_est_cut_off_vehicle"],
               "people_estimate_method": f["access"]["people_estimate_method"]}
        if include_partly:
            out["partly_cut"] = f["partly_cut_settlements"]
        for s in f["cut_off_settlements"][:10]:
            self.actions.append({"type": "highlight", "lon": s["lon"], "lat": s["lat"], "label": s["name"]})
        return out

    def find_settlement(self, name: str) -> dict:
        S = self.settlements
        q = name.strip().lower()
        cand = S[S["name"].fillna("").str.lower().str.contains(q, regex=False)
                 | S["name_ne"].fillna("").str.contains(name.strip(), regex=False)]
        if cand.empty:
            # fuzzy: first 4 letters
            cand = S[S["name"].fillna("").str.lower().str.startswith(q[:4])] if len(q) >= 4 else cand
        if cand.empty:
            return {"error": f"No settlement named '{name}' in this area's pre-event OpenStreetMap."}
        r = cand.sort_values("buildings", ascending=False).iloc[0]
        c = r.geometry
        self.actions.append({"type": "fly", "lon": round(c.x, 5), "lat": round(c.y, 5), "label": r["name"]})
        keep = ["name", "name_ne", "kind", "buildings", "people_est", "vehicle_status", "vehicle_lost", "vehicle_stranded_share",
                "vehicle_health_km_before", "vehicle_health_km_after", "foot_status", "foot_lost"]
        d = {k: (None if str(r.get(k)) in ("nan", "None") else r.get(k)) for k in keep if k in r}
        d["lon"], d["lat"] = round(float(c.x), 5), round(float(c.y), 5)
        if d.get("vehicle_stranded_share") is not None:
            d["percent_of_buildings_with_no_road_left"] = round(float(d["vehicle_stranded_share"]) * 100)
        d["status_meaning"] = {"cut off": "no road link left to any town, health facility or the road network beyond the map",
                               "partly cut": "some of its buildings lost every road link (see percent_of_buildings_with_no_road_left) or it lost a destination type (vehicle_lost)",
                               "connected": "road links intact on the map",
                               "isolated before event": "had no mapped road link even before the flood",
                               "no mapped road": "no road within 400 m in pre-event OpenStreetMap"}.get(d.get("vehicle_status"))
        return _clean(d)

    def damaged_bridges(self) -> dict:
        b = self.facts["damaged_bridges"]
        for x in b[:15]:
            self.actions.append({"type": "highlight", "lon": x["lon"], "lat": x["lat"], "label": x["name"]})
        return {"count_likely_damaged": self.facts["damage"]["bridges_likely_damaged"],
                "count_possibly_damaged": self.facts["damage"]["bridges_possibly_damaged"],
                "bridges": b}

    def health_facilities(self) -> dict:
        return {"total_in_area": self.facts["damage"]["health_facilities_total"],
                "affected": self.facts["affected_health_facilities"]}

    def trace_flood_path(self, lon: float, lat: float) -> dict:
        from .grid import Grid
        wd = Path(self.facts["terrain_workdir"])
        line, exited = flowpath.trace(wd, lon, lat)
        g = Grid.from_bbox(tuple(self.facts["area"]["bbox"]))   # the run's 10 m analysis grid
        if line is None:
            return {"error": "Could not trace a path from this point."}
        hand = g.read(str(wd / "hand.tif"))
        S = self.settlements.to_crs(g.crs)
        along = flowpath.along(line, S, hand, g)
        path_ll = gpd.GeoSeries([line], crs=g.crs).to_crs(4326).iloc[0]
        self.actions.append({"type": "path", "coords": [[round(x, 5), round(y, 5)] for x, y in path_ll.coords][::3]})
        return _clean({"path_length_km": round(line.length / 1000, 1), "leaves_analysed_area": exited,
                "assumed_surge_speed_m_per_s": flowpath.ASSUMED_SPEED_MS,
                "settlements_along_path": [
                    {"name": r["name"] or f"unnamed {r['kind'].replace('building cluster', 'cluster')} ({int(r['buildings'])} buildings)",
                     "km_downstream": r["km_downstream"], "lowest_part_above_river_m": r["hand_m"],
                     "minutes_at_assumed_speed": int(r["minutes_at_assumed_speed"]),
                     "buildings": int(r["buildings"])} for _, r in along.head(25).iterrows()]})


TOOL_SPECS = [
    {"name": "get_overview", "description": "Headline numbers for the analysed area: impact area, buildings/roads/bridges affected, settlements cut off, which satellite images were used.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "list_cut_off", "description": "Settlements that lost every road connection (to towns, health facilities, the outside network), largest first, with estimated people.",
     "parameters": {"type": "object", "properties": {"include_partly": {"type": "boolean", "description": "also list settlements that lost some links"}}}},
    {"name": "find_settlement", "description": "Status of one named village/town: buildings, estimated people, road access before/after, road km to nearest health facility before/after.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "place name in English or Nepali"}}, "required": ["name"]}},
    {"name": "damaged_bridges", "description": "Bridges rated likely or possibly damaged, with names and coordinates.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "health_facilities", "description": "Health facilities in the area and which are in/near the impact zone.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "trace_flood_path", "description": "Trace the flood path downstream from a point (lon, lat) on the elevation model and list settlements along it in order.",
     "parameters": {"type": "object", "properties": {"lon": {"type": "number"}, "lat": {"type": "number"}}, "required": ["lon", "lat"]}},
]


# ---------------------------------------------------------------- number verifier
NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)(?![\w])")


def _numbers(text: str) -> list[str]:
    t = text.translate(DEV)
    return [m.group(1).replace(",", "") for m in NUM_RE.finditer(t)]


def _evidence_numbers(results: list) -> set[str]:
    blob = json.dumps(results, ensure_ascii=False).translate(DEV)
    vals = set()
    for m in re.finditer(r"-?\d+(?:\.\d+)?", blob):
        s = m.group(0).lstrip("-")
        vals.add(s)
        try:
            f = float(s)
            vals.update({str(int(round(f))), f"{f:.1f}", f"{f:.0f}"})
            if f == int(f):
                vals.add(str(int(f)))
            if 0 < f < 1:                       # shares may be quoted as percentages
                vals.update({str(int(round(f * 100))), f"{f * 100:.0f}"})
        except ValueError:
            pass
    return vals


def verify(answer: str, results: list) -> tuple[list[str], list[str]]:
    ev = _evidence_numbers(results)
    nums = _numbers(answer)
    bad = []
    for n in nums:
        norm = n.rstrip("0").rstrip(".") if "." in n else n
        if n in ev or norm in ev or n in SAFE_NUMBERS:
            continue
        bad.append(n)
    return nums, bad


def _mask(answer: str, bad: list[str]) -> str:
    for b in sorted(set(bad), key=len, reverse=True):
        for form in {b, b.translate(ASCII2DEV)}:
            answer = re.sub(rf"(?<![\d.]){re.escape(form)}(?![\d.])", "[unverified]", answer)
    return answer


# ---------------------------------------------------------------- LLM backends
def _backend():
    want = os.getenv("WATERGUARD_LLM", "").lower()
    if want == "offline":
        return None
    if want in ("", "openai") and os.getenv("OPENAI_API_KEY"):
        return "openai"
    if want in ("", "bedrock"):
        try:
            import boto3
            boto3.client("sts").get_caller_identity()
            return "bedrock"
        except Exception:
            return None
    return None


def _call_openai(messages, tools):
    from openai import OpenAI
    cli = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None, api_key=os.getenv("OPENAI_API_KEY"))
    r = cli.chat.completions.create(model=os.getenv("OPENAI_MODEL", "nvidia/Llama-3_3-Nemotron-Super-49B-v1_5"),
                                    messages=messages, temperature=0.1,
                                    tools=[{"type": "function", "function": t} for t in tools])
    m = r.choices[0].message
    calls = [(c.id, c.function.name, json.loads(c.function.arguments or "{}")) for c in (m.tool_calls or [])]
    return m.content or "", calls, m


def _bedrock_messages(messages):
    out = []
    for m in messages[1:]:
        if m["role"] == "user":
            out.append({"role": "user", "content": [{"text": m["content"]}]})
        elif m["role"] == "assistant":
            content = []
            if m.get("content"):
                content.append({"text": m["content"]})
            for c in m.get("tool_calls", []):
                content.append({"toolUse": {"toolUseId": c["id"], "name": c["function"]["name"],
                                            "input": json.loads(c["function"]["arguments"] or "{}")}})
            out.append({"role": "assistant", "content": content})
        elif m["role"] == "tool":
            block = {"toolResult": {"toolUseId": m["tool_call_id"], "content": [{"text": m["content"]}]}}
            if out and out[-1]["role"] == "user" and any("toolResult" in c for c in out[-1]["content"]):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def _call_bedrock(messages, tools):
    import boto3
    cli = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "ap-south-1"))
    r = cli.converse(modelId=os.getenv("BEDROCK_MODEL", "apac.amazon.nova-pro-v1:0"),
                     system=[{"text": messages[0]["content"]}], messages=_bedrock_messages(messages),
                     inferenceConfig={"temperature": 0.1, "maxTokens": 900},
                     toolConfig={"tools": [{"toolSpec": {"name": t["name"], "description": t["description"],
                                                         "inputSchema": {"json": t["parameters"]}}} for t in tools]})
    content = r["output"]["message"]["content"]
    text = "".join(c.get("text", "") for c in content)
    calls = [(c["toolUse"]["toolUseId"], c["toolUse"]["name"], c["toolUse"]["input"]) for c in content if "toolUse" in c]
    return text, calls, None


# ---------------------------------------------------------------- offline router
def _is_nepali(text):
    return bool(re.search(r"[ऀ-ॿ]", text))


def _offline(tools: RunTools, question: str, results: list) -> str:
    from .sitrep import offline_answer
    return offline_answer(tools, question, results, nepali=_is_nepali(question))


def _strip(text: str) -> str:
    """Remove model reasoning blocks some models emit (e.g. <thinking>...</thinking>)."""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", text or "", flags=re.S).strip()


# ---------------------------------------------------------------- main entry
def ask(run_id: str, question: str, history: list | None = None, point: dict | None = None) -> dict:
    tools = RunTools(run_id)
    results: list = []
    backend = _backend()
    if backend is None:
        ans = _offline(tools, question, results)
        nums, bad = verify(ans, results)
        return {"answer": ans, "backend": "offline (deterministic)", "numbers_checked": len(nums),
                "unverified": bad, "actions": tools.actions, "tool_calls": [r["tool"] for r in results]}

    sys_msg = SYSTEM + ("\nThe user clicked the map at lon %.5f, lat %.5f." % (point["lon"], point["lat"]) if point else "")
    messages = [{"role": "system", "content": sys_msg}]
    for h in (history or [])[-6:]:
        messages.append({"role": h["role"], "content": h["text"]})
    lang = "Nepali (Devanagari script)" if _is_nepali(question) else "English"
    messages.append({"role": "user", "content": f"{question}\n\n[Reply in {lang}.]"})
    call = _call_openai if backend == "openai" else _call_bedrock

    def loop(msgs):
        for _ in range(6):
            text, calls, raw = call(msgs, TOOL_SPECS)
            if not calls:
                return text
            msgs.append({"role": "assistant", "content": text or None,
                         "tool_calls": [{"id": cid, "type": "function",
                                         "function": {"name": n, "arguments": json.dumps(a)}} for cid, n, a in calls]})
            for cid, n, a in calls:
                try:
                    res = getattr(tools, n)(**a) if n in {t["name"] for t in TOOL_SPECS} else {"error": "unknown tool"}
                except Exception as e:
                    res = {"error": str(e)}
                results.append({"tool": n, "args": a, "result": res})
                msgs.append({"role": "tool", "tool_call_id": cid, "content": json.dumps(res, ensure_ascii=False, default=str)})
        return text

    answer = _strip(loop(messages))
    nums, bad = verify(answer, results + [{"q": question}])
    retried = False
    if bad:
        retried = True
        messages.append({"role": "assistant", "content": answer})
        messages.append({"role": "user", "content":
                         f"VERIFIER: these numbers are not in any tool result: {', '.join(bad)}. Rewrite the answer "
                         "using only numbers copied from tool results (call tools if needed). Same language."})
        answer = _strip(loop(messages))
        nums, bad = verify(answer, results + [{"q": question}])
        if bad:
            answer = _mask(answer, bad)
    return {"answer": answer, "backend": backend, "numbers_checked": len(nums), "unverified": bad,
            "retried": retried, "actions": tools.actions, "tool_calls": [r["tool"] for r in results]}
