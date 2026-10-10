"""Signal-processing primitives: oscillators, envelopes, filters, space, dynamics, I/O.

All signals are float64 numpy arrays at SR. Stereo is shape (2, n).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from scipy import signal as sps
from scipy.ndimage import maximum_filter1d

SR = 44100


def rng(seed: int | None = None) -> np.random.Generator:
    return np.random.default_rng(seed)


def secs(n: int) -> float:
    return n / SR


def samples(t: float) -> int:
    return int(round(t * SR))


# ----------------------------------------------------------------- oscillators
def _phase(freq, n: int, phase0: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    dt = f / SR
    ph = (phase0 + np.concatenate(([0.0], np.cumsum(dt[:-1])))) % 1.0
    return ph, dt


def _polyblep(ph: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """PolyBLEP residual that removes the aliasing step of a naive saw/square."""
    out = np.zeros_like(ph)
    lo = ph < dt
    t = ph[lo] / dt[lo]
    out[lo] = t + t - t * t - 1.0
    hi = ph > 1.0 - dt
    t = (ph[hi] - 1.0) / dt[hi]
    out[hi] = t * t + t + t + 1.0
    return out


def saw(freq, n: int, phase0: float = 0.0) -> np.ndarray:
    ph, dt = _phase(freq, n, phase0)
    return 2.0 * ph - 1.0 - _polyblep(ph, dt)


def square(freq, n: int, phase0: float = 0.0, width: float = 0.5) -> np.ndarray:
    ph, dt = _phase(freq, n, phase0)
    sq = np.where(ph < width, 1.0, -1.0)
    sq += _polyblep(ph, dt)
    sq -= _polyblep((ph + 1.0 - width) % 1.0, dt)
    return sq


def sine(freq, n: int, phase0: float = 0.0) -> np.ndarray:
    ph, _ = _phase(freq, n, phase0)
    return np.sin(2 * np.pi * ph)


def triangle(freq, n: int, phase0: float = 0.0) -> np.ndarray:
    ph, _ = _phase(freq, n, phase0)
    return 4.0 * np.abs(ph - 0.5) - 1.0


def noise(n: int, seed: int | None = None) -> np.ndarray:
    return rng(seed).uniform(-1.0, 1.0, n)


# ------------------------------------------------------------------- envelopes
def adsr(n: int, a: float = 0.005, d: float = 0.1, s: float = 0.8, r: float = 0.05,
         gate: int | None = None) -> np.ndarray:
    """Linear-attack, exponential decay/release envelope. `gate` = samples held."""
    gate = n if gate is None else min(gate, n)
    env = np.zeros(n)
    na, nd = max(1, samples(a)), max(1, samples(d))
    t = np.arange(n)
    att = t < na
    env[att] = t[att] / na
    dec = ~att
    env[dec] = s + (1 - s) * np.exp(-(t[dec] - na) / nd * 4.0)
    if gate < n:
        level = env[gate - 1] if gate > 0 else 0.0
        rel = t >= gate
        env[rel] = level * np.exp(-(t[rel] - gate) / max(1, samples(r)) * 5.0)
    return env


def exp_decay(n: int, tau: float) -> np.ndarray:
    return np.exp(-np.arange(n) / (tau * SR))


def fade(x: np.ndarray, fade_in: float = 0.003, fade_out: float = 0.01) -> np.ndarray:
    n = x.shape[-1]
    env = np.ones(n)
    a, b = min(n, samples(fade_in)), min(n, samples(fade_out))
    if a:
        env[:a] = np.linspace(0, 1, a)
    if b:
        env[n - b:] *= np.linspace(1, 0, b)
    return x * env


# --------------------------------------------------------------------- filters
def biquad(kind: str, f: float, q: float = 0.707, gain_db: float = 0.0) -> np.ndarray:
    """RBJ cookbook biquad as a (1, 6) SOS row."""
    f = float(np.clip(f, 10.0, SR * 0.49))
    w = 2 * np.pi * f / SR
    cw, sw = np.cos(w), np.sin(w)
    alpha = sw / (2 * q)
    A = 10 ** (gain_db / 40)
    if kind == "lowpass":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "bandpass":  # constant 0 dB peak gain
        b = [alpha, 0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind in ("lowshelf", "highshelf"):
        sq = 2 * np.sqrt(A) * alpha
        if kind == "lowshelf":
            b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw),
                 A * ((A + 1) - (A - 1) * cw - sq)]
            a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw),
                 A * ((A + 1) + (A - 1) * cw - sq)]
            a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    else:
        raise ValueError(kind)
    b, a = np.array(b) / a[0], np.array(a) / a[0]
    return np.concatenate([b, a])[None, :]


def filt(x: np.ndarray, kind: str, f: float, q: float = 0.707, gain_db: float = 0.0,
         order: int = 1) -> np.ndarray:
    """Static filter; `order` cascades the biquad (order=2 -> 24 dB/oct)."""
    sos = np.vstack([biquad(kind, f, q, gain_db)] * order)
    return sps.sosfilt(sos, x, axis=-1)


def sweep(x: np.ndarray, cutoff, kind: str = "lowpass", q: float = 0.707, block: int = 128,
          order: int = 2) -> np.ndarray:
    """Time-varying filter: coefficients follow `cutoff` (Hz, per-sample array or scalar).

    Coefficients update every `block` samples and the filter state carries across,
    which is how a synth's filter envelope behaves.
    """
    x = np.atleast_2d(x)
    n = x.shape[-1]
    cut = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), (n,))
    out = np.empty_like(x)
    zi = np.zeros((order, x.shape[0], 2))
    for s in range(0, n, block):
        e = min(n, s + block)
        sos = np.vstack([biquad(kind, cut[(s + e) // 2], q)] * order)
        out[:, s:e], zi = sps.sosfilt(sos, x[:, s:e], axis=-1, zi=zi)
    return out if out.shape[0] > 1 else out[0]


# ---------------------------------------------------------------- stereo / mix
def pan(x: np.ndarray, p: float = 0.0) -> np.ndarray:
    """Equal-power pan of a mono signal; p in [-1, 1]."""
    th = (p + 1) * np.pi / 4
    return np.vstack([x * np.cos(th), x * np.sin(th)]) * np.sqrt(2)


def to_stereo(x: np.ndarray) -> np.ndarray:
    return x if x.ndim == 2 else np.vstack([x, x])


def width(x: np.ndarray, w: float) -> np.ndarray:
    """Mid/side width: 0 mono, 1 unchanged, >1 wider."""
    m, s = (x[0] + x[1]) / 2, (x[0] - x[1]) / 2 * w
    return np.vstack([m + s, m - s])


def mono_below(x: np.ndarray, f: float = 120.0) -> np.ndarray:
    """Keep the low end mono (sub energy centred, like a real mastered drop)."""
    m, s = (x[0] + x[1]) / 2, (x[0] - x[1]) / 2
    s = filt(s, "highpass", f, order=2)
    return np.vstack([m + s, m - s])


def db(x: float) -> float:
    return 10 ** (x / 20)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)) + 1e-20))


def saturate(x: np.ndarray, drive: float = 1.5) -> np.ndarray:
    return np.tanh(x * drive) / np.tanh(drive)


class Bus:
    """A stereo buffer that instruments are summed into at sample offsets."""

    def __init__(self, n: int):
        self.buf = np.zeros((2, n))

    @property
    def n(self) -> int:
        return self.buf.shape[1]

    def add(self, x: np.ndarray, start: int, gain: float = 1.0, p: float = 0.0):
        x = pan(x, p) if x.ndim == 1 else x
        if start >= self.n or x.shape[1] == 0:
            return
        if start < 0:
            x, start = x[:, -start:], 0
        e = min(self.n, start + x.shape[1])
        self.buf[:, start:e] += gain * x[:, : e - start]


# ----------------------------------------------------------------------- space
def reverb_ir(seconds: float = 2.4, predelay: float = 0.02, bright: float = 6000.0,
              dark: float = 1800.0, seed: int = 7) -> np.ndarray:
    """Stereo plate-ish impulse response: decorrelated noise whose highs die faster."""
    n = samples(seconds)
    t = np.arange(n) / SR
    out = []
    for ch in range(2):
        nz = noise(n, seed + ch)
        hi = filt(nz, "lowpass", bright) * np.exp(-t * 6.9 / (seconds * 0.45))
        lo = filt(nz, "lowpass", dark) * np.exp(-t * 6.9 / seconds)
        ir = hi + 1.2 * lo
        ir[: samples(0.004)] *= np.linspace(0, 1, samples(0.004))
        out.append(np.concatenate([np.zeros(samples(predelay)), ir]))
    ir = np.vstack(out)
    return ir / np.sqrt(np.sum(ir ** 2) / 2)


def convolve(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    x = to_stereo(x)
    wet = np.vstack([sps.fftconvolve(x[c], ir[c])[: x.shape[1]] for c in range(2)])
    return wet


def reverb(x: np.ndarray, ir: np.ndarray, hp: float = 250.0) -> np.ndarray:
    """100% wet return; the high-pass keeps the low end out of the tail."""
    return filt(convolve(x, ir), "highpass", hp)


def delay(x: np.ndarray, t: float, feedback: float = 0.45, repeats: int = 6,
          pingpong: bool = True, tone: float = 4500.0) -> np.ndarray:
    """Tempo-synced (pass t in seconds) ping-pong delay, 100% wet."""
    x = to_stereo(x)
    n = x.shape[1]
    out = np.zeros_like(x)
    mono = (x[0] + x[1]) / 2
    d = samples(t)
    tap = mono
    for k in range(1, repeats + 1):
        tap = filt(tap, "lowpass", tone) * feedback
        off = k * d
        if off >= n:
            break
        ch = (k % 2) if pingpong else None
        if ch is None:
            out[:, off:] += tap[: n - off]
        else:
            out[ch, off:] += tap[: n - off]
            out[1 - ch, off:] += 0.25 * tap[: n - off]
    return out


# -------------------------------------------------------------------- dynamics
def sidechain_curve(n: int, hits: list[int], depth: float = 0.8, release: float = 0.22,
                    attack: float = 0.004, shape: float = 2.0) -> np.ndarray:
    """Gain curve ducked at every kick (sample indices) — the future bass pump."""
    g = np.ones(n)
    rl, al = max(1, samples(release)), max(1, samples(attack))
    k = np.arange(rl)
    duck = 1 - depth * (1 - (k / rl) ** (1 / shape))
    a = np.linspace(1, 1 - depth, al, endpoint=False)
    for h in hits:
        s0 = h - al
        if s0 >= 0:
            e = min(n, h)
            g[s0:e] = np.minimum(g[s0:e], a[: e - s0])
        if h < n:
            e = min(n, h + rl)
            g[h:e] = np.minimum(g[h:e], duck[: e - h])
    return g


def _envelope(x: np.ndarray, hop: int) -> np.ndarray:
    mono = np.max(np.abs(to_stereo(x)), axis=0)
    pad = (-len(mono)) % hop
    mono = np.pad(mono, (0, pad))
    return mono.reshape(-1, hop).max(axis=1)


def compress(x: np.ndarray, threshold_db: float = -18.0, ratio: float = 3.0, attack: float = 0.01,
             release: float = 0.15, makeup_db: float = 0.0, knee_db: float = 6.0) -> np.ndarray:
    """Feed-forward peak compressor with a soft knee, computed on 2 ms hops."""
    hop = 88
    env = _envelope(x, hop)
    lvl = 20 * np.log10(env + 1e-9)
    over = lvl - threshold_db
    gr = np.where(over <= -knee_db / 2, 0.0,
                  np.where(over >= knee_db / 2, over * (1 - 1 / ratio),
                           (1 - 1 / ratio) * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    ca = np.exp(-hop / (attack * SR))
    cr = np.exp(-hop / (release * SR))
    sm = np.empty_like(gr)
    prev = 0.0
    for i, v in enumerate(gr):
        c = ca if v > prev else cr
        prev = c * prev + (1 - c) * v
        sm[i] = prev
    gain = 10 ** ((makeup_db - sm) / 20)
    g = np.interp(np.arange(x.shape[-1]), np.arange(len(gain)) * hop + hop / 2, gain)
    return x * g


def integrated_lufs(x: np.ndarray) -> float:
    """ITU-R BS.1770-4 integrated loudness: K-weighting, 400 ms blocks (75% overlap),
    -70 LUFS absolute gate, then a -10 LU relative gate."""
    x = to_stereo(x)
    # K-weighting as RBJ biquads: +4 dB high shelf at 1.5 kHz, 38 Hz RLB high-pass.
    k = np.vstack([biquad("highshelf", 1500.0, 1 / np.sqrt(2), 4.0), biquad("highpass", 38.0, 0.5)])
    y = sps.sosfilt(k, x, axis=-1)
    blk, hop = samples(0.4), samples(0.1)
    if y.shape[1] < blk:
        return -70.0
    sq = np.cumsum(np.concatenate([np.zeros((2, 1)), y ** 2], axis=1), axis=1)
    starts = np.arange(0, y.shape[1] - blk + 1, hop)
    ms = ((sq[:, starts + blk] - sq[:, starts]) / blk).sum(axis=0)
    lk = -0.691 + 10 * np.log10(ms + 1e-20)
    gated = ms[lk > -70.0]
    if not len(gated):
        return -70.0
    rel = -0.691 + 10 * np.log10(gated.mean()) - 10.0
    final = ms[lk > max(-70.0, rel)]
    return float(-0.691 + 10 * np.log10(final.mean()))


def master_to(x: np.ndarray, lufs: float = -9.0, ceiling_db: float = -1.5, passes: int = 3) -> np.ndarray:
    """Bring a mix to an integrated loudness target under a true-peak ceiling.

    Gain then limit, re-measured a few times because limiting itself costs loudness.
    """
    y = to_stereo(x)
    for _ in range(passes):
        g = lufs - integrated_lufs(y)
        if abs(g) < 0.1:
            break
        y = limit(y * db(g), ceiling_db)
    return y


def true_peak(x: np.ndarray, oversample: int = 4) -> float:
    """Inter-sample (true) peak, linear, via polyphase oversampling as in ITU-R BS.1770."""
    x = to_stereo(x)
    return float(max(np.max(np.abs(sps.resample_poly(c, oversample, 1))) for c in x))


def limit(x: np.ndarray, ceiling_db: float = -1.0, release: float = 0.08,
          lookahead: float = 0.004) -> np.ndarray:
    """True-peak-aware look-ahead brickwall limiter.

    Gain is computed from a 4x-oversampled envelope so inter-sample overs (which
    become real clipping in an MP3 decoder or DAC) are caught, then a final trim
    guarantees the true-peak ceiling.
    """
    ceil = db(ceiling_db)
    x = to_stereo(x)
    hop = 32
    os = np.vstack([sps.resample_poly(c, 4, 1)[: 4 * x.shape[1]] for c in x])
    env = _envelope(os, hop * 4)[: -(-x.shape[1] // hop)]
    la = max(1, int(lookahead * SR / hop))
    # Peak over the next `la` hops (and the current one), so gain drops before the peak.
    env = maximum_filter1d(env, size=la + 1, origin=-((la + 1) // 2), mode="nearest")
    target = np.minimum(1.0, ceil / (env + 1e-12))
    cr = np.exp(-hop / (release * SR))
    sm = np.empty_like(target)
    prev = 1.0
    for i, v in enumerate(target):
        prev = v if v < prev else cr * prev + (1 - cr) * v
        sm[i] = prev
    g = np.interp(np.arange(x.shape[1]), np.arange(len(sm)) * hop, sm)
    y = x * g
    tp = true_peak(y)
    if tp > ceil:  # residual overs from gain interpolation: trim the whole thing
        y *= ceil / tp
    return y


# ------------------------------------------------------------------------- I/O
def write_wav(path: str | Path, x: np.ndarray, bits: int = 24, seed: int = 0) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    x = to_stereo(np.asarray(x, dtype=np.float64))
    full = 2 ** (bits - 1) - 1
    tpdf = (rng(seed).uniform(-0.5, 0.5, x.shape) + rng(seed + 1).uniform(-0.5, 0.5, x.shape))
    q = np.clip(np.round(x * full + tpdf), -full - 1, full).astype(np.int32)
    inter = q.T.reshape(-1)
    if bits == 16:
        raw = inter.astype("<i2").tobytes()
    elif bits == 24:
        b = inter.astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3]
        raw = b.tobytes()
    else:
        raise ValueError("bits must be 16 or 24")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(bits // 8)
        w.setframerate(SR)
        w.writeframes(raw)
    return path


def require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is required (apt install ffmpeg / brew install ffmpeg)")
    return exe


def read_audio(path: str | Path, sr: int = SR) -> np.ndarray:
    """Decode any format ffmpeg understands to float64 stereo at `sr`."""
    cmd = [require_ffmpeg(), "-v", "error", "-i", str(path), "-f", "f32le", "-acodec", "pcm_f32le",
           "-ac", "2", "-ar", str(sr), "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    x = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    return x.reshape(-1, 2).T.copy()


def ffmpeg_filter(x: np.ndarray, afilter: str) -> np.ndarray:
    """Run a stereo buffer through an ffmpeg audio filter chain (e.g. rubberband)."""
    x = to_stereo(x)
    cmd = [require_ffmpeg(), "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
           "-af", afilter, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"]
    raw = subprocess.run(cmd, input=x.T.astype("<f4").tobytes(), check=True, capture_output=True).stdout
    y = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    return y.reshape(-1, 2).T.copy()


def pitch_shift(x: np.ndarray, semitones: float) -> np.ndarray:
    """Formant-aware, duration-preserving pitch shift via ffmpeg's rubberband filter."""
    if abs(semitones) < 1e-6:
        return x
    ratio = 2 ** (semitones / 12)
    return ffmpeg_filter(x, f"rubberband=pitch={ratio:.6f}:formant=preserved:pitchq=quality")


def encode(wav: str | Path, out: str | Path, lufs: float | None = None, true_peak: float = -1.5,
           title: str = "", artist: str = "", bitrate: str = "320k") -> Path:
    """Encode to MP3 (or AAC for other suffixes) with tags.

    With `lufs`, ffmpeg's two-pass EBU R128 normalisation is applied first; leave it None
    when the WAV is already mastered (see `master_to`), which keeps the limiter's
    true-peak headroom intact instead of letting linear gain push peaks up.
    """
    ff = require_ffmpeg()
    out = Path(out)
    af: list[str] = []
    if lufs is not None:
        measure = subprocess.run(
            [ff, "-hide_banner", "-i", str(wav), "-af",
             f"loudnorm=I={lufs}:TP={true_peak}:LRA=7:print_format=json", "-f", "null", "-"],
            check=True, capture_output=True, text=True).stderr
        stats = json.loads(measure[measure.rindex("{"): measure.rindex("}") + 1])
        af = ["-af", (f"loudnorm=I={lufs}:TP={true_peak}:LRA=7:measured_I={stats['input_i']}:"
                      f"measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}:"
                      f"measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true")]
    meta = []
    if title:
        meta += ["-metadata", f"title={title}"]
    if artist:
        meta += ["-metadata", f"artist={artist}"]
    codec = ["-c:a", "libmp3lame", "-b:a", bitrate] if out.suffix == ".mp3" else ["-c:a", "aac", "-b:a", "256k"]
    subprocess.run([ff, "-v", "error", "-y", "-i", str(wav), *af, "-ar", str(SR), *codec, *meta, str(out)],
                   check=True)
    return out


def loudness(path: str | Path) -> float:
    """Integrated loudness (LUFS) of a file, via ffmpeg's ebur128 filter."""
    err = subprocess.run([require_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128",
                          "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
    tail = err[err.rindex("Integrated loudness"):]
    return float(tail.split("I:")[1].split("LUFS")[0])
