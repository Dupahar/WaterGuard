"""Captions (out/captions.srt) + VO beat sheet (../docs/video/beats.md) from src/timeline.json."""
import json, re
from pathlib import Path

V = Path(__file__).resolve().parents[1]
tl = json.load(open(V / "src/timeline.json"))
srt_t = lambda s: f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d},{int(round(s % 1 * 1000)) % 1000:03d}"
ts = lambda s: f"{int(s // 60)}:{s % 60:05.2f}"
FIX = [("Bodhikoshi", "Bhote Koshi"), ("Botikoshi", "Bhote Koshi"), ("Sia Prubesi", "Syapru Besi"), ("Shabrubensi", "Syabru Bensi"), ("co -pilot", "copilot"), ("It treats", "It reads"), ("open street map", "OpenStreetMap"), ("km off road", "km of road"), ("one -page", "one-page"), ("washed out", "washed-out"), ("water guard", "WaterGuard"), ("Water guard", "WaterGuard"), ("Water Guard", "WaterGuard"), ("Sentinel -1", "Sentinel-1"),
       ("Sentinel -2", "Sentinel-2"), ("sentinels do", "Sentinel-2"), ("Siapro Basie", "Syapru Besi"), ("the mark from", "the map from"),
       ("Siabru Benzi", "Syabru Bensi"), ("washed -out", "washed-out"), ("flat part", "flood path"), ("0 .92", "0.92"), ("0 .89", "0.89"),
       ("Elevation Model", "elevation model"), ("one page", "one-page"), ("where the sky", "Where the sky")]
srt, k = [], 1
md = ["# WaterGuard film: voiceover beat sheet", "",
      f"Picture length **{ts(tl['end'])}**. Every visual hit is cued to these word times. To use your own voice: record each block",
      "(text in `vo_blocks.txt`), save as `video/public/audio/vo/k1.mp3 … k9.mp3`, then run `make_timeline.py`, `mix.py`, render.", ""]
for s in tl["scenes"]:
    words = s["words"]
    chunk, start = [], None
    for i, w in enumerate(words):
        start = w[0] if start is None else start
        chunk.append(w)
        nxt = words[i + 1][2] if i + 1 < len(words) else ""
        glued = nxt.startswith(".") or w[2] in ("Siapro", "Siabru", "Sentinel", "Water", "water", "Sia", "co", "open", "street")   # keep "0 .92", names together
        if re.search(r"[.?!]$", w[2]) or (len(chunk) >= 10 and not glued):
            srt += [str(k), f"{srt_t(start)} --> {srt_t(chunk[-1][1] + 0.15)}", " ".join(x[2] for x in chunk), ""]
            k += 1; chunk, start = [], None
    if chunk:
        srt += [str(k), f"{srt_t(start)} --> {srt_t(chunk[-1][1] + 0.15)}", " ".join(x[2] for x in chunk), ""]; k += 1
    md += [f"- **Block {s['n']}** IN {ts(s['start'])} → OUT {ts(words[-1][1])} ({words[-1][1] - s['start']:.1f} s)"]
out = "\n".join(srt)
for a, b in FIX:
    out = out.replace(a, b)
(V / "out/captions.srt").write_text(out, encoding="utf-8")
(V.parent / "docs/video/beats.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print(k - 1, "captions")
