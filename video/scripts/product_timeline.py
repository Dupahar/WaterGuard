"""Product-film voiceover -> src/product/timeline.json (every visual cue is a word time from here).

Same method as make_timeline.py: trim silence, cap inner pauses, faster-whisper word timestamps,
blocks laid out with LEAD before the first, GAPS[n] before block n (room for visual beats), TAIL after.
Run with the whisper venv:  ..\TawiTwin\.scratch\wvenv\Scripts\python -I video/scripts/product_timeline.py
"""
import json, os, subprocess, sys
from pathlib import Path
import numpy as np

V = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V / "scripts"))
from make_timeline import fit, load, save, SR   # noqa: E402

VO = V / "public/audio/vo_product"
SRC = Path(os.environ.get("VO_SRC", VO))
OUT = V / "src/product/timeline.json"
LEAD, TAIL = 2.4, 5.5
GAPS = {2: 1.4, 3: 1.8, 4: 2.4, 5: 2.0, 6: 2.6, 7: 2.4, 8: 2.4, 9: 2.4, 10: 2.2, 11: 2.0, 12: 2.4}
N = 12

if __name__ == "__main__":
    from faster_whisper import WhisperModel
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    t, scenes = LEAD, []
    for n in range(1, N + 1):
        y = fit(load(SRC / f"k{n}.mp3"))
        wav = VO / f"s{n}.wav"
        save(y, wav)
        dur = len(y) / SR
        y16 = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                                           capture_output=True, check=True).stdout, np.float32).copy()
        segs, _ = model.transcribe(y16, word_timestamps=True, language="en")
        if n > 1:
            t += GAPS.get(n, 0)
        words = [[round(t + w.start, 2), round(t + w.end, 2), w.word.strip()] for s in segs for w in s.words]
        scenes.append({"n": n, "start": round(t, 2), "dur": round(dur, 2), "words": words})
        print(n, round(t, 2), round(dur, 2), " ".join(w[2] for w in words))
        t += dur
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"end": round(t + TAIL, 2), "scenes": scenes}, indent=1), encoding="utf-8")
    print("end", round(t + TAIL, 2))
