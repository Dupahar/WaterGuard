"""Dashboard + API.   python -m waterguard.server   ->  http://localhost:8000

POST /api/runs {bbox:[w,s,e,n], date}      start (or reuse) an analysis; returns {run_id}
GET  /api/runs/{id}                         progress / facts when done
GET  /api/runs                              finished runs
GET  /api/runs/{id}/sitrep?lang=en|ne       one-page situation report (printable HTML)
POST /api/runs/{id}/chat {message, history, point?}   copilot
POST /api/runs/{id}/trace {lon, lat}        flood path from a point + settlements along it
GET  /runs/{id}/<file>                      layers (GeoJSON / PNG overlays)
"""
import json
import threading
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import copilot, sitrep
from .config import ROOT
from .pipeline import RUNS_DIR, run, run_id

app = FastAPI(title="WaterGuard")
JOBS: dict = {}
LOCK = threading.Lock()
STATIC = ROOT / "web"


class RunReq(BaseModel):
    bbox: list[float]
    date: str


class ChatReq(BaseModel):
    message: str
    history: list = []
    point: dict | None = None


class PointReq(BaseModel):
    lon: float
    lat: float


def _facts(rid):
    p = RUNS_DIR / rid / "facts.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


@app.post("/api/runs")
def start(req: RunReq):
    if len(req.bbox) != 4:
        raise HTTPException(400, "bbox must be [west, south, east, north]")
    date = req.date if "T" in req.date else req.date + "T00:00:00Z"
    rid = run_id(req.bbox, date)
    if _facts(rid):
        return {"run_id": rid, "cached": True}
    with LOCK:
        if rid in JOBS and JOBS[rid]["state"] == "running":
            return {"run_id": rid}
        JOBS[rid] = {"state": "running", "step": "queued", "pct": 0}

    def work():
        try:
            run(req.bbox, date, progress=lambda m, p: JOBS[rid].update(step=m, pct=p))
            JOBS[rid]["state"] = "done"
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
    try:
        return copilot.ask(rid, req.message, req.history, req.point)
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


@app.get("/runs/{rid}/{name}")
def run_file(rid: str, name: str):
    p = (RUNS_DIR / rid / name).resolve()
    if RUNS_DIR.resolve() not in p.parents or not p.exists() or p.suffix not in (".geojson", ".png", ".json", ".tif"):
        raise HTTPException(404)
    return FileResponse(p)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
