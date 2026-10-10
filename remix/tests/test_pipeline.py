"""End-to-end: CLI options -> files on disk, demo and source modes."""
import numpy as np
import pytest
from scipy import signal as sps

import remix as cli
from radcat.dsp import SR, loudness, read_audio, true_peak
from radcat.midi import read_midi_summary
from radcat.pipeline import Options, run


def test_cli_parsing():
    o = cli.parse(["--bpm", "150", "--key", "Am", "--stems", "--no-mp3", "--transpose", "-2"])
    assert (o.bpm, o.key, o.stems, o.mp3, o.transpose, o.source) == (150.0, "Am", True, False, -2, None)
    with pytest.raises(SystemExit):
        cli.parse(["--acapella", "v.wav"])


def test_demo_mode_writes_everything(tmp_path, short_form):
    r = run(Options(out=str(tmp_path), name="demo", stems=True, form=short_form, lufs=-10.0), quiet=True)
    f = r.files
    for k in ("wav", "mp3", "midi", "report", "stem:drums", "stem:bass", "stem:chords", "stem:chops"):
        assert f[k].exists() and f[k].stat().st_size > 0, k
    assert "stem:vocal" not in f  # nothing to write in demo mode
    wav = read_audio(f["wav"])
    assert wav.shape[1] / SR == pytest.approx(r.grid.bar_time(len(r.plan)) + 4.0, abs=0.05)
    assert true_peak(wav) <= 10 ** (-1 / 20) + 1e-3
    assert loudness(f["mp3"]) == pytest.approx(-10.0, abs=1.0)
    midi = read_midi_summary(f["midi"])
    assert midi["tempo"] == pytest.approx(155.0, rel=1e-3)
    assert {t["name"] for t in midi["tracks"]} >= {"chords", "chops", "bass", "drums", "keys", "pluck"}
    assert "demo mode" in f["report"].read_text()


def test_demo_key_and_tempo_options(tmp_path, short_form):
    r = run(Options(out=str(tmp_path), name="k", key="Am", bpm=140, mp3=False, midi=False, form=short_form),
            quiet=True)
    assert r.plan.key.name == "A minor"
    assert r.grid.bpm == pytest.approx(140)


def test_source_mode_end_to_end(tmp_path, song_150):
    path, _, mix, vocal, truth = song_150
    r = run(Options(source=str(path), vocal_method="centre", out=str(tmp_path), name="src", stems=True,
                    mp3=False), quiet=True)
    assert "150.0 BPM" in r.report and "C major" in r.report
    assert "chops:" in r.report  # chops were cut from the real vocal
    sections = [s for s, *_ in r.plan.sections()]
    assert sections == ["intro", "verse", "build", "chorus", "outro"]
    # The remixed vocal must land exactly where the grid says: original time + offset.
    v = read_audio(r.files["stem:vocal"])[0]
    n = min(len(v), vocal.shape[1])
    c = sps.correlate(v[:n], vocal[0, :n], mode="full", method="fft")
    lag = (np.argmax(c) - (n - 1)) / SR
    offset = r.grid.beats[0] * -1 if r.grid.beats[0] < 0 else 0.0
    expected = r.grid.bar_time(1) - truth["beats"][0]  # bar 2 = the song's first downbeat
    assert lag == pytest.approx(expected, abs=0.003)
    assert offset == 0.0  # grid was shifted so the pickup bar starts at t >= 0


def test_source_mode_instrumental_and_transpose(tmp_path, song_150):
    path = song_150[0]
    r = run(Options(source=str(path), vocal_method="centre", out=str(tmp_path), name="t", transpose=2,
                    instrumental=True, chops="synth", mp3=False, midi=False, stems=True), quiet=True)
    assert r.plan.key.name == "D major"
    assert r.plan.bars[1].chord.name == "D"
    assert "stem:vocal" not in r.files
    assert "chops:" not in r.report
