import numpy as np
import pytest

from radcat.arrangement import DEMO_FORM, Bar, Grid, demo_plan, plan_from_labels
from radcat.theory import Chord, Key


def test_fixed_grid_timing():
    g = Grid.fixed(120, 4)
    assert g.bpm == pytest.approx(120)
    assert g.t(0) == 0 and g.t(4) == pytest.approx(2.0)
    assert g.t(2.5) == pytest.approx(1.25)
    assert g.bar_time(2) == pytest.approx(4.0)
    assert g.step(1, 4) == pytest.approx(2.5)  # bar 2, beat 2
    assert g.beat_len(0) == pytest.approx(0.5)


def test_grid_extrapolates_past_both_ends():
    g = Grid.fixed(120, 1, offset=1.0)
    assert g.t(-2) == pytest.approx(0.0)
    assert g.t(6) == pytest.approx(4.0)
    assert np.allclose(g.t(np.array([0, 1])), [1.0, 1.5])


def test_swing_delays_only_off_eighth_sixteenths():
    g = Grid.fixed(120, 1)
    s16 = 0.125
    assert g.step(0, 2, swing=0.5) == pytest.approx(2 * s16 + 0.5 * s16)
    assert g.step(0, 4, swing=0.5) == pytest.approx(4 * s16)
    assert g.step(0, 3, swing=0.5) == pytest.approx(3 * s16)


def test_variable_grid_follows_given_beats():
    beats = np.cumsum([0, 0.5, 0.5, 0.52, 0.54, 0.56])
    g = Grid(beats)
    assert g.t(3) == pytest.approx(beats[3])
    assert g.t(3.5) == pytest.approx((beats[3] + beats[4]) / 2)


def test_grid_validation():
    with pytest.raises(ValueError):
        Grid([0.0])
    with pytest.raises(ValueError):
        Grid([0.0, 1.0, 0.5])


def test_demo_plan_form():
    plan = demo_plan(Key.parse("C"))
    assert len(plan) == sum(f[2] for f in DEMO_FORM) == 96
    secs = [s for s, *_ in plan.sections()]
    assert secs == ["intro", "verse", "build", "drop", "break", "verse", "build", "drop", "outro"]
    drop2 = [b for b in plan.bars if b.section == "drop" and b.variant == 2]
    assert len(drop2) == 16 and drop2[0].pos == 0 and drop2[-1].last
    assert plan.bars[32].chord == Chord.parse("Fmaj9")  # first drop opens on IV
    assert all(b.index == i for i, b in enumerate(plan.bars))


def test_demo_plan_transposes():
    a = demo_plan(Key.parse("C"))
    d = demo_plan(Key.parse("D"))
    assert all((y.chord.root - x.chord.root) % 12 == 2 for x, y in zip(a.bars, d.bars))


def test_plan_from_labels_runs_and_variants():
    labels = ["intro"] * 2 + ["verse"] * 4 + ["chorus"] * 4 + ["verse"] * 4 + ["chorus"] * 4 + ["outro"] * 2
    chords = [Chord(i % 12) for i in range(len(labels))]
    vocal = [lab in ("verse", "chorus") for lab in labels]
    plan = plan_from_labels(Key(0), labels, chords, vocal)
    runs = plan.sections()
    assert [(s, n, v) for s, _, n, v in runs] == [
        ("intro", 2, 1), ("verse", 4, 1), ("chorus", 4, 1), ("verse", 4, 2), ("chorus", 4, 2), ("outro", 2, 1)]
    assert plan.bars[6].pos == 0 and plan.bars[9].last and plan.bars[9].phrase_end
    assert plan.bars[3].vocal and not plan.bars[0].vocal
    with pytest.raises(ValueError):
        plan_from_labels(Key(0), labels, chords[:-1])


def test_bar_rejects_unknown_section():
    with pytest.raises(ValueError):
        Bar(0, "bridge", Chord(0))


def test_describe_lists_sections_with_times():
    plan = demo_plan(Key.parse("C"), title="T")
    text = plan.describe(Grid.fixed(155, len(plan)))
    assert text.startswith("T — key C major, 96 bars")
    assert "0:49.55  drop" in text
