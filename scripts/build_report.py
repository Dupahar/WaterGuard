"""Fill docs/REPORT.md tables from docs/validation_emsr927.json and print docs/REPORT.pdf.

    python scripts/build_report.py
Needs Google Chrome or Microsoft Edge for the PDF (headless print).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def tables():
    v = json.loads((DOCS / "validation_emsr927.json").read_text())
    rows = [r for r in v if "aoi" in r]
    fa = next((r["false_alarm_tests"] for r in v if "false_alarm_tests" in r), [])
    t = ["| EMS area | Split | EMS impact (ha) | Ours (ha) | Precision | Recall | **F1** | IoU | Valley-only baseline F1 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        a, b = r["area"], r["valley_baseline"]
        t.append(f"| AOI{r['aoi']:02d} {r['name']} | {r['split']} | {r['ref_ha']} | {r['ours_ha']} | {a['precision']:.2f} | "
                 f"{a['recall']:.2f} | **{a['f1']:.2f}** | {a['iou']:.2f} | {b['f1']:.2f} |")
    t += ["", "| EMS area | EMS damaged/destroyed building points on our impact map | Destroyed | Damaged | Possibly damaged | EMS damaged bridges: in pre-event OSM / flagged by us |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        b = r.get("buildings", {})
        br = r.get("bridges", {})
        g = b.get("by_grade", {})
        t.append(f"| AOI{r['aoi']:02d} | {b.get('on_our_impact_map', '–')}/{b.get('ems_damaged_points', '–')} "
                 f"({(b.get('recall') or 0) * 100:.0f}%) | {g.get('Destroyed', '–')} | {g.get('Damaged', '–')} | "
                 f"{g.get('Possibly damaged', '–')} | {br.get('in_pre_event_osm', '–')} / {br.get('flagged_by_us', '–')} of {br.get('ems_damaged_bridges', '–')} |")
    f = ["| Test | Area (km²) | Impact mapped (ha) | of which riverbed, lower confidence (ha) | Buildings likely affected | Bridges likely damaged |", "|---|---|---|---|---|---|"]
    for x in fa:
        f.append(f"| {x['test']} | {x['area_km2']} | {x['impact_ha']} | {x.get('of_which_riverbed_lower_confidence_ha', '–')} | {x['buildings_likely_affected']} | {x['bridges_likely_damaged']} |")
    return "\n".join(t), "\n".join(f)


def main():
    res, fa = tables()
    md = (DOCS / "REPORT.md").read_text(encoding="utf-8")
    md = md.replace("RESULTS_TABLE", res).replace("FALSE_ALARM_TABLE", fa)
    (DOCS / "REPORT_filled.md").write_text(md, encoding="utf-8")
    body = markdown.markdown(md, extensions=["tables"])
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 14mm 14mm; }}
body {{ font: 10.2px/1.42 'Segoe UI', Arial, sans-serif; color:#111; }}
h1 {{ font-size: 18px; margin: 0 0 4px; }} h2 {{ font-size: 13px; margin: 12px 0 4px; border-bottom: 2px solid #c8461a; }}
table {{ border-collapse: collapse; width: 100%; margin: 4px 0 8px; font-size: 9.4px; }}
td, th {{ border: 1px solid #ccc; padding: 2px 4px; text-align: left; }} th {{ background: #f2f2f2; }}
p, li {{ margin: 3px 0; }} img {{ max-width: 100%; }}
</style></head><body>{body}</body></html>"""
    (DOCS / "REPORT.html").write_text(html, encoding="utf-8")
    browser = next((p for p in [shutil.which("chrome"), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"] if p and Path(p).exists()), None)
    if not browser:
        sys.exit("No Chrome/Edge found: open docs/REPORT.html and print to PDF")
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={DOCS / 'REPORT.pdf'}", (DOCS / "REPORT.html").as_uri()], check=True,
                   capture_output=True)
    print("wrote", DOCS / "REPORT.pdf")


if __name__ == "__main__":
    main()
