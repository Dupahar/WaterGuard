r"""Product-film voiceover -> src/product/timeline.json (every visual cue is a word time from here).

Same method as make_timeline.py: trim silence, cap inner pauses, faster-whisper word timestamps,
blocks laid out in ORDER with LEAD before the first, GAPS[n] before block n (room for visual beats), TAIL after.
Blocks 13-14 (how the agent looks, the stress test and AWS) were added later and play between 8 and 9; scenes
are written sorted by n, so every cue in the film still addresses a block by its number.
Run with the whisper venv:  ..\TawiTwin\.scratch\wvenv\Scripts\python -I video/scripts/product_timeline.py
"""
import json, os, subprocess, sys
from pathlib import Path
import numpy as np

V = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V / "scripts"))
import make_timeline   # noqa: E402
from make_timeline import fit, load, save, SR   # noqa: E402

VO = V / "public/audio/vo_product"
SRC = Path(os.environ.get("VO_SRC", VO))     # ElevenLabs read: VO_SRC=video/public/audio/vo_el (el_import.py)
make_timeline.PAUSE = float(os.environ.get("VO_PAUSE", make_timeline.PAUSE))   # inner-pause cap, s
OUT = V / "src/product/timeline.json"
LEAD, TAIL = 2.4, 5.5
GAPS = {2: 1.4, 3: 1.8, 4: 2.4, 5: 2.0, 6: 2.6, 7: 2.4, 8: 2.4, 13: 2.6, 15: 2.6, 14: 2.4, 9: 2.6, 10: 2.2, 11: 2.0, 12: 2.4}
ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 13, 15, 14, 9, 10, 11, 12]

if __name__ == "__main__":
    from faster_whisper import WhisperModel
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    t, scenes = LEAD, []
    for i, n in enumerate(ORDER):
        y = fit(load(next(p for p in (SRC / f"k{n}.wav", SRC / f"k{n}.mp3") if p.exists())))
        wav = VO / f"s{n}.wav"
        save(y, wav)
        dur = len(y) / SR
        y16 = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                                           capture_output=True, check=True).stdout, np.float32).copy()
        segs, _ = model.transcribe(y16, word_timestamps=True, language="en")
        if i:
            t += GAPS.get(n, 0)
        words = [[round(t + w.start, 2), round(t + w.end, 2), w.word.strip()] for s in segs for w in s.words]
        scenes.append({"n": n, "start": round(t, 2), "dur": round(dur, 2), "words": words})
        print(n, round(t, 2), round(dur, 2), " ".join(w[2] for w in words))
        t += dur
    OUT.parent.mkdir(parents=True, exist_ok=True)
    scenes.sort(key=lambda sc: sc["n"])
    OUT.write_text(json.dumps({"end": round(t + TAIL, 2), "scenes": scenes}, indent=1), encoding="utf-8")
    print("end", round(t + TAIL, 2))
