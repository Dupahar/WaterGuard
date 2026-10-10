"""Music bed + guide VO for the WaterGuard film, timed from src/timeline.json (same method as the
Tawi Twin film). Outputs to out/: music_bed.wav (ducked under narration), vo_guide.wav, mix.wav.
Music: Mixkit (free licence) - Silent Descent #871, Sci-Fi Score #726, Tapis #759."""
import json, subprocess
from pathlib import Path
import numpy as np

V = Path(__file__).resolve().parents[1]
SR = 48000
tl = json.load(open(V / "src/timeline.json"))
END = tl["end"]
N = int(END * SR)


def load(p):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)


def place(buf, clip, at, src_from=0.0):
    clip = clip[int(src_from * SR):]
    s = int(at * SR)
    if s < 0:
        clip, s = clip[-s:], 0
    e = min(N, s + len(clip))
    buf[s:e] += clip[: e - s]


def env(points):
    t = np.arange(N) / SR
    xs, ys = zip(*points)
    return 10 ** (np.interp(t, xs, ys) / 20)


def word(n, w, nth=0):
    hits = [x for x in tl["scenes"][n - 1]["words"] if "".join(c for c in x[2].lower() if c.isalnum()) == w]
    return hits[nth][0]


drop = word(2, "water")            # the title lands on the drop
a = load(V / "public/audio/mixkit_silent_descent_871.mp3")
b = load(V / "public/audio/mixkit_sci_fi_score_726.mp3")
c = load(V / "public/audio/mixkit_tapis_759.mp3")
for x, sl in ((a, slice(SR * 40, SR * 80)), (b, slice(SR * 20, SR * 80)), (c, slice(SR * 10, SR * 90))):
    x *= 10 ** ((-16 - rms_db(x[sl])) / 20)
B_DROP = 14.5
b_at = drop - B_DROP
c_at = tl["scenes"][6]["start"] - 1.0          # Tapis takes over at the copilot
m = np.zeros((N, 2), np.float32)
ta = np.zeros((N, 2), np.float32); place(ta, a, 0)
tb = np.zeros((N, 2), np.float32); place(tb, b, b_at)
tc = np.zeros((N, 2), np.float32); place(tc, c, c_at, src_from=2.6)
m += ta * env([(0, -6), (max(0.1, b_at), -6), (drop - 0.4, -14), (drop, -60), (END, -60)])[:, None]
m += tb * env([(0, -60), (max(0.1, b_at), -60), (b_at + 0.5, -10), (drop - 0.05, -6), (drop, 0), (c_at, 0), (c_at + 3, -60), (END, -60)])[:, None]
m += tc * env([(0, -60), (c_at, -60), (c_at + 3, 0), (END - 4, 0), (END, -60)])[:, None]
pts = [(0, 0.0)]
for s in tl["scenes"]:
    w0, w1 = s["words"][0][0], s["words"][-1][1]
    pts += [(w0 - 0.3, 0.0), (w0, -11.0), (w1, -11.0), (w1 + 0.35, 0.0)]
pts.append((END, 0.0))
m *= env(sorted(pts))[:, None]
m *= 10 ** ((-1.0 - 20 * np.log10(np.abs(m).max() + 1e-9)) / 20)
vo = np.zeros((N, 2), np.float32)
for s in tl["scenes"]:
    place(vo, load(V / f"public/audio/vo/s{s['n']}.wav"), s["start"])
vo *= 10 ** ((-3.0 - 20 * np.log10(np.abs(vo).max() + 1e-9)) / 20)


def save(x, name):
    out = V / "out" / name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-", "-c:a", "pcm_s16le", str(out)],
                   input=np.clip(x, -1, 1).astype(np.float32).tobytes(), check=True)
    print("wrote", name, f"{len(x) / SR:.2f}s")


save(m, "music_bed.wav")
save(vo, "vo_guide.wav")
mix = m * 0.55 + vo
save(mix * (0.98 / max(1e-9, np.abs(mix).max())), "mix.wav")
print("drop at", round(drop, 2), "sci-fi starts", round(b_at, 2), "tapis starts", round(c_at, 2))
