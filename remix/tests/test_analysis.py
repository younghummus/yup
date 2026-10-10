"""Analysis accuracy against synthetic recordings with exact ground truth."""
import numpy as np
import pytest

from fixtures import make_song
from radcat import analysis as an
from radcat import instruments as ins
from radcat.dsp import SR, pan, samples, write_wav
from radcat.theory import Chord, Key


def nearest_errors(found, truth):
    return np.array([found[np.argmin(np.abs(found - t))] - t for t in truth])


def test_tempo_key_and_beats(analysis_150, song_150):
    a, truth = analysis_150, song_150[4]
    assert a.bpm == pytest.approx(150.0, abs=0.1)
    assert a.key == Key.parse("C")
    err = nearest_errors(a.beats, truth["beats"])
    assert np.median(np.abs(err)) < 0.003
    assert np.max(np.abs(err)) < 0.010


def test_bars_start_on_downbeats_with_a_pickup_bar(analysis_150, song_150):
    a, truth = analysis_150, song_150[4]
    # 1.3 s lead-in at 150 BPM = 3.25 beats, so bar 1 is a pickup starting before t=0.
    assert a.bar_times[0] < 0 < a.bar_times[1]
    assert a.offset == pytest.approx(-a.bar_times[0])
    downbeats = truth["beats"][::4][:-1]
    assert np.max(np.abs(a.bar_times[1:1 + len(downbeats)] - downbeats)) < 0.010


def test_chords_vocal_and_sections(analysis_150, song_150):
    a, truth = analysis_150, song_150[4]
    n = len(truth["chords"])
    assert a.chords[1:1 + n] == truth["chords"]
    assert list(a.vocal_bars[1:1 + n]) == truth["vocal"]
    labels = a.labels[1:1 + n]
    assert set(labels[:4]) == {"intro"}
    assert set(labels[4:8]) == {"verse"}
    assert set(labels[8:12]) == {"build"}  # the phrase before the chorus becomes the build-up
    assert set(labels[12:20]) == {"chorus"}
    assert set(labels[20:]) == {"outro"}


@pytest.mark.parametrize("bpm,lead", [(96.0, 0.6), (128.0, 0.0), (170.0, 0.81)])
def test_tempo_range(tmp_path, bpm, lead):
    mix, _, truth = make_song(bpm, lead)
    a = an.analyse(write_wav(tmp_path / "s.wav", mix), vocal_method="centre")
    assert a.bpm == pytest.approx(bpm, abs=0.1)
    assert np.max(np.abs(nearest_errors(a.bar_times, truth["beats"][::4]))) < 0.010


def test_follows_a_drifting_live_tempo(tmp_path):
    mix, _, truth = make_song(155.0, 0.5, bpm_end=149.0)
    a = an.analyse(write_wav(tmp_path / "d.wav", mix), vocal_method="centre")
    err = nearest_errors(a.beats, truth["beats"])
    assert np.median(np.abs(err)) < 0.005
    assert np.max(np.abs(err)) < 0.035


def test_bpm_hint_picks_the_octave():
    env = np.zeros(4000)
    period = 60 * an.ASR / an.HOP / 150.0
    env[np.round(np.arange(0, 3990, period)).astype(int)] = 1.0
    assert an.estimate_tempo(env, hint=75) == pytest.approx(75, rel=0.02)
    assert an.estimate_tempo(env, hint=150) == pytest.approx(150, rel=0.02)


def test_key_detection_major_and_minor():
    def chroma(pcs):
        c = np.full(12, 0.1)
        for p, w in pcs:
            c[p % 12] += w
        return c
    c_major = chroma([(0, 3), (4, 2), (7, 2.5), (5, 1), (9, 1), (2, 1), (11, 0.6)])
    a_minor = chroma([(9, 3), (0, 2), (4, 2.5), (2, 1), (5, 1), (7, 0.7), (11, 0.6)])
    assert an.detect_key(c_major) == Key.parse("C")
    assert an.detect_key(a_minor) == Key.parse("Am")


def test_chord_detection_prefers_stable_diatonic_path():
    key = Key.parse("C")
    seq = [Chord.parse(c) for c in ("C", "C", "F", "G", "Am", "Am")]
    C = np.zeros((12, len(seq)))
    B = np.zeros((12, len(seq)))
    for i, ch in enumerate(seq):
        for pc in ch.pcs:
            C[pc, i] = 1.0
        B[ch.root, i] = 1.0
    C += 0.05
    assert an.detect_chords(C, B, key) == seq


def test_label_sections_rules():
    energy = np.array([-20] * 4 + [-16] * 8 + [-11] * 8 + [-11] * 4 + [-22] * 4, float)
    vocal = np.array([0] * 4 + [1] * 16 + [0] * 8, float)
    labels = an.label_sections(energy, vocal)
    assert labels == ["intro"] * 4 + ["verse"] * 4 + ["build"] * 4 + ["chorus"] * 8 + ["drop"] * 4 + ["outro"] * 4


def test_pitch_estimation():
    for midi in (57, 64, 72, 79):
        x = ins.vox(midi, 0.2, "a", vibrato=0.0)
        p, v = an.estimate_pitch(x[samples(0.05):samples(0.15)])
        assert p == pytest.approx(midi, abs=0.4) and v > 0.5
    assert an.estimate_pitch(np.zeros(4000)) == (0.0, 0.0)


def test_centre_extraction_keeps_the_middle_and_drops_the_sides():
    t = np.arange(SR * 2) / SR
    voice = ins.vox(69, 2.0, "a")
    guitar = np.sin(2 * np.pi * 330 * t) * 0.5
    mix = pan(voice, 0.0) + pan(guitar, -1.0) * 0.8
    v = an.centre_vocals(mix)

    def corr(a, b):
        return abs(np.corrcoef(a, b)[0, 1])
    assert corr(v[0], voice) > 0.8
    assert corr(v[0], guitar) < 0.2


def test_vocal_grains_are_pitched_syllables(analysis_150, song_150):
    vocal = song_150[3]
    a = analysis_150
    grains = an.vocal_grains(vocal, a.bar_times, [i for i in range(a.n_bars) if a.vocal_bars[i]])
    assert 3 <= len(grains) <= 8
    for g, p in grains:
        assert len(g) == samples(0.32)
        assert 60 <= p <= 80  # the fixture sings E4-E5


def test_active_span():
    x = np.zeros((2, SR * 3))
    x[:, SR:2 * SR] = 0.5
    on, off = an.active_span(x)
    assert on == pytest.approx(1.0, abs=0.05) and off == pytest.approx(2.0, abs=0.05)


def test_acapella_input_is_used(tmp_path, song_150):
    path, vpath, *_ = song_150
    a = an.analyse(path, acapella=vpath)
    assert a.vocal_method == "acapella"
    assert a.vocal.shape[1] == pytest.approx(song_150[3].shape[1], abs=2)
