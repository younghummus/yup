"""The instrument rack: Serum-style supersaw, 808, drums, keys, vocal chops, FX.

Each function returns a freshly rendered note/hit (mono 1-D or stereo (2, n)) that the
arranger drops onto a Bus. Durations are seconds; pitches are MIDI numbers.
"""
from __future__ import annotations

import numpy as np

from .dsp import (SR, adsr, exp_decay, fade, filt, noise, pan, samples, saturate, saw, sine,
                  square, sweep, triangle)
from .theory import midi_to_hz


def _t(n: int) -> np.ndarray:
    return np.arange(n) / SR


# ---------------------------------------------------------------------- synths
def supersaw(midi: float, dur: float, voices: int = 7, detune: float = 0.22, bend=None,
             seed: int = 0, stereo: float = 0.9) -> np.ndarray:
    """Detuned saw stack (Serum's 'Supersaw' unison). `bend` = per-sample semitone offset."""
    n = samples(dur)
    r = np.random.default_rng(seed)
    spread = np.linspace(-1.0, 1.0, voices)
    offsets = np.sign(spread) * np.abs(spread) ** 1.4 * detune
    bend = 0.0 if bend is None else bend
    out = np.zeros((2, n))
    for i, o in enumerate(offsets):
        f = midi_to_hz(midi + o + bend)
        v = saw(f, n, r.random())
        g = 1.0 if i == voices // 2 else 0.75
        out += g * pan(v, spread[i] * stereo)
    return out / voices


def future_chord(notes: list[int], dur: float, cutoff=(700.0, 9500.0, 4200.0), attack: float = 0.004,
                 release: float = 0.08, scoop: float = 0.0, wobble_hz: float = 0.0, wobble_depth: float = 0.0,
                 seed: int = 0, air: float = 0.08) -> np.ndarray:
    """A future bass chord hit: supersaw stack, filter envelope, optional pitch scoop + wobble.

    cutoff = (start, peak, sustain) Hz for the filter envelope. `scoop` (semitones) bends
    every voice up into pitch over ~60 ms, the signature 'pitch-rise' chord swell.
    """
    n = samples(dur)
    t = _t(n)
    bend = None
    if scoop:
        bend = -scoop * np.exp(-t / 0.035)
    sig = np.zeros((2, n))
    for k, m in enumerate(notes):
        sig += supersaw(m, dur, bend=bend, seed=seed * 31 + k)
    sig /= np.sqrt(len(notes))
    # Air: a little filtered noise glued to the chord, like a Serum noise oscillator.
    if air:
        nz = filt(noise(n, seed + 99), "highpass", 6000.0)
        sig += air * np.vstack([nz, np.roll(nz, 311)])
    c0, c1, c2 = cutoff
    env = c2 + (c1 - c2) * np.exp(-t / 0.18)
    env = np.minimum(env, c0 + (c1 - c0) * np.clip(t / 0.02, 0, 1))
    # Round the attack/decay corner: a kink in the cutoff curve ticks audibly.
    k = samples(0.006)
    env = np.convolve(np.pad(env, (k, k), mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    amp = adsr(n, a=attack, d=0.25, s=0.85, r=release, gate=n - samples(release))
    if wobble_hz:
        lfo = 0.5 + 0.5 * np.cos(2 * np.pi * wobble_hz * t)
        env = env * (1 - wobble_depth * 0.85 * (1 - lfo))
        amp = amp * (1 - wobble_depth * 0.6 * (1 - lfo))
    out = sweep(sig, env, "lowpass", q=0.9, block=64) * amp
    return fade(out, 0.002, 0.01)


def pad(notes: list[int], dur: float, cutoff: float = 2200.0, seed: int = 0) -> np.ndarray:
    """Slow, warm supersaw pad."""
    n = samples(dur)
    sig = np.zeros((2, n))
    for k, m in enumerate(notes):
        sig += supersaw(m, dur, voices=5, detune=0.14, seed=seed + k)
    sig = filt(sig, "lowpass", cutoff, order=2) / np.sqrt(len(notes))
    return sig * adsr(n, a=min(0.6, dur / 3), d=0.5, s=0.9, r=min(0.6, dur / 3), gate=n - samples(min(0.6, dur / 3)))


def pluck(midi: float, dur: float, bright: float = 1.0, decay: float = 0.35, seed: int = 0) -> np.ndarray:
    """Additive pluck: upper partials die faster (bell-ish Porter Robinson sparkle)."""
    n = samples(dur)
    t = _t(n)
    f0 = midi_to_hz(midi)
    r = np.random.default_rng(seed)
    out = np.zeros(n)
    for k in range(1, 24):
        f = f0 * k * (1 + 0.0004 * k * k)  # slight stiffness
        if f > 17000:
            break
        out += np.sin(2 * np.pi * f * t + r.random() * 6.28) * np.exp(-t / decay * (1 + 0.45 * k / bright)) / k ** 1.15
    out *= np.minimum(1, t / 0.002)
    return fade(out / 1.6, 0.0, 0.02)


def epiano(midi: float, dur: float, vel: float = 0.8, seed: int = 0) -> np.ndarray:
    """FM electric piano (Rhodes-style), stereo tremolo. The R&B half of the sound."""
    n = samples(dur + 0.6)
    t = _t(n)
    f = midi_to_hz(midi)
    index = (1.6 * vel + 0.4) * np.exp(-t * 2.5) + 0.25
    mod = np.sin(2 * np.pi * f * t) * index
    body = np.sin(2 * np.pi * f * t + mod)
    tine = np.sin(2 * np.pi * f * 14.0 * t) * np.exp(-t * 55) * 0.18 * vel
    gate = samples(dur)
    amp = np.exp(-t * (0.9 + 0.012 * max(0, midi - 48)))
    amp[gate:] *= np.exp(-(t[gate:] - t[gate]) * 12)
    x = (body + tine) * amp * (0.55 + 0.45 * vel)
    trem = 0.5 + 0.5 * np.sin(2 * np.pi * 4.1 * t + seed)
    st = np.vstack([x * (0.65 + 0.35 * trem), x * (0.65 + 0.35 * (1 - trem))])
    return fade(st, 0.002, 0.05)


def sub(midi: float, dur: float, glide_from: float | None = None, glide: float = 0.05) -> np.ndarray:
    """Clean sine sub with a touch of triangle for audibility on small speakers."""
    n = samples(dur)
    t = _t(n)
    p = np.full(n, float(midi))
    if glide_from is not None:
        p = midi + (glide_from - midi) * np.exp(-t / glide)
    f = midi_to_hz(p)
    x = 0.85 * sine(f, n) + 0.15 * triangle(f, n)
    return x * adsr(n, a=0.006, d=0.2, s=0.9, r=0.04, gate=n - samples(0.04))


def bass808(midi: float, dur: float, glide_from: float | None = None, glide: float = 0.07,
            decay: float = 1.1, drive: float = 2.2) -> np.ndarray:
    """Trap 808: punchy pitch drop, long decay, saturation for upper harmonics."""
    n = samples(dur)
    t = _t(n)
    p = midi + 5.0 * np.exp(-t / 0.01)
    if glide_from is not None:
        p = p + (glide_from - midi) * np.exp(-t / glide)
    x = sine(midi_to_hz(p), n)
    env = exp_decay(n, decay) * np.minimum(1, t / 0.0015)
    x = saturate(x * env, drive) * 0.9
    return fade(x, 0.0, 0.03)


# ----------------------------------------------------------------------- drums
def kick(dur: float = 0.42, tone: float = 50.0, punch: float = 1.0, seed: int = 1) -> np.ndarray:
    n = samples(dur)
    t = _t(n)
    f = tone + 210 * punch * np.exp(-t / 0.025) + 40 * np.exp(-t / 0.12)
    body = sine(f, n) * np.exp(-t / 0.30) * np.minimum(1, t / 0.001)
    click = filt(noise(n, seed), "highpass", 3000) * np.exp(-t / 0.0025) * 0.5
    return fade(saturate(body * 1.2 + click, 1.6), 0.0, 0.02)


def clap(dur: float = 0.45, seed: int = 2) -> np.ndarray:
    n = samples(dur)
    t = _t(n)
    nz = noise(n, seed)
    env = np.zeros(n)
    for k, off in enumerate((0.0, 0.009, 0.018, 0.027)):
        tt = t - off
        m = tt >= 0
        env[m] += np.exp(-tt[m] / (0.006 if k < 3 else 0.16)) * (0.8 if k < 3 else 1.0)
    x = filt(nz * env, "bandpass", 1150, q=0.8) * 2.2 + filt(nz * env, "highpass", 2500) * 0.4
    return fade(x, 0.0, 0.03)


def snare(dur: float = 0.35, tune: float = 1.0, seed: int = 3) -> np.ndarray:
    n = samples(dur)
    t = _t(n)
    tone = (sine(185 * tune, n) + 0.5 * sine(330 * tune, n)) * np.exp(-t / 0.05)
    nz = filt(noise(n, seed), "highpass", 1700) * np.exp(-t / 0.13)
    nz = filt(nz, "peak", 5000, q=1.0, gain_db=4)
    return fade(saturate(0.6 * tone + 0.8 * nz, 1.4), 0.0, 0.02)


_HAT_FREQS = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)


def hat(open_: bool = False, dur: float | None = None, seed: int = 4) -> np.ndarray:
    """808-style hat: six detuned squares + noise through a high band."""
    dur = dur or (0.38 if open_ else 0.07)
    n = samples(dur)
    t = _t(n)
    metal = sum(square(f * 1.7, n) for f in _HAT_FREQS) / 6
    x = 0.6 * metal + 0.5 * noise(n, seed)
    x = filt(filt(x, "bandpass", 10000, q=0.9), "highpass", 7000, order=2)
    return x * np.exp(-t / (0.11 if open_ else 0.018)) * 1.8


def crash(dur: float = 2.5, seed: int = 5) -> np.ndarray:
    n = samples(dur)
    t = _t(n)
    metal = sum(square(f * 3.1, n) for f in _HAT_FREQS) / 6
    x = filt(0.5 * metal + noise(n, seed), "highpass", 4500, order=2)
    st = np.vstack([x, np.roll(filt(noise(n, seed + 1), "highpass", 4500), 0) * 0.8 + 0.2 * x])
    return st * np.exp(-t / 0.75) * 0.5


def rim(dur: float = 0.08) -> np.ndarray:
    n = samples(dur)
    t = _t(n)
    x = (sine(1720, n) * 0.6 + sine(480, n) * 0.5) * np.exp(-t / 0.012)
    return x


def snap(dur: float = 0.12, seed: int = 6) -> np.ndarray:
    n = samples(dur)
    t = _t(n)
    return filt(noise(n, seed), "bandpass", 2400, q=1.6) * np.exp(-t / 0.018) * 3.0


def shaker(dur: float = 0.09, seed: int = 8) -> np.ndarray:
    n = samples(dur)
    t = _t(n)
    env = np.minimum(1, t / 0.012) * np.exp(-t / 0.035)
    return filt(noise(n, seed), "bandpass", 6500, q=1.2) * env * 1.6


# ------------------------------------------------------------------------- FX
def riser(dur: float, start_midi: float = 55, octaves: float = 2.0, seed: int = 9) -> np.ndarray:
    """White-noise sweep + rising saw: the build-up tension."""
    n = samples(dur)
    t = _t(n)
    k = t / dur
    cut = 300 * (12000 / 300) ** (k ** 1.6)
    nz = sweep(np.vstack([noise(n, seed), noise(n, seed + 1)]), cut, "bandpass", q=1.4)
    tone = saw(midi_to_hz(start_midi + 12 * octaves * k ** 2), n)
    tone = sweep(tone, 400 + 6000 * k ** 2, "lowpass", q=1.2)
    amp = k ** 2.2
    return (nz * 1.4 + 0.25 * pan(tone, 0)) * amp


def downlifter(dur: float = 2.0, seed: int = 10) -> np.ndarray:
    n = samples(dur)
    t = _t(n)
    k = t / dur
    cut = 9000 * (200 / 9000) ** k
    nz = sweep(np.vstack([noise(n, seed), noise(n, seed + 1)]), cut, "bandpass", q=1.2)
    return nz * (1 - k) ** 1.5 * 1.2


def reverse_cymbal(dur: float = 1.0, seed: int = 11) -> np.ndarray:
    return crash(dur, seed)[:, ::-1] * 1.4


def impact(dur: float = 2.2, seed: int = 12) -> np.ndarray:
    n = samples(dur)
    t = _t(n)
    boom = sine(30 + 45 * np.exp(-t / 0.15), n) * np.exp(-t / 0.7)
    hit = filt(noise(n, seed), "lowpass", 3000) * np.exp(-t / 0.08)
    return pan(saturate(boom + 0.4 * hit, 1.3), 0)


def vinyl(dur: float, seed: int = 13) -> np.ndarray:
    """Hiss + crackle bed for the lo-fi intro."""
    n = samples(dur)
    r = np.random.default_rng(seed)
    hiss = filt(noise(n, seed), "bandpass", 4000, q=0.5) * 0.25
    clicks = np.zeros(n)
    idx = r.integers(0, n, size=max(1, int(dur * 9)))
    clicks[idx] = r.uniform(-1, 1, idx.size)
    clicks = filt(clicks, "highpass", 1500) * 2.5
    return np.vstack([hiss + clicks, np.roll(hiss, 977) + 0.7 * clicks])


# ---------------------------------------------------------------- vocal chops
# Soprano formants: (Hz, dB, bandwidth Hz) — standard singing-voice tables.
VOWELS = {
    "a": ((800, 0, 80), (1150, -6, 90), (2900, -32, 120), (3900, -20, 130), (4950, -50, 140)),
    "e": ((350, 0, 60), (2000, -20, 100), (2800, -15, 120), (3600, -40, 150), (4950, -56, 200)),
    "i": ((270, 0, 60), (2140, -12, 90), (2950, -26, 100), (3900, -26, 120), (4950, -44, 120)),
    "o": ((450, 0, 70), (800, -11, 80), (2830, -22, 100), (3800, -22, 130), (4950, -50, 135)),
    "u": ((325, 0, 50), (700, -16, 60), (2700, -35, 170), (3800, -40, 180), (4950, -60, 200)),
}


def _formant(src: np.ndarray, vowel: str, shift: float) -> np.ndarray:
    out = np.zeros_like(src)
    for f, g, bw in VOWELS[vowel]:
        fs = f * shift
        out += filt(src, "bandpass", fs, q=fs / bw) * 10 ** (g / 20)
    return out


def vox(midi: float, dur: float, vowel: str = "a", to_vowel: str | None = None, glide_from: float | None = None,
        glide: float = 0.03, shift: float = 1.12, vibrato: float = 0.25, breath: float = 0.05,
        attack: float = 0.006, release: float = 0.04, seed: int = 0) -> np.ndarray:
    """Formant-synthesised sung vowel — the raw material of a chopped vocal hook.

    `shift` > 1 scales the formants up: the pitched-up 'chipmunk' chop colour.
    """
    n = samples(dur)
    t = _t(n)
    p = np.full(n, float(midi))
    if glide_from is not None:
        p = midi + (glide_from - midi) * np.exp(-t / glide)
    vib = vibrato * np.minimum(1, np.maximum(0, t - 0.12) / 0.2) * np.sin(2 * np.pi * 5.6 * t)
    r = np.random.default_rng(seed)
    jitter = np.interp(t, np.linspace(0, dur, 12), r.normal(0, 0.04, 12))
    f = midi_to_hz(p + vib + jitter)
    src = saw(f, n) * 0.8 + square(f, n, width=0.12) * 0.2
    src = filt(src, "lowpass", 5500)
    src = src + breath * noise(n, seed)
    x = _formant(src, vowel, shift)
    if to_vowel and to_vowel != vowel:
        y = _formant(src, to_vowel, shift)
        k = np.clip(t / max(dur, 1e-3), 0, 1)
        x = x * (1 - k) + y * k
    x = filt(x, "highpass", 180)
    x /= max(1e-9, np.max(np.abs(x))) * 1.2
    return x * adsr(n, a=attack, d=0.1, s=0.9, r=release, gate=n - samples(release))


def choir(notes: list[int], dur: float, vowel: str = "u", seed: int = 0) -> np.ndarray:
    """'Ooh' vocal pad stacked from formant voices (for breaks)."""
    out = np.zeros((2, samples(dur)))
    for k, m in enumerate(notes):
        v = vox(m, dur, vowel, shift=1.0, vibrato=0.15, attack=min(0.5, dur / 3), release=min(0.6, dur / 3),
                breath=0.08, seed=seed + k)
        out += pan(v, (k / max(1, len(notes) - 1) - 0.5) * 1.2)
    return out / np.sqrt(len(notes))
