"""Dashboard + API.   python -m waterguard.server   ->  http://localhost:8000

POST /api/runs {bbox:[w,s,e,n], date}      start (or reuse) an analysis; returns {run_id}
GET  /api/runs/{id}                         progress / facts when done
GET  /api/runs                              finished runs
GET  /api/runs/{id}/sitrep?lang=en|ne       one-page situation report (printable HTML)
POST /api/runs/{id}/chat {message, history, point?}   copilot
POST /api/runs/{id}/trace {lon, lat}        flood path from a point + settlements along it
GET  /api/runs/{id}/proof                   Merkle roots, per-settlement proofs, public-ledger status
POST /api/runs/{id}/inspect                 start the inspector agent; GET /api/runs/{id}/inspection for results
POST /api/runs/{id}/inspection/{cell} {decision: keep|remove, note}   analyst review
POST /api/runs/{id}/apply-review            re-run with removed cells vetoed, then fingerprint (and anchor)
GET  /runs/{id}/<file>                      layers (GeoJSON / PNG overlays)
"""
import json
import os
import threading
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chain, copilot, inspector, ledger, sitrep
from .config import ROOT
from .pipeline import EXPOSURE_MODES, RUNS_DIR, default_exposure, run, run_id
from .providers.base import as_utc

app = FastAPI(title="WaterGuard")
JOBS: dict = {}
LOCK = threading.Lock()
# Runs are memory-hungry: on a shared server, execute at most this many at once (the rest wait as "queued").
SLOTS = threading.Semaphore(int(os.getenv("WATERGUARD_MAX_JOBS", "1")))
STATIC = ROOT / "web"


class RunReq(BaseModel):
    bbox: list[float]
    date: str
    exposure: str | None = None     # "osm" | "open" (default: WATERGUARD_EXPOSURE)


class ChatReq(BaseModel):
    message: str
    history: list = []
    point: dict | None = None


class ReviewReq(BaseModel):
    decision: str
    note: str = ""


class PointReq(BaseModel):
    lon: float
    lat: float


def _facts(rid):
    p = RUNS_DIR / rid / "facts.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


MAX_QUEUE = int(os.getenv("WATERGUARD_MAX_QUEUE", "4"))          # runs + inspections waiting or running
ALLOW_LLM_PLANNER = os.getenv("WATERGUARD_ALLOW_LLM_PLANNER", "") == "1"


def _busy() -> int:
    return sum(j.get("state") == "running" for j in list(JOBS.values()) + list(INSPECT.values()))


@app.post("/api/runs")
def start(req: RunReq):
    if len(req.bbox) != 4:
        raise HTTPException(400, "bbox must be [west, south, east, north]")
    w, s_, e, n = req.bbox
    if not (-180 <= w < e <= 180 and -90 <= s_ < n <= 90):
        raise HTTPException(400, "bbox must be [west, south, east, north] in degrees")
    date = req.date if "T" in req.date else req.date + "T00:00:00Z"
    try:
        ev = as_utc(date)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD or an ISO time")
    if not datetime(2015, 1, 1, tzinfo=timezone.utc) <= ev <= datetime.now(timezone.utc) + timedelta(days=1):
        raise HTTPException(400, "the event date must be between 2015 and today")
    exposure = req.exposure or default_exposure()
    if exposure not in EXPOSURE_MODES:
        raise HTTPException(400, f"exposure must be one of {EXPOSURE_MODES}")
    rid = run_id(req.bbox, date, exposure)
    if _facts(rid):
        return {"run_id": rid, "cached": True}
    with LOCK:
        if rid in JOBS and JOBS[rid]["state"] == "running":
            return {"run_id": rid}
        if _busy() >= MAX_QUEUE:
            raise HTTPException(429, "the server is busy with other analyses; try again in a few minutes")
        JOBS[rid] = {"state": "running", "step": "queued", "pct": 0}

    def work():
        try:
            with SLOTS:
                run(req.bbox, date, progress=lambda m, p: JOBS[rid].update(step=m, pct=p), exposure=exposure)
            JOBS[rid]["state"] = "done"
            ledger.build(rid)
        except Exception as e:
            traceback.print_exc()
            JOBS[rid].update(state="error", error=str(e))

    threading.Thread(target=work, daemon=True).start()
    return {"run_id": rid}


@app.get("/api/runs")
def runs():
    out = []
    for d in sorted(RUNS_DIR.glob("*/facts.json"), key=lambda p: -p.stat().st_mtime):
        f = json.loads(d.read_text(encoding="utf-8"))
        out.append({"run_id": f["run_id"], "bbox": f["area"]["bbox"], "event": f["event_time_utc"],
                    "impact_ha": f["impact"]["impact_ha"]})
    return out


@app.get("/api/runs/{rid}")
def status(rid: str):
    f = _facts(rid)
    if f:
        return {"state": "done", "pct": 100, "facts": f}
    if rid in JOBS:
        return JOBS[rid]
    raise HTTPException(404, "unknown run")


@app.get("/api/runs/{rid}/sitrep", response_class=HTMLResponse)
def report(rid: str, lang: str = "en"):
    if not _facts(rid):
        raise HTTPException(404, "unknown run")
    return sitrep.render(rid, "ne" if lang == "ne" else "en")


@app.post("/api/runs/{rid}/chat")
def chat(rid: str, req: ChatReq):
    if not _facts(rid):
        raise HTTPException(404, "unknown run")
    if len(req.message) > 600:
        raise HTTPException(400, "question too long (600 characters at most)")
    history = [{"role": h.get("role"), "text": str(h.get("text", ""))[:2000]} for h in req.history[-6:]
               if isinstance(h, dict) and h.get("role") in ("user", "assistant")]
    try:
        return copilot.ask(rid, req.message, history, req.point)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/runs/{rid}/trace")
def trace(rid: str, req: PointReq):
    if not _facts(rid):
        raise HTTPException(404, "unknown run")
    t = copilot.RunTools(rid)
    try:
        res = t.trace_flood_path(req.lon, req.lat)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return res | {"actions": t.actions}


def anchor(rid):
    """Fingerprint the run; anchor it publicly when this server holds a ledger key and an analyst
    has cleared every cell the inspector could not confirm."""
    try:
        ledger.build(rid)
        ok, _ = inspector.ready_to_publish(rid)
        if ok and os.getenv("WATERGUARD_LEDGER_KEY"):
            lg = chain.Ledger()
            if lg.registry is not None:
                lg.publish(rid)
    except Exception:
        traceback.print_exc()


@app.get("/api/runs/{rid}/proof")
def proof(rid: str):
    if not _facts(rid):
        raise HTTPException(404, "unknown run")
    p = ledger.load(rid) or ledger.build(rid)
    on = chain.onchain_summary(rid)
    if on:
        from web3 import Web3
        on["status_selector"] = "0x" + Web3.keccak(text="status(bytes32)")[:4].hex()
    return p | {"chain": on}


INSPECT: dict = {}
# On a shared public demo, analyst decisions would let any visitor edit the review queue for everyone.
READONLY_REVIEW = os.getenv("WATERGUARD_READONLY_REVIEW", "") == "1"


@app.post("/api/runs/{rid}/inspect")
def start_inspect(rid: str, planner: str = "rules"):
    if not _facts(rid):
        raise HTTPException(404, "unknown run")
    if planner not in ("rules", "llm") or (planner == "llm" and not ALLOW_LLM_PLANNER):
        planner = "rules"            # the model planner costs real money: only where the operator allows it
    if INSPECT.get(rid, {}).get("state") == "running":
        return INSPECT[rid]
    if _busy() >= MAX_QUEUE:
        raise HTTPException(429, "the server is busy with other analyses; try again in a few minutes")
    INSPECT[rid] = {"state": "running", "step": "queued", "pct": 0}

    def work():
        try:
            with SLOTS:
                inspector.inspect(rid, planner=planner, progress=lambda m, p: INSPECT[rid].update(step=m, pct=p))
            INSPECT[rid]["state"] = "done"
            anchor(rid)
        except Exception as e:
            traceback.print_exc()
            INSPECT[rid].update(state="error", error=str(e))

    threading.Thread(target=work, daemon=True).start()
    return INSPECT[rid]


@app.get("/api/runs/{rid}/inspection")
def get_inspection(rid: str):
    res = inspector.load(rid)
    job = INSPECT.get(rid)
    if job and job["state"] == "running":
        return {"job": job, "result": res}
    if res is None:
        raise HTTPException(404, "not inspected")
    ok, why = inspector.ready_to_publish(rid)
    return {"job": job, "result": res, "ready_to_publish": ok, "publish_status": why, "readonly_review": READONLY_REVIEW}


@app.post("/api/runs/{rid}/inspection/{cell}")
def review_cell(rid: str, cell: str, req: ReviewReq):
    if READONLY_REVIEW:
        raise HTTPException(403, "Analyst review is read-only on the public demo. Run WaterGuard locally to review cells.")
    try:
        s = inspector.review(rid, cell, req.decision, note=req.note)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return s


@app.post("/api/runs/{rid}/apply-review")
def apply_review(rid: str):
    if READONLY_REVIEW:
        raise HTTPException(403, "Analyst review is read-only on the public demo. Run WaterGuard locally to review cells.")
    ok, why = inspector.ready_to_publish(rid)
    if not ok:
        raise HTTPException(409, why)
    with SLOTS:
        facts = inspector.apply_review(rid)
    anchor(rid)
    return {"facts": facts}


@app.get("/runs/{rid}/{name:path}")
def run_file(rid: str, name: str):
    p = (RUNS_DIR / rid / name).resolve()   # name may be "inspect/<cell>.png"
    if RUNS_DIR.resolve() not in p.parents or not p.exists() or p.suffix not in (".geojson", ".png", ".json", ".tif"):
        raise HTTPException(404)
    return FileResponse(p)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
