"""Music bed + voiceover for the product film, timed from src/product/timeline.json -> public/audio/product_mix.wav.
Music: Mixkit (free licence). Silent Descent #871 under the hook; Tech House Vibes #130 builds under the
problem behind a low-pass sweep and its kick lands on "WaterGuard"; Motivating Mornings #33 takes over at the
inspector, beat-matched (both are 123 BPM), and its final stop-hit lands on "This is WaterGuard".
Both grooves are lengthened by repeating whole 8-bar phrases, never by stretching. Ducked under every block.
VO comes from public/audio/vo_product/s{n}.wav (written by product_timeline.py, Polly guide or ElevenLabs).
A cut of the film (short_timeline.py) is mixed the same way from its remapped timeline:
    MIX_TIMELINE=video/src/product/short_timeline.json MIX_OUT=short_mix.wav python video/scripts/product_mix.py"""
import json, os, subprocess, sys
from pathlib import Path
import numpy as np

V = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V / "scripts"))
SR = 48000
tl = json.load(open(os.environ.get("MIX_TIMELINE", V / "src/product/timeline.json")))
SC = {s["n"]: s for s in tl["scenes"]}
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
    hits = [x for x in SC[n]["words"] if "".join(c for c in x[2].lower() if c.isalnum()) == w]
    return hits[nth][0]


drop = word(2, "water") if 2 in SC else SC[min(SC, key=lambda k: SC[k]["start"] if k > 1 else 1e9)]["start"]
hit = word(12, "water")            # "This is WaterGuard"
P = 60 / 123.047                   # beat of both grooves
K130 = 15.81                       # Tech House: first full-kick downbeat after the 8-bar intro
BRK130 = K130 + 132 * P            # ... its breakdown after the main body
HIT33 = 91.25                      # Motivating Mornings: stop-hit at the end


def extend(x, at, beats, n):
    """repeat the `beats`-long phrase starting at track time `at` n extra times (downbeat to downbeat)"""
    s, L, f = int(at * SR), int(beats * P * SR), int(0.02 * SR)
    seg = x[s:s + L]
    out = [x[:s + L]]
    for _ in range(n):
        out.append(seg.copy())
    out.append(x[s + L:])
    for i in range(1, len(out)):           # 20 ms crossfades at the joins
        a, b = out[i - 1], out[i]
        b[:f] = a[-f:] * np.linspace(1, 0, f)[:, None] + b[:f] * np.linspace(0, 1, f)[:, None]
        out[i - 1] = a[:-f]
    return np.concatenate(out)


def sweep(x, f0, f1):
    """time-varying low-pass, cutoff f0 -> f1 Hz (exponential) across x: the DJ filter-open into the drop"""
    from scipy.signal import butter, sosfilt
    y, zi, H = np.zeros_like(x), None, 1024
    for i in range(0, len(x), H):
        fc = f0 * (f1 / f0) ** (i / len(x))
        sos = butter(2, min(fc, SR * 0.45), "low", fs=SR, output="sos")
        if zi is None:
            zi = np.zeros((sos.shape[0], 2, 2))
        y[i:i + H], zi = sosfilt(sos, x[i:i + H], axis=0, zi=zi)
    return y


a = load(V / "public/audio/mixkit_silent_descent_871.mp3")
b = load(V / "public/audio/mixkit_tech_house_vibes_130.mp3")
c = load(V / "public/audio/mixkit_motivating_mornings_33.mp3")
for x, sl in ((a, slice(SR * 40, SR * 80)), (b, slice(SR * 20, SR * 75)), (c, slice(SR * 15, SR * 75))):
    x *= 10 ** ((-16 - rms_db(x[sl])) / 20)
c_at = SC[8]["start"] - 1.5 if 8 in SC else drop + 60    # the inspector block
# Tech House: kick on "WaterGuard", breakdown arriving just before the inspector
n130 = max(0, round((c_at - drop - (BRK130 - K130)) / (32 * P)))
b = extend(b, K130 + 64 * P, 32, n130)
b_at = drop - K130
brk = drop + (BRK130 - K130) + n130 * 32 * P
nb = int(K130 * SR)
b[:nb] = sweep(b[:nb], 350, 16000)
# Motivating Mornings: stop-hit on "This is WaterGuard", on the same beat grid as the Tech House
c_at2 = hit - HIT33
d = ((c_at2 - drop) / P) % 1 * P
c_at2 -= d if d < P / 2 else d - P
n33 = 0
while c_at2 > brk + 8:                         # Tech House breakdown runs out first; too short: repeat an 8-bar phrase of its main groove
    n33 += 1
    c_at2 -= 32 * P
c = extend(c, 12.2 + 32 * P, 32, n33)
xf = max(c_at2, brk)                           # Tech House hands over across 4 bars from here
m = np.zeros((N, 2), np.float32)
ta = np.zeros((N, 2), np.float32); place(ta, a, 0)
tb = np.zeros((N, 2), np.float32); place(tb, b, b_at)
tc = np.zeros((N, 2), np.float32); place(tc, c, c_at2)
m += ta * env([(0, -3), (max(0.1, b_at), -2), (drop - 2, -10), (drop, -60), (END, -60)])[:, None]
m += tb * env([(0, -60), (max(0.1, b_at), -24), (drop - 0.05, -4), (drop, 0), (xf, 0), (xf + 16 * P, -60), (END, -60)])[:, None]
m += tc * env([(0, -60), (c_at2, -60), (c_at2 + 2, 0), (xf + 16 * P, 0), (END - 2, 0), (END, -60)])[:, None]
pts = [(0, 0.0)]
for s in tl["scenes"]:
    w0, w1 = s["words"][0][0], s["words"][-1][1]
    pts += [(w0 - 0.35, 0.0), (w0, -12.0), (w1, -12.0), (w1 + 0.6, 0.0)]
pts.append((END, 0.0))
m *= env(sorted(pts))[:, None]
m *= 10 ** ((-1.0 - 20 * np.log10(np.abs(m).max() + 1e-9)) / 20)
vo = np.zeros((N, 2), np.float32)
for s in tl["scenes"]:
    place(vo, load(V / f"public/audio/vo_product/s{s['n']}.wav"), s["start"])
vo *= 10 ** ((-3.0 - 20 * np.log10(np.abs(vo).max() + 1e-9)) / 20)
mix = m * 0.56 + vo
mix *= 0.98 / max(1e-9, np.abs(mix).max())
out = V / "public/audio" / os.environ.get("MIX_OUT", "product_mix.wav")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-", "-c:a", "pcm_s16le", str(out)],
               input=np.clip(mix, -1, 1).astype(np.float32).tobytes(), check=True)
print("wrote", out.name, f"{N / SR:.1f}s; drop {drop:.2f} (+{n130} phrases), breakdown {brk:.2f}, mornings from {c_at2:.2f} (+{n33}), hit {c_at2 + HIT33 + n33 * 32 * P:.2f} vs word {hit:.2f}")
