"""Voiceover -> src/timeline.json (every visual cue in the film is a word time from here).

For each block public/audio/vo/k{n}.mp3: trim head/tail silence, cap inner pauses at PAUSE s
-> public/audio/vo/s{n}.wav; faster-whisper word timestamps; blocks laid out with LEAD before the
first, GAPS[n] between blocks (room for visual beats) and TAIL after the last.
Run with the whisper venv:  ..\TawiTwin\.scratch\wvenv\Scripts\python -I video/scripts/make_timeline.py
"""
import json, subprocess
from pathlib import Path
import numpy as np

V = Path(__file__).resolve().parents[1]
import os
VO = V / "public/audio/vo"
SRC = Path(os.environ.get("VO_SRC", VO / "Elevenlabs"))   # where k1..k9.mp3 are (Polly guide: vo/polly)
TEMPO = float(os.environ.get("VO_TEMPO", "1.0"))
SR = 48000
PAUSE, FLOOR_DB = 0.38, -40
LEAD, TAIL = 3.2, 6.5
GAPS = {2: 1.6, 3: 1.2, 4: 1.0, 5: 1.0, 6: 1.0, 7: 1.4, 8: 1.4, 9: 1.6}   # silence before block n


def load(p):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def save(x, p):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ac", "1", "-ar", str(SR), "-i", "-", "-c:a", "pcm_s16le", str(p)],
                   input=x.astype(np.float32).tobytes(), check=True)


def fit(x):
    hop = int(0.01 * SR)
    db = 20 * np.log10(np.sqrt(np.convolve(x ** 2, np.ones(hop) / hop, "same"))[::hop] + 1e-9)
    loud = db > FLOOR_DB
    idx = np.flatnonzero(loud)
    a, b = idx[0], idx[-1] + 1
    out, i, fade = [], a, int(0.01 * SR)
    while i < b:
        j = i
        while j < b and loud[j] == loud[i]:
            j += 1
        seg = x[i * hop:j * hop]
        if not loud[i] and (j - i) * 0.01 > PAUSE:
            k = int(PAUSE / 2 * SR)
            seg = np.concatenate([seg[:k], seg[-k:]])
            seg[k - fade:k] *= np.linspace(1, 0, fade)
            seg[k:k + fade] *= np.linspace(0, 1, fade)
        out.append(seg)
        i = j
    pad = np.zeros(int(0.05 * SR), np.float32)
    return np.concatenate([pad, np.concatenate(out), pad])


if __name__ == "__main__":
    from faster_whisper import WhisperModel
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    t, scenes = LEAD, []
    for n in range(1, 10):
        y = fit(load(SRC / f"k{n}.mp3"))
        wav = VO / f"s{n}.wav"
        save(y, wav)
        if TEMPO != 1.0:   # gentle speed-up without pitch change
            tmp = VO / f"s{n}_t.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-af", f"atempo={TEMPO}", str(tmp)], check=True)
            tmp.replace(wav)
            y = load(wav)
        dur = len(y) / SR
        y16 = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                                           capture_output=True, check=True).stdout, np.float32).copy()
        segs, _ = model.transcribe(y16, word_timestamps=True, language="en")
        words = [[round(t + w.start, 2), round(t + w.end, 2), w.word.strip()] for s in segs for w in s.words]
        t = t + GAPS.get(n, 0) if n > 1 else t
        if n > 1:   # shift for the gap applied before this block
            words = [[a + GAPS.get(n, 0), b + GAPS.get(n, 0), w] for a, b, w in words]
        scenes.append({"n": n, "start": round(t, 2), "dur": round(dur, 2), "words": words})
        print(n, round(t, 2), round(dur, 2), " ".join(w[2] for w in words))
        t += dur
    tl = {"end": round(t + TAIL, 2), "scenes": scenes}
    (V / "src/timeline.json").write_text(json.dumps(tl, indent=1), encoding="utf-8")
    print("end", tl["end"])
