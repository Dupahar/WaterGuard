"""A shorter cut of the product film -> src/product/short.json (read by src/product/Short.tsx).

The cut replays chosen narration blocks of the full film (src/product/timeline.json): blocks that follow
each other in the film become one continuous segment; segments cross-fade. Times stay those of the
full film, so every visual cue still lands on its word. Also writes short_timeline.json: the kept
blocks on the cut's own clock, for the music and voice mix. Run after product_timeline.py; then mix with
MIX_TIMELINE=video/src/product/short_timeline.json MIX_OUT=short_mix.wav python video/scripts/product_mix.py.
    python video/scripts/short_timeline.py 1 3 4 5 8 15 14 12
"""
import json
import sys
from pathlib import Path

V = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V / "scripts"))
from product_timeline import ORDER   # noqa: E402

PRE, POST, XFADE = 1.3, 1.2, 0.8

if __name__ == "__main__":
    tl = json.loads((V / "src/product/timeline.json").read_text(encoding="utf-8"))
    sc = {s["n"]: s for s in tl["scenes"]}
    keep = [int(x) for x in sys.argv[1:]]
    blocks = [n for n in ORDER if n in keep]
    runs = []                                  # blocks adjacent in the film play as one segment
    for n in blocks:
        if runs and ORDER.index(n) == ORDER.index(runs[-1][-1]) + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    segs, out = [], 0.0
    for r in runs:
        a = 0.0 if r[0] == ORDER[0] else sc[r[0]]["start"] - PRE
        b = tl["end"] if r[-1] == ORDER[-1] else sc[r[-1]]["start"] + sc[r[-1]]["dur"] + POST
        segs.append({"blocks": r, "from": round(a, 2), "to": round(b, 2), "out": round(out, 2)})
        out += b - a - XFADE
    end = round(out + XFADE, 2)
    at = lambda n: next(s["out"] + sc[n]["start"] - s["from"] for s in segs if n in s["blocks"])
    res = {"blocks": blocks, "xfade": XFADE, "segments": segs, "end": end,
           "labels": {str(n): f"{i + 1:02d}" for i, n in enumerate(blocks)},
           "marks": [{"n": n, "at": round(at(n), 2)} for n in blocks]}
    (V / "src/product/short.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    # the same blocks on the cut's clock, for product_mix.py (MIX_TIMELINE)
    shift = {n: at(n) - sc[n]["start"] for n in blocks}
    remap = [{**sc[n], "start": round(sc[n]["start"] + shift[n], 2),
              "words": [[round(w0 + shift[n], 2), round(w1 + shift[n], 2), w] for w0, w1, w in sc[n]["words"]]} for n in blocks]
    (V / "src/product/short_timeline.json").write_text(json.dumps({"end": end, "scenes": sorted(remap, key=lambda x: x["n"])}, indent=1),
                                                      encoding="utf-8")
    for s in segs:
        print(f"{s['out']:7.2f}  film {s['from']:7.2f}-{s['to']:7.2f}  blocks {s['blocks']}")
    print(f"end {end:.2f} s = {int(end // 60)}:{int(end % 60):02d}")
