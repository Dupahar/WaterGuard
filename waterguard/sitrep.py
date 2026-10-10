"""One-page situation report (English + Nepali), generated from facts.json only.

The report is template-based, not written by a language model, so every number in it is a value
computed by the pipeline. It is printable (A4) HTML; the dashboard links to it.
"""
import html
import json
import re
from datetime import datetime

from .config import DATA_DIR

RUNS_DIR = DATA_DIR / "runs"
DEV = str.maketrans("0123456789", "०१२३४५६७८९")

T = {
    "en": {
        "title": "Flood situation report", "area": "Area", "event": "Event (UTC)", "made": "Generated (UTC)",
        "where": "Where did the flood hit?", "what": "What was damaged?", "who": "Who is cut off?",
        "impact": "{impact_ha} ha of valley floor show flood or debris impact in {patches} patches; "
                  "{new_water_ha} ha are new open water; {riverbed_lower_confidence_ha} ha are riverbed that was already bare "
                  "before the event (lower confidence).",
        "decided": "{share_decided_by_optical_pct}% of the mapped impact is confirmed by clear-sky Sentinel-2; the rest by Sentinel-1 radar.",
        "unassess": "{unassessable_pct_of_area}% of the area could not be assessed (radar layover/shadow and cloud).",
        "bld": "Buildings: <b>{buildings_likely_affected}</b> likely affected (≈ {people_est_in_likely_affected_buildings} people, estimate), {buildings_possibly_affected} possibly affected (of {buildings_total} mapped).",
        "brg": "Bridges: <b>{bridges_likely_damaged}</b> likely damaged, {bridges_possibly_damaged} possibly damaged (of {bridges_total} mapped).",
        "road": "Roads: {road_km_in_impact} km inside the impact zone.",
        "hf": "Health facilities in or next to the impact zone: {health_facilities_affected} (of {health_facilities_total} mapped).",
        "cut": "<b>{settlements_cut_off_vehicle}</b> settlements have lost every road link (estimated <b>{people_est_cut_off_vehicle}</b> people); "
               "{settlements_partly_cut_vehicle} more lost some links. An estimated <b>{people_est_stranded_vehicle}</b> people live in buildings with no road left. On foot (trails included): {settlements_cut_off_foot} cut off.",
        "tbl": ["Settlement", "Buildings", "Buildings with no road", "People stranded (est.)", "Road km to health post: before → after"],
        "unreach": "no road",
        "bridges_h": "Bridges likely damaged",
        "basis": "Basis", "limits": "Limits",
        "limits_txt": "Satellite-derived and not verified on the ground. Radar cannot see steep slopes facing away from or towards the satellite; "
                      "clouds hide optical images. Damage = buildings on or within 20 m of mapped impact. People = buildings × 4.37 "
                      "(Nepal census 2021 household size). Roads/settlements are from OpenStreetMap before the event and may be incomplete.",
        "none": "None found.",
        "legend": "Map: Sentinel-2 after the flood. Orange = flood/debris impact, yellow = riverbed bare before (lower confidence), blue = new water, red lines = roads in impact, "
                  "✕ = bridge likely damaged, dots = settlements (red cut off, yellow partly cut, green connected).",
    },
    "ne": {
        "title": "बाढी स्थिति प्रतिवेदन", "area": "क्षेत्र", "event": "घटना (UTC)", "made": "तयार मिति (UTC)",
        "where": "बाढी कहाँ पुग्यो?", "what": "के के क्षति भयो?", "who": "को को सम्पर्कविहीन भए?",
        "impact": "उपत्यकाको {impact_ha} हेक्टर भूभागमा बाढी वा लेदो-गेग्रानको असर देखियो ({patches} वटा क्षेत्र); "
                  "{new_water_ha} हेक्टरमा नयाँ खुला पानी छ; {riverbed_lower_confidence_ha} हेक्टर घटनाअघि नै खाली रहेको नदी किनार हो (कम निश्चित)।",
        "decided": "नक्सामा देखाइएको असरको {share_decided_by_optical_pct}% भाग सफा आकाशको सेन्टिनेल-२ तस्बिरले पुष्टि गरेको हो; बाँकी सेन्टिनेल-१ राडारले।",
        "unassess": "क्षेत्रको {unassessable_pct_of_area}% भाग जाँच्न सकिएन (भिरालो पहाडमा राडारको छाया/ओभरले र बादल)।",
        "bld": "घर/भवन: <b>{buildings_likely_affected}</b> सम्भवतः प्रभावित (अनुमानित {people_est_in_likely_affected_buildings} जना), {buildings_possibly_affected} प्रभावित हुन सक्ने (नक्सामा भएका {buildings_total} मध्ये)।",
        "brg": "पुल: <b>{bridges_likely_damaged}</b> सम्भवतः क्षतिग्रस्त, {bridges_possibly_damaged} क्षति हुन सक्ने (नक्सामा भएका {bridges_total} मध्ये)।",
        "road": "सडक: {road_km_in_impact} किलोमिटर असर क्षेत्रभित्र।",
        "hf": "असर क्षेत्रभित्र वा नजिकका स्वास्थ्य संस्था: {health_facilities_affected} (नक्सामा भएका {health_facilities_total} मध्ये)।",
        "cut": "<b>{settlements_cut_off_vehicle}</b> वटा बस्तीको सबै सडक सम्पर्क टुटेको छ (अनुमानित <b>{people_est_cut_off_vehicle}</b> जना); "
               "थप {settlements_partly_cut_vehicle} वटाको केही सम्पर्क टुटेको छ। सडक सम्पर्क नभएका घरमा अनुमानित <b>{people_est_stranded_vehicle}</b> जना बस्छन्। पैदल (गोरेटो समेत): {settlements_cut_off_foot} वटा सम्पर्कविहीन।",
        "tbl": ["बस्ती", "घर", "सडक नभएका घर", "अनुमानित सम्पर्कविहीन मानिस", "स्वास्थ्य संस्थासम्म सडक दूरी (कि.मि.): पहिले → अहिले"],
        "unreach": "सडक छैन",
        "bridges_h": "सम्भवतः क्षतिग्रस्त पुलहरू",
        "basis": "आधार", "limits": "सीमाहरू",
        "limits_txt": "यो भू-उपग्रहबाट निकालिएको अनुमान हो, स्थलगत रूपमा पुष्टि गरिएको छैन। राडारले केही ठाडो भिरहरू देख्न सक्दैन; बादलले "
                      "अप्टिकल तस्बिर छोप्छ। क्षति = नक्साङ्कित असरमा वा २० मिटरभित्रका घर। मानिस = घर × ४.३७ (राष्ट्रिय जनगणना २०७८ को "
                      "औसत परिवार आकार)। सडक र बस्ती घटनाअघिको ओपनस्ट्रिटम्यापबाट लिइएका हुन्, अपूर्ण हुन सक्छन्।",
        "none": "भेटिएन।",
        "legend": "नक्सा: बाढीपछिको सेन्टिनेल-२ तस्बिर। सुन्तला = बाढी/लेदो असर, पहेँलो = पहिले नै खाली नदी किनार (कम निश्चित), नीलो = नयाँ पानी, रातो रेखा = असर क्षेत्रभित्रको सडक, "
                  "✕ = सम्भवतः क्षतिग्रस्त पुल, थोप्लाहरू = बस्ती (रातो सम्पर्कविहीन, पहेँलो आंशिक, हरियो जोडिएको)।",
    },
}

ATTRIB = ("Contains modified Copernicus Sentinel data 2026. Produced using Copernicus WorldDEM-30 © DLR e.V. 2010–2014 and "
          "© Airbus Defence and Space GmbH 2014–2018 provided under COPERNICUS by the European Union and ESA; all rights reserved. "
          "© OpenStreetMap contributors.")


def _fmt(s: str, d: dict, ne: bool) -> str:
    def rep(m):
        v = d.get(m.group(1))
        v = "—" if v is None else (f"{v:,}" if isinstance(v, int) and v >= 10000 else str(v))
        return v.translate(DEV) if ne else v
    return re.sub(r"\{(\w+)\}", rep, s)


def render(run_id: str, lang: str = "en") -> str:
    f = json.loads((RUNS_DIR / run_id / "facts.json").read_text(encoding="utf-8"))
    L = T[lang]
    ne = lang == "ne"
    d = {**f["impact"], **f["damage"], **f["access"]}
    n = (lambda x: str(x).translate(DEV)) if ne else str
    rows = []
    for s in (f.get("most_stranded_settlements") or f["cut_off_settlements"])[:10]:
        nm = (s.get("name_ne") or s["name"]) if ne else s["name"]
        b, a = s.get("health_km_before"), s.get("health_km_after")
        sh = s.get("share_of_buildings_cut_off")
        rows.append(f"<tr><td>{html.escape(str(nm))}</td><td>{n(s['buildings'])}</td><td>{n(round(sh * 100)) + '%' if sh is not None else '–'}</td><td>{n(s.get('people_est_stranded', s['people_est']))}</td>"
                    f"<td>{n(b) if b is not None else L['unreach']} → {n(a) if a is not None else L['unreach']}</td></tr>")
    table = (f"<table><tr>{''.join(f'<th>{h}</th>' for h in L['tbl'])}</tr>{''.join(rows)}</table>" if rows
             else f"<p>{L['none']}</p>")
    br = [b for b in f["damaged_bridges"] if b["status"] == "likely damaged"][:10]
    def bname(b):
        if ne and b.get("near_place") and b["name"].startswith("bridge near"):
            return f"{b.get('near_place_ne') or b['near_place']} नजिकको पुल ({n(b['near_km'])} कि.मि.)"
        return b["name"]
    br_txt = ", ".join(f"{html.escape(bname(b))} [{b['lat']}, {b['lon']}]" for b in br) or L["none"]
    s1 = ", ".join(sorted({s["post_time"] for s in f["inputs"]["sentinel1"]}))
    s2 = ", ".join(sorted({s["date"] for s in f["inputs"]["sentinel2"] if s["role"] == "post"})) or "—"
    bbox = ", ".join(str(v) for v in f["area"]["bbox"])
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{L['title']}</title>
<style>
@page {{ size: A4; margin: 12mm; }}
body {{ font: 11px/1.4 'Segoe UI', 'Noto Sans Devanagari', 'Nirmala UI', Arial, sans-serif; color:#111; max-width: 186mm; margin: auto; }}
h1 {{ font-size: 18px; margin: 0 0 2px; }} h2 {{ font-size: 13px; margin: 10px 0 3px; border-bottom: 2px solid #c8461a; }}
.meta {{ color:#444; font-size: 10px; }} table {{ border-collapse: collapse; width:100%; }}
td, th {{ border-bottom: 1px solid #ddd; padding: 2px 4px; text-align:left; }} th {{ background:#f3f3f3; }}
.foot {{ font-size: 8.5px; color:#555; margin-top: 8px; }} .warn {{ background:#fff4e5; padding:4px 6px; }}
</style></head><body>
<h1>WaterGuard — {L['title']}</h1>
<div class="meta">{L['area']}: {bbox} ({n(f['area']['area_km2'])} km²) · {L['event']}: {f['event_time_utc']} · {L['made']}: {f['generated_utc']} · run {f['run_id']}</div>
{'<img src="/runs/' + f['run_id'] + '/sitrep_map.png" style="width:100%;max-height:105mm;object-fit:contain;margin-top:6px">' if (RUNS_DIR / run_id / 'sitrep_map.png').exists() else ''}
<div class="meta">{L['legend']}</div>
<h2>1. {L['where']}</h2>
<p>{_fmt(L['impact'], d, ne)} {_fmt(L['decided'], d, ne)} {_fmt(L['unassess'], d, ne)}</p>
<h2>2. {L['what']}</h2>
<p>{_fmt(L['bld'], d, ne)}<br>{_fmt(L['brg'], d, ne)}<br>{_fmt(L['road'], d, ne)}<br>{_fmt(L['hf'], d, ne)}</p>
<p><b>{L['bridges_h']}:</b> {br_txt}</p>
<h2>3. {L['who']}</h2>
<p>{_fmt(L['cut'], d, ne)}</p>
{table}
<h2>{L['basis']}</h2>
<p class="meta">Sentinel-1 post-event: {s1}. Sentinel-2 post-event (cloud-free pixels): {s2}. Copernicus DEM GLO-30.
OpenStreetMap snapshot {f['inputs']['osm']['snapshot_time']} ({f['inputs']['osm']['features']} features, 0 edited after snapshot).</p>
<p class="warn"><b>{L['limits']}:</b> {L['limits_txt']}</p>
<div class="foot">{ATTRIB}<br>Educational prototype, not an operational tool.</div>
</body></html>"""


# ---------------------------------------------------------------- offline copilot (no LLM)
def offline_answer(tools, q: str, results: list, nepali: bool) -> str:
    """Keyword router over the same tools. Numbers are formatted straight from tool results."""
    ql = q.lower()
    n = (lambda x: str(x).translate(DEV)) if nepali else str

    def use(tool, **kw):
        r = getattr(tools, tool)(**kw)
        results.append({"tool": tool, "args": kw, "result": r})
        return r

    if any(k in ql for k in ("bridge", "पुल")):
        r = use("damaged_bridges")
        names = ", ".join(b["name"] for b in r["bridges"][:8] if b["status"] == "likely damaged")
        return (f"सम्भवतः क्षतिग्रस्त पुल: {n(r['count_likely_damaged'])}, क्षति हुन सक्ने: {n(r['count_possibly_damaged'])}। {names}"
                if nepali else f"Bridges likely damaged: {r['count_likely_damaged']}, possibly damaged: "
                               f"{r['count_possibly_damaged']}. {names}")
    if any(k in ql for k in ("health", "hospital", "स्वास्थ्य", "अस्पताल")):
        r = use("health_facilities")
        aff = ", ".join(f"{a['name']} ({a['status']})" for a in r["affected"]) or ("कुनै छैन" if nepali else "none")
        return (f"क्षेत्रमा स्वास्थ्य संस्था: {n(r['total_in_area'])}। असर क्षेत्रमा/नजिक: {aff}" if nepali
                else f"Health facilities in the area: {r['total_in_area']}. In or next to the impact zone: {aff}.")
    if any(k in ql for k in ("cut off", "cut-off", "isolated", "stranded", "सम्पर्क", "टुटे", "cut")):
        r = use("list_cut_off")
        top = r["cut_off_by_road"][:6]
        lines = [f"- {s['name']}: {n(s['buildings'])} " + ("घर, अनुमानित " if nepali else "buildings, est. ") +
                 f"{n(s['people_est'])}" + (" जना" if nepali else " people") for s in top]
        head = (f"सबै सडक सम्पर्क टुटेका बस्ती: {n(r['count_cut_off_by_road'])} (अनुमानित {n(r['estimated_people_cut_off_by_road'])} जना)।"
                if nepali else f"Settlements with no road link left: {r['count_cut_off_by_road']} "
                               f"(estimated {r['estimated_people_cut_off_by_road']} people).")
        return "\n".join([head] + lines)
    names = [x for x in tools.settlements["name"].dropna().tolist() + tools.settlements["name_ne"].dropna().tolist()
             if len(x) >= 3]
    hit = next((x for x in sorted(names, key=len, reverse=True) if x.lower() in ql), None)
    if hit:
        r = use("find_settlement", name=hit)
        if "error" not in r:
            return (f"{r['name']}: {n(r['buildings'])} घर, अनुमानित {n(r['people_est'])} जना। सडक स्थिति: {r.get('vehicle_status')}।"
                    if nepali else f"{r['name']}: {r['buildings']} buildings, est. {r['people_est']} people. "
                                   f"Road status: {r.get('vehicle_status')} ({r.get('status_meaning')}). " + _health_line(r))
    r = use("get_overview")
    d = r["damage"]
    a = r["access"]
    return (f"असर क्षेत्र {n(r['impact']['impact_ha'])} हेक्टर। सम्भवतः प्रभावित घर {n(d['buildings_likely_affected'])}, "
            f"सम्भवतः क्षतिग्रस्त पुल {n(d['bridges_likely_damaged'])}, सम्पर्क टुटेका बस्ती {n(a['settlements_cut_off_vehicle'])} "
            f"(अनुमानित {n(a['people_est_cut_off_vehicle'])} जना)।" if nepali else
            f"Impact: {r['impact']['impact_ha']} ha. Buildings likely affected: {d['buildings_likely_affected']}. "
            f"Bridges likely damaged: {d['bridges_likely_damaged']}. Settlements cut off by road: "
            f"{a['settlements_cut_off_vehicle']} (estimated {a['people_est_cut_off_vehicle']} people).")


def _health_line(r) -> str:
    b, a = r.get("vehicle_health_km_before"), r.get("vehicle_health_km_after")
    if b is None:
        return "No road route to a mapped health facility inside the analysed area, even before the flood."
    if a is None:
        return f"Road distance to the nearest health facility was {b} km before; there is no road route now."
    return f"Road distance to the nearest health facility: {b} km before, {a} km now."
