"""Capture the real dashboard, state by state, for the product film (public/ui/*.png + ui.json).

Drives a local WaterGuard server the way a user would (Playwright + Edge, 1600x900 CSS px at 2x), and
records the on-screen box of every element the film's cursor touches, so the film animates a pointer
onto the exact spot in each still.

    python video/scripts/capture_ui.py [http://localhost:8010]
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010"
RID = "e34c30aded"
OUT = Path(__file__).resolve().parents[1] / "public/ui"
OUT.mkdir(parents=True, exist_ok=True)
VW, VH = 1600, 900
meta = {"w": VW, "h": VH, "dpr": 2, "states": {}}


def box(pg, sel, nth=0):
    el = pg.locator(sel).nth(nth)
    b = el.bounding_box()
    return [round(b["x"], 1), round(b["y"], 1), round(b["width"], 1), round(b["height"], 1)] if b else None


def idle(pg, extra=600):
    pg.wait_for_function("() => window.map && map.loaded() && !map.isMoving()", timeout=60000)
    pg.wait_for_timeout(extra)


def snap(pg, name, boxes=None, full=False):
    pg.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    meta["states"][name] = {"boxes": boxes or {}}
    print("captured", name)


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=2)
    pg = ctx.new_page()
    pg.goto(BASE + "/")
    idle(pg, 2500)
    snap(pg, "a_empty", {"preset": box(pg, "#preset"), "run": box(pg, "#runBtn"), "date": box(pg, "#date")})

    pg.select_option("#preset", "85.313,28.139,85.358,28.198|2026-08-25T22")
    idle(pg, 1500)
    snap(pg, "a_preset", {"run": box(pg, "#runBtn"), "bbox": box(pg, "#bboxTxt")})

    # the real run is cached; show what the progress bar looks like mid-run
    pg.evaluate("""() => { $('#progress').hidden = false; $('#progress .bar i').style.transition = 'none';
                           $('#progress .bar i').style.width = '62%'; $('#progress span').textContent = '62% · Sentinel-2 optical change'; }""")
    pg.wait_for_timeout(300)
    snap(pg, "a_progress", {"progress": box(pg, "#progress")})
    pg.evaluate("() => { $('#progress').hidden = true; }")

    pg.click("#runBtn")
    pg.wait_for_selector("#results:not([hidden])", timeout=60000)
    idle(pg, 3000)
    snap(pg, "b_result", {"tiles": box(pg, "#tiles"), "layers": box(pg, "#layers"), "cut": box(pg, "#tab-cut"),
                          "tile0": box(pg, "#tiles .tile", 0), "tile1": box(pg, "#tiles .tile", 1)})

    after = pg.locator("#layers button", has_text="Sentinel-2 after")
    before = pg.locator("#layers button", has_text="Sentinel-2 before")
    impact = pg.locator("#layers button", has_text="Flood / debris impact")
    impact.click(); after.click()
    idle(pg, 1200)
    snap(pg, "b_after", {"after_btn": box(pg, "#layers button >> text=Sentinel-2 after"),
                         "impact_btn": box(pg, "#layers button >> text=Flood / debris impact")})
    after.click(); before.click()
    idle(pg, 1200)
    snap(pg, "b_before", {"before_btn": box(pg, "#layers button >> text=Sentinel-2 before")})
    before.click(); impact.click()
    idle(pg, 800)

    xy = pg.evaluate("""() => { const f = map.queryRenderedFeatures({layers:['settlements']}).find(x => x.properties.name === 'Syabru Bensi');
                               const q = map.project(f.geometry.coordinates); return [q.x, q.y]; }""")
    pg.mouse.click(xy[0], xy[1])
    pg.wait_for_timeout(900)
    snap(pg, "b_popup", {"dot": [xy[0] - 8, xy[1] - 8, 16, 16], "popup": box(pg, ".maplibregl-popup-content")})
    pg.keyboard.press("Escape")
    pg.evaluate("() => document.querySelectorAll('.maplibregl-popup').forEach(e => e.remove())")

    pg.click('.tabs button[data-tab="bridges"]')
    pg.wait_for_timeout(500)
    snap(pg, "b_bridges", {"tab": box(pg, '.tabs button[data-tab="bridges"]'), "list": box(pg, "#tab-bridges")})

    # copilot, English then Nepali (answers come from the configured LLM, numbers verified)
    pg.click('.tabs button[data-tab="ask"]')
    pg.wait_for_timeout(400)
    snap(pg, "c_ask0", {"tab": box(pg, '.tabs button[data-tab="ask"]'), "input": box(pg, "#askIn")})
    pg.fill("#askIn", "Which villages are cut off, and how many people?")
    snap(pg, "c_ask_typed", {"input": box(pg, "#askIn"), "send": box(pg, "#askForm button")})
    pg.click("#askForm button")
    pg.wait_for_function("() => [...document.querySelectorAll('#chat .msg.bot')].some(m => m.textContent !== '…')", timeout=120000)
    idle(pg, 2500)
    snap(pg, "c_ask1", {"chat": box(pg, "#chat"), "meta": box(pg, "#chat .msg.bot .meta")})
    pg.fill("#askIn", "कुन कुन पुल भत्किए?")
    pg.click("#askForm button")
    pg.wait_for_function("() => document.querySelectorAll('#chat .msg.bot').length >= 2 && ![...document.querySelectorAll('#chat .msg.bot')].some(m => m.textContent === '…')", timeout=120000)
    idle(pg, 2500)
    snap(pg, "c_ask2", {"chat": box(pg, "#chat"), "meta": box(pg, "#chat .msg.bot .meta", 1)})

    # report tab + flood path
    pg.click('.tabs button[data-tab="report"]')
    pg.wait_for_timeout(400)
    snap(pg, "d_report_tab", {"tab": box(pg, '.tabs button[data-tab="report"]'), "en": box(pg, "#repEn"), "ne": box(pg, "#repNe"),
                              "trace": box(pg, "#traceBtn")})
    pg.evaluate("() => { markers.forEach(m => m.remove()); const b = state.bbox; map.fitBounds([[b[0], b[1]], [b[2], b[3]]], {padding: {top: 110, bottom: 60, left: 60, right: 60}, duration: 0}); }")
    idle(pg, 1500)
    pg.click("#traceBtn")
    up = pg.evaluate("""async () => { const g = await fetch(`/runs/${state.runId}/impact.geojson`).then(r => r.json());
        let best = null; for (const f of g.features) for (const ring of (f.geometry.type === 'Polygon' ? [f.geometry.coordinates[0]] : f.geometry.coordinates.map(p => p[0])))
          for (const c of ring) if (!best || c[1] > best[1]) best = c;
        const q = map.project(best); return [q.x, q.y]; }""")
    pg.mouse.click(up[0], up[1])
    pg.wait_for_function("() => document.querySelector('#traceOut').textContent.includes('Path')", timeout=60000)
    idle(pg, 2000)
    snap(pg, "d_trace", {"click": [up[0] - 8, up[1] - 8, 16, 16], "out": box(pg, "#traceOut"), "trace": box(pg, "#traceBtn")})

    # inspector
    pg.evaluate("() => map.getSource('path') && map.getSource('path').setData({type:'FeatureCollection',features:[]})")
    pg.evaluate("() => { markers.forEach(m => m.remove()); }")
    pg.click('.tabs button[data-tab="inspect"]')
    pg.wait_for_timeout(1500)
    pg.evaluate("() => { const P = document.querySelector('.panel'); P.scrollTop += document.querySelector('.tabs').getBoundingClientRect().top - 70; }")
    pg.wait_for_timeout(600)
    snap(pg, "f_inspect", {"tab": box(pg, '.tabs button[data-tab="inspect"]'), "tiles": box(pg, "#inspectTiles"),
                           "first": box(pg, "#cellList li", 0)})
    pg.evaluate("() => { document.querySelector('.panel').scrollTop += 900; }")
    pg.wait_for_timeout(500)
    snap(pg, "f_inspect_list", {"list": box(pg, "#cellList")})
    # the most instructive cell: one that needed a later look
    cid = pg.evaluate("() => (state.inspection.cells.find(c => c.chip_later && c.verdict === 'confirmed') || state.inspection.cells.find(c => c.chip_later) || state.inspection.cells[0]).id")
    pg.evaluate(f"() => openCell(state.runId, state.inspection.cells.find(c => c.id === '{cid}'))")
    pg.wait_for_timeout(1500)
    snap(pg, "f_cell_later", {"card": box(pg, ".lb-card")})
    pg.keyboard.press("Escape")
    rid = pg.evaluate("() => state.inspection.cells.find(c => c.verdict !== 'confirmed' && !c.review).id")
    pg.evaluate(f"() => openCell(state.runId, state.inspection.cells.find(c => c.id === '{rid}'))")
    pg.wait_for_timeout(1500)
    snap(pg, "f_cell_review", {"card": box(pg, ".lb-card"), "keep": box(pg, ".lb-card .acts .keep"), "remove": box(pg, ".lb-card .acts .remove")})
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)

    # proof
    pg.click('.tabs button[data-tab="proof"]')
    pg.wait_for_timeout(2500)
    pg.evaluate("() => { const P = document.querySelector('.panel'); P.scrollTop += document.querySelector('.tabs').getBoundingClientRect().top - 70; }")
    pg.wait_for_timeout(500)
    snap(pg, "g_proof", {"tab": box(pg, '.tabs button[data-tab="proof"]'), "info": box(pg, "#proofInfo"), "verify": box(pg, "#verifyBtn")})
    pg.click("#verifyBtn")
    pg.wait_for_function("() => /confirmations/.test(document.querySelector('#verifyLog').textContent)", timeout=90000)
    pg.wait_for_timeout(500)
    snap(pg, "g_verified", {"log": box(pg, "#verifyLog"), "verify": box(pg, "#verifyBtn")})
    meta["verify_log"] = pg.inner_text("#verifyLog")

    # the printed report (English + Nepali), full page
    rp = ctx.new_page()
    rp.set_viewport_size({"width": 900, "height": 1270})
    for lang in ("en", "ne"):
        rp.goto(f"{BASE}/api/runs/{RID}/sitrep?lang={lang}")
        rp.wait_for_timeout(1800)
        rp.screenshot(path=str(OUT / f"sitrep_{lang}.png"), full_page=True)
        print("captured sitrep", lang)
    b.close()

(OUT / "ui.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", OUT / "ui.json")
