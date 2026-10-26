"""ElevenLabs takes (public/audio/VO_ELEVENLABS) -> public/audio/vo_el/k1..k12.wav for product_timeline.py.

The website takes do not line up one-to-one with the 12 narration blocks: K5 and K6 are two takes of
block 5, so K7..K10 are blocks 6..9, and K_11 reads blocks 10-12 in one go. K_11 is cut at the
silences between blocks. K13 and K14 (added later) read blocks 13 and 14; until they exist the
placeholder reads already in vo_el are kept. Every block is gain-matched to the same loudness (K_11 came out ~12 dB
quieter than the rest), and gets a short fade at both ends because some takes stop mid-decay.
"""
import re, subprocess
from pathlib import Path
import numpy as np

V = Path(__file__).resolve().parents[1]
SRC = V / "public/audio/VO_ELEVENLABS"
OUT = V / "public/audio/vo_el"
SR, LUFS = 48000, -16.0
# block -> (take, from s, to s)
MAP = {1: ("K1.mp3",), 2: ("K2.mp3",), 3: ("K3.mp3",), 4: ("K4.mp3",), 5: ("K5.mp3",),
       6: ("K7.mp3",), 7: ("K8.mp3",), 8: ("K9.mp3",), 9: ("K10.mp3",),
       10: ("K_11.mp3.mpeg", 0.0, 21.90), 11: ("K_11.mp3.mpeg", 21.90, 34.76), 12: ("K_11.mp3.mpeg", 34.76, None),
       13: ("K13.mp3",), 14: ("K14.mp3",)}


def load(p):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def lufs(x):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-f", "f32le", "-ac", "1", "-ar", str(SR), "-i", "-", "-af", "ebur128", "-f", "null", "-"],
                       input=x.tobytes(), capture_output=True)
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr.decode())[-1])


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    takes = {}
    for n, (name, *cut) in MAP.items():
        if not (SRC / name).exists():
            print(n, name, "missing: keeping", OUT / f"k{n}.wav")
            continue
        x = takes.setdefault(name, None)
        if x is None:
            x = takes[name] = load(SRC / name)
        if cut:
            a, b = cut
            x = x[int(a * SR): None if b is None else int(b * SR)]
        x = x.copy()
        x *= 10 ** ((LUFS - lufs(x)) / 20)
        f = int(0.03 * SR)
        x[:f] *= np.linspace(0, 1, f)
        x[-f:] *= np.linspace(1, 0, f)
        # K_11 needs ~+8 dB, which would push its peaks past 0 dBFS: a fast limiter catches those
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ac", "1", "-ar", str(SR), "-i", "-",
                        "-af", "alimiter=limit=0.89:attack=3:release=60:level=disabled", "-c:a", "pcm_s16le", str(OUT / f"k{n}.wav")],
                       input=x.astype(np.float32).tobytes(), check=True)
        print(n, name, f"{len(x) / SR:.1f}s", f"pre-limit peak {20 * np.log10(np.abs(x).max()):.1f} dB")
