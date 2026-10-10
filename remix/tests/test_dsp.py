import shutil
import subprocess

import numpy as np
import pytest

from radcat import dsp
from radcat.dsp import SR

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def _has_rubberband() -> bool:
    if not HAS_FFMPEG:
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return " rubberband " in out


def band_db(x, lo, hi):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return 10 * np.log10(spec[(f >= lo) & (f < hi)].sum() + 1e-30)


def peak_hz(x):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.fft.rfftfreq(len(x), 1 / SR)[np.argmax(spec)]


def test_oscillators_are_bounded_and_pitched():
    n = SR
    for osc in (dsp.saw, dsp.square, dsp.sine, dsp.triangle):
        x = osc(220.0, n)
        assert x.shape == (n,)
        assert np.max(np.abs(x)) <= 1.2
        assert peak_hz(x) == pytest.approx(220.0, abs=2.0)


def test_polyblep_saw_aliases_less_than_naive():
    n, f = SR, 4987.0
    ph = (np.arange(n) * f / SR) % 1.0
    naive = 2 * ph - 1
    blep = dsp.saw(f, n)
    # Energy between harmonics (alias products) relative to the fundamental.
    def alias_ratio(x):
        spec = np.abs(np.fft.rfft(x * np.hanning(n))) ** 2
        freqs = np.fft.rfftfreq(n, 1 / SR)
        harm = np.zeros_like(freqs, bool)
        for k in range(1, int(SR / 2 / f) + 1):
            harm |= np.abs(freqs - k * f) < 20
        return spec[~harm].sum() / spec[harm].sum()
    assert alias_ratio(blep) < 0.25 * alias_ratio(naive)


def test_filters_attenuate_the_right_band():
    x = dsp.noise(SR, 1)
    lp = dsp.filt(x, "lowpass", 1000, order=2)
    hp = dsp.filt(x, "highpass", 5000, order=2)
    assert band_db(lp, 8000, 16000) < band_db(x, 8000, 16000) - 40
    assert band_db(hp, 50, 500) < band_db(x, 50, 500) - 40
    pk = dsp.filt(x, "peak", 3000, q=1.0, gain_db=6)
    assert band_db(pk, 2800, 3200) == pytest.approx(band_db(x, 2800, 3200) + 6, abs=1.0)


def test_sweep_with_constant_cutoff_matches_static_filter():
    x = dsp.noise(8000, 3)
    a = dsp.sweep(x, 2000.0, "lowpass", q=0.8, order=2)
    b = dsp.filt(x, "lowpass", 2000.0, q=0.8, order=2)
    assert np.allclose(a, b, atol=1e-9)


def test_sweep_stereo_shapes():
    x = np.vstack([dsp.noise(5000, 1), dsp.noise(5000, 2)])
    y = dsp.sweep(x, np.linspace(300, 8000, 5000), "lowpass")
    assert y.shape == x.shape and np.all(np.isfinite(y))


def test_equal_power_pan():
    x = np.ones(10)
    c = dsp.pan(x, 0.0)
    assert np.allclose(c[0], c[1]) and np.allclose(c[0], 1.0)
    left = dsp.pan(x, -1.0)
    assert np.allclose(left[1], 0.0, atol=1e-12)
    # Power is constant across the pan law.
    for p in np.linspace(-1, 1, 9):
        s = dsp.pan(x, p)
        assert np.allclose(s[0] ** 2 + s[1] ** 2, 2.0)


def test_mono_below_removes_low_side_energy():
    t = np.arange(SR) / SR
    low = np.sin(2 * np.pi * 50 * t)
    x = np.vstack([low, -low])  # pure side signal
    y = dsp.mono_below(x, 120)
    assert dsp.rms(y[0] - y[1]) < 0.05 * dsp.rms(x[0] - x[1])


def test_sidechain_curve_ducks_and_recovers():
    hits = [1000, 30000]
    g = dsp.sidechain_curve(40000, hits, depth=0.8, release=0.2)
    assert g[1000] == pytest.approx(0.2, abs=1e-6)
    assert g[1000 + dsp.samples(0.2) + 10] == pytest.approx(1.0)
    assert np.all(np.diff(g[1000:1000 + dsp.samples(0.2)]) >= -1e-12)  # monotone recovery
    assert g.min() >= 0.2 - 1e-9


def test_compressor_reduces_dynamic_range():
    t = np.arange(SR) / SR
    x = np.sin(2 * np.pi * 220 * t) * np.where(t < 0.5, 0.1, 0.9)
    y = dsp.compress(x[None, :].repeat(2, 0), threshold_db=-20, ratio=4, attack=0.002, release=0.05)
    loud, quiet = dsp.rms(y[:, SR // 2 + 4000:]), dsp.rms(y[:, 4000:SR // 2 - 4000])
    assert loud / quiet < 0.9 / 0.1 * 0.5


def test_limiter_respects_true_peak_ceiling():
    x = dsp.noise(SR, 5) * 3.0
    y = dsp.limit(np.vstack([x, x * 0.8]), ceiling_db=-1.0)
    assert dsp.true_peak(y) <= dsp.db(-1.0) + 1e-6
    # Quiet material passes untouched.
    q = np.vstack([dsp.sine(440.0, SR) * 0.1] * 2)
    assert np.allclose(dsp.limit(q, -1.0), q, atol=1e-6)


def test_reverb_and_delay():
    ir = dsp.reverb_ir(1.0)
    assert ir.shape[0] == 2 and np.allclose(np.sum(ir ** 2) / 2, 1.0)
    imp = np.zeros(SR)
    imp[0] = 1.0
    d = dsp.delay(imp, 0.25, feedback=0.5, repeats=3)
    first = np.argmax(np.abs(d).max(axis=0))
    assert first == pytest.approx(dsp.samples(0.25), abs=2)


def test_bus_add_clips_to_bounds():
    b = dsp.Bus(100)
    b.add(np.ones(50), 80)  # runs off the end
    b.add(np.ones(50), -40)  # starts before 0
    assert b.buf[0, 99] > 0 and b.buf[0, 0] > 0
    b.add(np.ones(10), 500)  # entirely outside: ignored
    assert np.isfinite(b.buf).all()


def test_envelopes():
    e = dsp.adsr(1000, a=0.001, d=0.002, s=0.5, r=0.002, gate=600)
    assert e[0] == 0 and e.max() <= 1.0 and e[-1] < 0.05
    f = dsp.fade(np.ones(1000), 0.001, 0.001)
    assert f[0] == 0 and f[-1] == 0 and f[500] == 1


@needs_ffmpeg
def test_wav_roundtrip(tmp_path):
    x = np.vstack([dsp.sine(440.0, 4000) * 0.5, dsp.sine(660.0, 4000) * 0.25])
    for bits in (16, 24):
        p = dsp.write_wav(tmp_path / f"t{bits}.wav", x, bits=bits)
        y = dsp.read_audio(p)
        assert y.shape == x.shape
        assert np.max(np.abs(y - x)) < (2e-4 if bits == 16 else 2e-6)


@needs_ffmpeg
def test_encode_hits_loudness_target(tmp_path):
    x = np.vstack([dsp.noise(SR * 4, 1), dsp.noise(SR * 4, 2)]) * 0.05
    wav = dsp.write_wav(tmp_path / "n.wav", x)
    mp3 = dsp.encode(wav, tmp_path / "n.mp3", lufs=-12.0, title="t", artist="a")
    assert mp3.exists() and mp3.stat().st_size > 10000
    assert dsp.loudness(mp3) == pytest.approx(-12.0, abs=1.0)


@pytest.mark.skipif(not _has_rubberband(), reason="ffmpeg without rubberband")
def test_pitch_shift_octave_up():
    x = np.vstack([dsp.sine(220.0, SR)] * 2) * 0.5
    y = dsp.pitch_shift(x, 12)
    assert y.shape[1] == pytest.approx(x.shape[1], rel=0.02)
    mid = y[0, SR // 4: 3 * SR // 4]
    assert peak_hz(mid) == pytest.approx(440.0, rel=0.02)


@needs_ffmpeg
def test_lufs_meter_matches_ffmpeg(tmp_path):
    t = np.arange(SR * 5) / SR
    x = np.vstack([np.sin(2 * np.pi * 997 * t) * 0.3, dsp.filt(dsp.noise(len(t), 4), "lowpass", 3000) * 0.4])
    x[:, SR * 2: SR * 3] *= 0.05  # a quiet stretch the gate should ignore
    wav = dsp.write_wav(tmp_path / "l.wav", x)
    assert dsp.integrated_lufs(x) == pytest.approx(dsp.loudness(wav), abs=0.2)


def test_lufs_reference_tone():
    # BS.1770: a 997 Hz full-scale sine in one channel reads -3.01 LUFS.
    t = np.arange(SR * 3) / SR
    x = np.vstack([np.sin(2 * np.pi * 997 * t), np.zeros_like(t)])
    assert dsp.integrated_lufs(x) == pytest.approx(-3.01, abs=0.1)
    assert dsp.integrated_lufs(np.zeros((2, 100))) == -70.0


def test_master_to_hits_target_under_ceiling():
    x = np.vstack([dsp.noise(SR * 4, 7), dsp.noise(SR * 4, 8)]) * 0.05
    y = dsp.master_to(x, -10.0, ceiling_db=-1.5)
    assert dsp.integrated_lufs(y) == pytest.approx(-10.0, abs=0.2)
    assert dsp.true_peak(y) <= dsp.db(-1.5) + 1e-6
