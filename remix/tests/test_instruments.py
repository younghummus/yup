import numpy as np
import pytest

from radcat import instruments as ins
from radcat.analysis import estimate_pitch
from radcat.dsp import SR, rms, samples


def spectrum_peak(x, lo=20, hi=20000):
    x = x if x.ndim == 1 else x.mean(0)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / SR)
    sel = (f >= lo) & (f <= hi)
    return f[sel][np.argmax(spec[sel])]


@pytest.mark.parametrize("make,dur", [
    (lambda: ins.supersaw(60, 0.3), 0.3),
    (lambda: ins.future_chord([60, 64, 67, 71], 0.4, scoop=5.0), 0.4),
    (lambda: ins.future_chord([60, 64, 67], 0.5, wobble_hz=5.0, wobble_depth=0.8), 0.5),
    (lambda: ins.pad([57, 60, 64], 1.0), 1.0),
    (lambda: ins.pluck(72, 0.3), 0.3),
    (lambda: ins.sub(36, 0.5, glide_from=40), 0.5),
    (lambda: ins.bass808(36, 0.8, glide_from=43), 0.8),
    (lambda: ins.kick(), 0.42),
    (lambda: ins.clap(), 0.45),
    (lambda: ins.snare(), 0.35),
    (lambda: ins.hat(), 0.07),
    (lambda: ins.hat(True), 0.38),
    (lambda: ins.crash(1.0), 1.0),
    (lambda: ins.rim(), 0.08),
    (lambda: ins.snap(), 0.12),
    (lambda: ins.shaker(), 0.09),
    (lambda: ins.riser(1.0), 1.0),
    (lambda: ins.downlifter(1.0), 1.0),
    (lambda: ins.reverse_cymbal(0.5), 0.5),
    (lambda: ins.impact(1.0), 1.0),
    (lambda: ins.vinyl(1.0), 1.0),
    (lambda: ins.vox(72, 0.3, "a", to_vowel="u"), 0.3),
    (lambda: ins.choir([60, 64, 67], 0.8), 0.8),
])
def test_instruments_render_clean_audio(make, dur):
    x = make()
    assert x.shape[-1] == samples(dur)
    assert np.all(np.isfinite(x))
    assert rms(x) > 1e-4
    assert np.max(np.abs(x)) < 4.0


def test_epiano_rings_past_its_gate():
    x = ins.epiano(60, 0.2)
    assert x.shape == (2, samples(0.8))
    p, voiced = estimate_pitch(x.mean(0)[samples(0.05):samples(0.15)])
    assert voiced > 0.8 and p == pytest.approx(60, abs=0.3)
    assert rms(x[:, samples(0.5):]) > 1e-3  # release tail, not a hard stop


def test_kick_and_808_live_in_the_low_end():
    assert spectrum_peak(ins.kick(), 20, 400) < 120
    b = ins.bass808(33, 1.0)  # A1, 55 Hz
    assert spectrum_peak(b[samples(0.1):], 20, 400) == pytest.approx(55.0, rel=0.05)


def test_supersaw_is_wide_and_pitched():
    x = ins.supersaw(57, 0.5)
    side = rms(x[0] - x[1]) / rms(x[0] + x[1])
    assert side > 0.2  # unison spread across the stereo field
    assert spectrum_peak(x, 100, 400) == pytest.approx(220.0, rel=0.02)


def test_scoop_bends_into_pitch():
    x = ins.future_chord([69], 0.5, scoop=12.0, air=0.0).mean(0)
    early = estimate_pitch(x[samples(0.005):samples(0.035)], 60, 1000)[0]
    late = estimate_pitch(x[samples(0.3):samples(0.4)], 60, 1000)[0]
    assert late == pytest.approx(69, abs=0.6)
    assert early < late - 2


@pytest.mark.parametrize("midi", [64, 69, 76])
def test_vocal_chop_sings_the_requested_note(midi):
    x = ins.vox(midi, 0.4, "a", vibrato=0.0)
    p, voicing = estimate_pitch(x[samples(0.1):samples(0.3)])
    assert voicing > 0.5
    assert p == pytest.approx(midi, abs=0.5)


def test_vowels_have_distinct_formants():
    a = ins.vox(60, 0.4, "a", vibrato=0.0)
    i = ins.vox(60, 0.4, "i", vibrato=0.0)
    # 'ee' has a high second formant (~2.1 kHz); 'ah' has energy near 1 kHz.
    def band(x, lo, hi):
        spec = np.abs(np.fft.rfft(x)) ** 2
        f = np.fft.rfftfreq(len(x), 1 / SR)
        return spec[(f >= lo) & (f < hi)].sum()
    assert band(i, 2000, 2800) / band(i, 700, 1300) > band(a, 2000, 2800) / band(a, 700, 1300)


def test_riser_gets_louder_and_brighter():
    r = ins.riser(2.0).mean(0)
    q = len(r) // 4
    assert rms(r[-q:]) > 4 * rms(r[:q])
