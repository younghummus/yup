"""Listen to the original: tempo, beats, downbeats, key, chords, sections, vocal.

Pure numpy/scipy implementations of the standard MIR recipes:
  * onset strength  — log-spectral flux
  * tempo           — onset autocorrelation with a log-normal tempo prior
  * beats           — Ellis (2007) dynamic-programming beat tracker
  * key             — Krumhansl-Kessler profile correlation on chroma
  * chords          — triad templates on per-bar chroma + bass chroma, Viterbi-smoothed
  * vocal stem      — Demucs when installed, else centre-channel + harmonic masking
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal as sps
from scipy.ndimage import median_filter

from .dsp import SR, read_audio, samples
from .theory import MAJOR_PROFILE, MINOR_PROFILE, Chord, Key

ASR = 22050          # analysis sample rate
HOP = 512            # onset hop (23 ms)


def _mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=0) if x.ndim == 2 else x


def _down(x: np.ndarray) -> np.ndarray:
    return sps.resample_poly(_mono(x), ASR, SR) if SR != ASR else _mono(x)


def _stft(x: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    """Magnitude STFT, frames centred on k*hop. Shape (bins, frames)."""
    pad = np.pad(x, (n_fft // 2, n_fft // 2))
    n_frames = 1 + (len(pad) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    return np.abs(np.fft.rfft(pad[idx] * np.hanning(n_fft), axis=1)).T


# ----------------------------------------------------------------------- rhythm
def onset_envelope(x: np.ndarray) -> np.ndarray:
    """Log-spectral-flux onset strength at ASR/HOP frames per second."""
    S = np.log1p(100.0 * _stft(_down(x), 2048, HOP))
    flux = np.maximum(0.0, np.diff(S, axis=1)).mean(axis=0)
    flux = np.concatenate(([0.0], flux))
    flux -= median_filter(flux, size=17, mode="nearest")  # remove slow loudness drift
    flux = np.maximum(flux, 0)
    return flux / (flux.std() + 1e-9)


def estimate_tempo(env: np.ndarray, prior_bpm: float = 120.0, lo: float = 55.0, hi: float = 215.0,
                   hint: float | None = None) -> float:
    fps = ASR / HOP
    lags = np.arange(int(fps * 60 / hi), int(fps * 60 / lo) + 1)
    ac = np.array([np.dot(env[:-lag], env[lag:]) / (len(env) - lag) for lag in lags])
    bpms = 60 * fps / lags
    if hint:
        # Accept the hint's octave family, so a hint of 155 also tolerates 77.5 tracking.
        w = np.zeros_like(bpms)
        for mult in (0.5, 1.0, 2.0):
            w += np.exp(-0.5 * (np.log2(bpms / (hint * mult)) / 0.03) ** 2) * (1.0 if mult == 1 else 0.6)
    else:
        w = np.exp(-0.5 * (np.log2(bpms / prior_bpm) / 1.0) ** 2)
    score = ac * w
    i = int(np.argmax(score))
    # Parabolic refinement of the peak lag.
    if 0 < i < len(score) - 1:
        a, b, c = score[i - 1], score[i], score[i + 1]
        off = 0.5 * (a - c) / (a - 2 * b + c + 1e-12)
        lag = lags[i] + float(np.clip(off, -0.5, 0.5))
    else:
        lag = lags[i]
    bpm = 60 * fps / lag
    if hint:
        bpm = min((bpm * m for m in (0.5, 1, 2)), key=lambda b: abs(np.log2(b / hint)))
    return float(bpm)


def active_span(x: np.ndarray, floor_db: float = -45.0) -> tuple[float, float]:
    """First and last time (s) the music is within `floor_db` of its loudest 50 ms."""
    m = _mono(x)
    hop = samples(0.05)
    n = len(m) // hop
    if n == 0:
        return 0.0, len(m) / SR
    r = np.sqrt(np.mean(m[: n * hop].reshape(n, hop) ** 2, axis=1))
    on = np.flatnonzero(r > r.max() * 10 ** (floor_db / 20))
    if len(on) == 0:
        return 0.0, len(m) / SR
    return on[0] * hop / SR, (on[-1] + 1) * hop / SR


def refine_tempo(env: np.ndarray, bpm: float, span: float = 0.04, step: float = 0.02) -> float:
    """Sub-frame tempo precision: correlate the onset envelope with ideal pulse trains.

    Autocorrelation lags are whole frames (~9 BPM apart near 150), so search a fine
    BPM grid around the estimate, each at its best phase, and keep the strongest.
    """
    fps = ASR / HOP
    idx = np.arange(len(env))
    sm = np.convolve(env, np.hanning(5), mode="same")
    best_bpm, best = bpm, -np.inf
    for b in np.arange(bpm * (1 - span), bpm * (1 + span), step):
        period = 60 * fps / b
        pulses = np.arange(0, len(env) - period, period)
        phases = np.arange(0, period, 0.5)
        pos = pulses[None, :] + phases[:, None]
        score = np.interp(pos, idx, sm).mean(axis=1).max()
        if score > best:
            best_bpm, best = b, score
    return float(best_bpm)


def track_beats(env: np.ndarray, bpm: float, tightness: float = 400.0) -> np.ndarray:
    """Ellis DP beat tracker. Returns beat times in seconds."""
    fps = ASR / HOP
    period = 60 * fps / bpm
    n = len(env)
    local = np.convolve(env, np.hanning(int(period / 2) * 2 + 1), mode="same")
    score = np.zeros(n)
    back = -np.ones(n, dtype=int)
    lo, hi = int(round(period / 2)), int(round(period * 2))
    for i in range(n):
        start, stop = max(0, i - hi), i - lo
        if stop <= start:
            score[i] = local[i]
            continue
        prev = np.arange(start, stop)
        cost = -tightness * np.log((i - prev) / period) ** 2
        cand = score[prev] + cost
        k = int(np.argmax(cand))
        score[i] = local[i] + cand[k]
        back[i] = prev[k]
    # Start the backtrace from the best-scoring frame in the final beat period.
    tail = np.arange(max(0, n - int(period)), n)
    i = int(tail[np.argmax(score[tail])])
    beats = []
    while i >= 0:
        beats.append(i)
        i = back[i]
    return np.array(beats[::-1]) / fps


def regularise_beats(beats: np.ndarray, duration: float) -> np.ndarray:
    """Turn the tracker's frame-quantised beats into a smooth grid covering the file.

    Robust line fit (beat index -> time) plus the slowly-varying part of its residual, so
    a band that drifts off the click is followed; `fit_to_onsets` then locks it to the
    audio with millisecond precision.
    """
    if len(beats) < 4:
        raise ValueError("too few beats detected")
    beats = np.asarray(beats, dtype=np.float64)
    # Re-index: a skipped or doubled beat would bend the line, so count periods.
    med = np.median(np.diff(beats))
    k = np.concatenate(([0], np.cumsum(np.maximum(1, np.round(np.diff(beats) / med)))))
    keep = np.ones(len(beats), bool)
    for _ in range(3):
        slope, icpt = np.polyfit(k[keep], beats[keep], 1)
        resid = beats - (slope * k + icpt)
        keep = np.abs(resid) < max(0.25 * slope, 3 * np.std(resid[keep]) + 1e-4)
    kk, rr = k[keep], resid[keep]
    if len(rr) >= 9:
        rr = median_filter(rr, size=9, mode="nearest")
        rr = np.convolve(np.pad(rr, 8, mode="edge"), np.ones(17) / 17, mode="valid")
    first = int(np.ceil(max(0.0, icpt) / slope)) + 1
    n = int(np.ceil((duration - (icpt - slope * first)) / slope)) + 9  # room to finish the last bar
    idx = np.arange(-first, n - first)
    return icpt + slope * idx + np.interp(idx, kk, rr)


# ----------------------------------------------------------------------- harmony
def chromagram(x: np.ndarray, pmin: int = 40, pmax: int = 84, n_fft: int = 8192, hop: int = 2048,
               harmonic: bool = True, n_harm: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """(12, frames) chroma from harmonic pitch salience, plus frame times.

    Plain bin-folding chroma credits every overtone to its own pitch class (a C's 3rd and
    5th partials vote for G and E). Salience instead scores each semitone by the summed
    energy at its whole harmonic series, minus the energy just below it, so a note's
    fundamental wins over its overtones. HPSS keeps drums out.
    """
    S = _stft(_down(x), n_fft, hop)
    if harmonic:
        H = median_filter(S, size=(1, 9), mode="nearest")
        P = median_filter(S, size=(9, 1), mode="nearest")
        S = S * H ** 2 / (H ** 2 + P ** 2 + 1e-12)
    S = np.sqrt(S)
    bin_hz = ASR / n_fft
    pitches = np.arange(pmin, pmax + 1)
    sal = np.zeros((len(pitches), S.shape[1]))
    for k, p in enumerate(pitches):
        f0 = 440.0 * 2 ** ((p - 69) / 12)
        for h in range(1, n_harm + 1):
            b = h * f0 / bin_hz
            if b >= S.shape[0] - 2:
                break
            lo, hi = int(np.floor(b * 2 ** (-1 / 36))), int(np.ceil(b * 2 ** (1 / 36))) + 1
            sal[k] += S[lo:hi].max(axis=0) * 0.8 ** (h - 1)
        # Sub-harmonic check: a real fundamental has no energy an octave below it.
        b_sub = f0 / 2 / bin_hz
        if b_sub > 2:
            sal[k] -= 0.5 * S[int(b_sub) - 1:int(b_sub) + 2].max(axis=0)
    sal = np.maximum(sal, 0)
    C = np.zeros((12, S.shape[1]))
    np.add.at(C, pitches % 12, sal)
    times = np.arange(S.shape[1]) * hop / ASR
    return C, times


def detect_key(chroma_total: np.ndarray) -> Key:
    c = chroma_total / (np.linalg.norm(chroma_total) + 1e-12)
    best, best_r = Key(0), -2.0
    for mode, prof in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
        p = np.array(prof)
        for tonic in range(12):
            r = np.corrcoef(c, np.roll(p, tonic))[0, 1]
            if r > best_r:
                best, best_r = Key(tonic, mode), r
    return best


TRIADS = [Chord(r, q) for q in ("maj", "min") for r in range(12)]


def _templates() -> np.ndarray:
    T = np.zeros((24, 12))
    for k, ch in enumerate(TRIADS):
        for iv, w in zip(ch.intervals, (1.0, 0.8, 0.85)):
            T[k, (ch.root + iv) % 12] = w
    return T / np.linalg.norm(T, axis=1, keepdims=True)


def detect_chords(bar_chroma: np.ndarray, bar_bass: np.ndarray, key: Key, switch_penalty: float = 0.05,
                  diatonic_bonus: float = 0.06) -> list[Chord]:
    """One triad per bar: cosine template match + bass-root bonus + Viterbi smoothing."""
    T = _templates()
    C = bar_chroma / (np.linalg.norm(bar_chroma, axis=0, keepdims=True) + 1e-12)
    B = bar_bass / (bar_bass.max(axis=0, keepdims=True) + 1e-12)
    diat = set(key.diatonic_triads())
    emit = T @ C  # (24, bars)
    for k, ch in enumerate(TRIADS):
        emit[k] += 0.15 * B[ch.root]
        if ch in diat:
            emit[k] += diatonic_bonus
    n = emit.shape[1]
    score = emit[:, 0].copy()
    back = np.zeros((24, n), dtype=int)
    for t in range(1, n):
        trans = score[None, :] - switch_penalty * (1 - np.eye(24))
        back[:, t] = np.argmax(trans, axis=1)
        score = trans[np.arange(24), back[:, t]] + emit[:, t]
    path = [int(np.argmax(score))]
    for t in range(n - 1, 0, -1):
        path.append(int(back[path[-1], t]))
    return [TRIADS[k] for k in path[::-1]]


def _per_bar(values: np.ndarray, times: np.ndarray, bar_times: np.ndarray, weights=None) -> np.ndarray:
    """Average frame features into bars (columns)."""
    out = np.zeros((values.shape[0], len(bar_times) - 1))
    for b in range(len(bar_times) - 1):
        sel = (times >= bar_times[b]) & (times < bar_times[b + 1])
        if np.any(sel):
            w = None if weights is None else weights(times[sel] - bar_times[b], bar_times[b + 1] - bar_times[b])
            out[:, b] = np.average(values[:, sel], axis=1, weights=w)
    return out


def _fine_flux(x: np.ndarray, hop: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """Onset function on a 2.9 ms hop (times, flux), latency-corrected to ~1 ms."""
    S = np.log1p(100.0 * _stft(_down(x), 512, hop))
    flux = np.concatenate(([0.0], np.maximum(0.0, np.diff(S, axis=1)).mean(axis=0)))
    # Flux peaks when an onset is a quarter-window into the frame; shift to the onset.
    return np.arange(len(flux)) * hop / ASR + 0.25 * 512 / ASR, flux


def fit_to_onsets(beats: np.ndarray, x: np.ndarray, window: int = 8, drift_tol: float = 0.008) -> np.ndarray:
    """Lock the grid onto the actual transients.

    One global shift (+/-20% of a beat) removes the tracker's frame lag. Then, twice
    (search +/-20%, then +/-6%), the phase is re-measured every `window` beats, weighted
    by onset strength: a weighted line through those measurements corrects the tempo, and
    if they still wander by more than `drift_tol` s (a live band) the grid follows their
    smoothed curve. +/-20% stays clear of off-beat 8th-note hats at 50%.
    """
    times, flux = _fine_flux(x)
    period = float(np.median(np.diff(beats)))
    inside = (beats > times[0] + 0.01) & (beats < times[-1] - period)
    if inside.sum() < 8:
        return beats

    def best(bb: np.ndarray, span: float) -> tuple[float, float]:
        shifts = np.arange(-span, span, 0.001)
        score = np.array([np.interp(bb + s, times, flux).sum() for s in shifts])
        k = int(np.argmax(score))
        return float(shifts[k]), float(score[k])

    beats = beats + best(beats[inside], 0.2 * period)[0]
    idx = np.flatnonzero(inside)
    for span in (0.2, 0.06):
        centres, shifts, weights = [], [], []
        for w in range(0, len(idx) - window // 2, window):
            sel = idx[w:w + window]
            s, sc = best(beats[sel], span * period)
            centres.append(beats[sel].mean())
            shifts.append(s)
            weights.append(sc / len(sel))
        centres, shifts, weights = map(np.asarray, (centres, shifts, weights))
        ok = weights > 0.25 * np.median(weights)  # skip near-silent / drumless windows
        if ok.sum() < 3:
            return beats
        a, c = np.polyfit(centres[ok], shifts[ok], 1, w=weights[ok])
        corr = a * beats + c
        resid = median_filter(shifts[ok] - (a * centres[ok] + c), size=3, mode="nearest")
        if ok.sum() >= 4 and np.max(np.abs(resid)) > drift_tol:
            corr = corr + np.interp(beats, centres[ok], resid)
        beats = beats + corr
    return beats


def beat_novelty(beats: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Harmonic + bass-note change arriving at each beat (chords change on downbeats)."""
    C, ct = chromagram(x, n_fft=4096, hop=512)
    B, _ = chromagram(x, pmin=28, pmax=52, n_fft=8192, hop=512, n_harm=4)
    out = np.zeros(len(beats))
    for F, w in ((C, 1.0), (B, 0.7)):
        bc = _per_bar(F, ct, beats)
        bc = bc / (np.linalg.norm(bc, axis=0, keepdims=True) + 1e-12)
        ch = np.concatenate(([0.0], 1 - np.sum(bc[:, 1:] * bc[:, :-1], axis=0), [0.0]))[: len(beats)]
        out += w * ch / (ch.max() + 1e-12)
    return out


def choose_downbeat(beats: np.ndarray, x: np.ndarray) -> int:
    """Which of the first four beats starts bar 1: the phase where harmony changes most."""
    nov = beat_novelty(beats, x)
    scores = [np.mean(nov[p::4]) for p in range(4)]
    return int(np.argmax(scores))


# ------------------------------------------------------------------------- vocal
def have_demucs() -> bool:
    return importlib.util.find_spec("demucs") is not None


def demucs_vocals(path: str | Path) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs", "-o", tmp,
                        str(path)], check=True)
        hits = list(Path(tmp).rglob("vocals.wav"))
        if not hits:
            raise RuntimeError("demucs produced no vocals.wav")
        return read_audio(hits[0])


def centre_vocals(x: np.ndarray, n_fft: int = 4096, hop: int = 1024) -> np.ndarray:
    """Dependency-free vocal estimate: centre-panned, harmonic, mid-band energy.

    Lead vocals are mixed dead-centre and are harmonic (sustained partials), so masking
    the mid channel by L/R similarity and by a median-filter harmonic mask keeps
    mostly the singer. Good enough for a personal remix; Demucs is much cleaner.
    """
    win = np.hanning(n_fft)
    _, _, L = sps.stft(x[0], SR, window=win, nperseg=n_fft, noverlap=n_fft - hop)
    _, _, R = sps.stft(x[1], SR, window=win, nperseg=n_fft, noverlap=n_fft - hop)
    M = (L + R) / 2
    side = np.sum(np.abs(L - R) ** 2) / (np.sum(np.abs(L + R) ** 2) + 1e-12)
    if side > 1e-4:  # real stereo: keep what is identical in both channels
        sim = 2 * np.abs(L * np.conj(R)) / (np.abs(L) ** 2 + np.abs(R) ** 2 + 1e-12)
        centre = sim ** 12
    else:
        centre = np.ones(M.shape)
    mag = np.abs(M)
    H = median_filter(mag, size=(1, 17), mode="nearest")
    P = median_filter(mag, size=(17, 1), mode="nearest")
    harm = H ** 2 / (H ** 2 + P ** 2 + 1e-12)
    f = np.fft.rfftfreq(n_fft, 1 / SR)[:, None]
    band = 1 / (1 + (140 / (f + 1)) ** 4) / (1 + (f / 9000) ** 4)
    mask = centre * harm * band
    _, v = sps.istft(M * mask, SR, window=win, nperseg=n_fft, noverlap=n_fft - hop)
    v = v[: x.shape[1]]
    if len(v) < x.shape[1]:
        v = np.pad(v, (0, x.shape[1] - len(v)))
    return np.vstack([v, v])


def separate_vocals(path: str | Path, x: np.ndarray, method: str = "auto") -> tuple[np.ndarray, str]:
    if method == "demucs" or (method == "auto" and have_demucs()):
        return demucs_vocals(path), "demucs"
    return centre_vocals(x), "centre"


def estimate_pitch(x: np.ndarray, fmin: float = 80.0, fmax: float = 1000.0) -> tuple[float, float]:
    """(MIDI pitch, voicing 0-1) of a short mono grain via normalised autocorrelation."""
    x = x - x.mean()
    n = len(x)
    if n < samples(0.03) or not np.any(x):
        return 0.0, 0.0
    ac = sps.fftconvolve(x, x[::-1])[n - 1:]
    ac /= ac[0] + 1e-12
    lo, hi = int(SR / fmax), min(n - 1, int(SR / fmin))
    if hi <= lo:
        return 0.0, 0.0
    seg = ac[lo:hi]
    k = int(np.argmax(seg)) + lo
    # Guard against octave-low errors: prefer a strong peak at half the lag.
    half = k // 2
    if half >= lo and ac[half] > 0.85 * ac[k]:
        k = half
    f0 = SR / k
    return float(69 + 12 * np.log2(f0 / 440.0)), float(np.clip(ac[k], 0, 1))


def vocal_grains(vocal: np.ndarray, bar_times: np.ndarray, bars: list[int], n: int = 8,
                 length: float = 0.32) -> list[tuple[np.ndarray, float]]:
    """Pick strong, clearly-pitched syllables from the given bars to chop."""
    mono = _mono(vocal)
    hop = samples(0.01)
    frames = np.sqrt(np.mean(mono[: len(mono) // hop * hop].reshape(-1, hop) ** 2, axis=1))
    thr = np.percentile(frames[frames > 0], 70) if np.any(frames > 0) else 0
    cands = []
    for b in bars:
        s, e = int(bar_times[b] * SR / hop), int(bar_times[b + 1] * SR / hop)
        for i in range(max(1, s), min(e, len(frames) - 1)):
            if frames[i] >= thr and frames[i - 1] < thr:  # syllable onset
                a = i * hop + samples(0.02)
                g = mono[a: a + samples(length)]
                if len(g) < samples(length):
                    continue
                p, v = estimate_pitch(g[samples(0.03): samples(0.03) + samples(0.08)])
                if v > 0.55 and p > 0:
                    cands.append((v * frames[i], a, g, p))
    cands.sort(key=lambda c: -c[0])
    picked: list[tuple[np.ndarray, float]] = []
    used: list[int] = []
    for _, a, g, p in cands:
        if all(abs(a - u) > samples(length) for u in used):
            picked.append((g.copy(), p))
            used.append(a)
        if len(picked) >= n:
            break
    return picked


# ------------------------------------------------------------------- structure
def label_sections(energy_db: np.ndarray, vocal: np.ndarray, block: int = 4, chorus_db: float = 2.0,
                   drop_db: float = 1.5) -> list[str]:
    """Per-bar section labels from loudness and vocal presence, decided per phrase.

    Levels are judged in dB against the loudest sung phrase: a sung phrase within
    `chorus_db` of it is a chorus, quieter ones are verses; an unsung phrase within
    `drop_db` of it is an instrumental drop, quieter ones are intro / break / outro.
    """
    n = len(energy_db)
    if n == 0:
        return []
    e = np.maximum(np.asarray(energy_db, dtype=float), np.max(energy_db) - 40.0)
    norm = (e - e.min()) / (np.ptp(e) + 1e-9)
    vocal = np.asarray(vocal, dtype=float)

    def phrase_blocks(o: int) -> list[tuple[int, int]]:
        starts = ([0] if o else []) + list(range(o, n, block))
        return [(a, min(n, b)) for a, b in zip(starts, starts[1:] + [n]) if b > a]

    def cost(bl) -> float:  # sections are homogeneous: vocal on/off and loudness per phrase
        return sum((np.var(vocal[a:b]) + np.var(norm[a:b])) * (b - a) for a, b in bl)

    # Phrases need not start on bar 1 (pickups, odd intros): pick the best-fitting offset.
    blocks = min((phrase_blocks(o) for o in range(block)), key=cost)
    sung = [np.mean(vocal[a:b]) >= 0.5 for a, b in blocks]
    level = np.array([np.median(e[a:b]) for a, b in blocks])
    ref = level[np.array(sung)].max() if any(sung) else level.max()
    first_v = next((k for k, v in enumerate(sung) if v), len(blocks))
    last_v = max((k for k, v in enumerate(sung) if v), default=-1)
    labels = []
    for k in range(len(blocks)):
        if sung[k]:
            lab = "chorus" if level[k] >= ref - chorus_db else "verse"
        elif level[k] >= ref - drop_db:
            lab = "drop"
        elif k < first_v:
            lab = "intro"
        elif k > last_v:
            lab = "outro"
        else:
            lab = "break"
        labels.append(lab)
    # A build-up in the phrase before every chorus/drop that follows a quieter section.
    for k in range(1, len(labels)):
        if labels[k] in ("chorus", "drop") and labels[k - 1] in ("verse", "break", "intro"):
            labels[k - 1] = "build"
    if len(labels) > 1 and labels[-1] != "outro":
        labels[-1] = "outro"
    out: list[str] = []
    for k, (a, b) in enumerate(blocks):
        out += [labels[k]] * (b - a)
    return out


@dataclass
class Analysis:
    duration: float
    bpm: float
    beats: np.ndarray          # beat times (s) from bar 1 beat 1 to the end of the last bar
    key: Key
    bar_times: np.ndarray      # n_bars + 1 boundaries (s)
    chords: list[Chord]
    energy_db: np.ndarray
    vocal_bars: np.ndarray     # bool per bar
    labels: list[str]
    vocal: np.ndarray | None = None
    vocal_method: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def n_bars(self) -> int:
        return len(self.bar_times) - 1

    @property
    def offset(self) -> float:
        """Seconds of silence to prepend so bar 1 (maybe a pickup bar) starts at t >= 0."""
        return max(0.0, -float(self.beats[0]))

    def summary(self) -> str:
        prog = " ".join(c.name for c in self.chords[:16])
        return (f"{self.duration:.1f}s  {self.bpm:.1f} BPM  key {self.key.name}  {self.n_bars} bars  "
                f"vocal via {self.vocal_method or 'n/a'}\n  first chords: {prog}")


def analyse(path: str | Path, bpm_hint: float | None = None, key_hint: Key | None = None,
            vocal_method: str = "auto", acapella: str | Path | None = None) -> Analysis:
    x = read_audio(path)
    duration = x.shape[1] / SR
    notes = []
    env = onset_envelope(x)
    bpm = estimate_tempo(env, hint=bpm_hint)
    bpm = refine_tempo(env, bpm)
    raw = track_beats(env, bpm)
    # Beats the tracker invents in leading/trailing silence would bend the grid fit.
    t_on, t_off = active_span(x)
    raw = raw[(raw >= t_on - 0.1) & (raw <= t_off + 0.1)]
    if bpm_hint is None and bpm < 90:
        # Future bass lives at 140-170 with half-time drums: split every beat in two.
        raw = np.sort(np.concatenate((raw, (raw[:-1] + raw[1:]) / 2)))
        bpm *= 2
        notes.append("doubled tempo into the future bass range")
    beats = fit_to_onsets(regularise_beats(raw, duration), x)
    period = float(np.median(np.diff(beats)))
    # Bar 1 starts on a downbeat; audio before it (a pickup) gets its own lead-in bar,
    # which may start before t=0 — the remix then pads the front by `offset`.
    beats = beats[choose_downbeat(beats, x):]
    if beats[0] > 0.25 * period:
        beats = np.concatenate((beats[0] - period * np.arange(4, 0, -1), beats))
    n_bars = int(np.searchsorted(beats[::4], duration - 1e-6))
    beats = beats[: 4 * n_bars + 1]
    bar_times = beats[::4]

    C, ct = chromagram(x)
    Cb, _ = chromagram(x, pmin=28, pmax=52, n_harm=4)
    key = key_hint or detect_key(C.sum(axis=1))
    first_beat_heavier = lambda t, L: np.where(t < L / 4, 1.5, 1.0)  # noqa: E731
    bar_c = _per_bar(C, ct, bar_times, first_beat_heavier)
    bar_b = _per_bar(Cb, ct, bar_times, first_beat_heavier)
    chords = detect_chords(bar_c, bar_b, key)

    mono = _mono(x)
    energy = np.array([20 * np.log10(np.sqrt(np.mean(mono[samples(max(0, a)):samples(b)] ** 2)) + 1e-9)
                       for a, b in zip(bar_times[:-1], bar_times[1:])])
    if acapella:
        vocal, method = read_audio(acapella), "acapella"
    else:
        vocal, method = separate_vocals(path, x, vocal_method)
    vm = _mono(vocal)
    v_energy = np.array([np.sqrt(np.mean(vm[samples(max(0, a)):samples(b)] ** 2) + 1e-12)
                         for a, b in zip(bar_times[:-1], bar_times[1:])])
    v_db = 20 * np.log10(v_energy + 1e-9)
    v_db -= np.percentile(v_db, 90)
    # Masking leaks some instrument energy; demand clear presence for the estimate.
    vocal_bars = v_db > (-12.0 if method == "centre" else -18.0)
    labels = label_sections(energy, vocal_bars.astype(float))
    return Analysis(duration, float(60 / period), beats, key, bar_times, chords, energy,
                    vocal_bars, labels, vocal, method, notes)

