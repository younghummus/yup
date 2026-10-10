import numpy as np
import pytest

from radcat import instruments as ins
from radcat.analysis import estimate_pitch
from radcat.arrangement import Grid, demo_plan
from radcat.dsp import SR, db, rms, samples, true_peak
from radcat.render import BUSES, ChopSampler, Remix, bass_note, hook_for
from radcat.theory import Chord, Key


@pytest.fixture(scope="module")
def short_render(short_form):
    plan = demo_plan(Key.parse("C"), short_form)
    grid = Grid.fixed(155, len(plan))
    remix = Remix(plan, grid, seed=1)
    stems = remix.render()
    return plan, grid, remix, stems


def test_hook_uses_chord_tones_in_range():
    chords = [Chord.parse(c) for c in ("Fmaj9", "G6", "Em7", "Am9")] * 2
    hook = hook_for(chords)
    assert len(hook) == len(chords)
    for ch, bar in zip(chords, hook):
        pcs = ch.flavoured().pcs
        assert all(n.midi % 12 in pcs and 64 <= n.midi <= 81 for n in bar)
        assert all(0 <= n.step < 16 and n.step + n.length <= 16 for n in bar)
    assert hook[3][-1].slide and not hook[2][-1].slide  # pitched-up yip ends each 4-bar phrase
    assert hook_for(chords)[5][2].midi == hook[5][2].midi  # deterministic


def test_bass_register():
    for r in range(12):
        assert 33 <= bass_note(Chord(r)) <= 44


def test_render_produces_every_stem(short_render):
    plan, grid, remix, stems = short_render
    for name in (*BUSES, "returns", "master"):
        assert stems[name].shape == (2, remix.n)
        assert np.all(np.isfinite(stems[name]))
    for name in ("kick", "snare", "hats", "bass", "chords", "keys", "pluck", "lead", "pad", "fx"):
        assert rms(stems[name]) > 1e-4, name
    assert not np.any(stems["vocal"])  # demo mode: no source vocal


def test_master_is_limited_and_loud(short_render):
    *_, stems = short_render
    m = stems["master"]
    assert true_peak(m) <= db(-1.0) + 1e-6
    assert 20 * np.log10(rms(m)) > -20


def test_drop_is_louder_than_break(short_render):
    plan, grid, _, stems = short_render
    m = stems["master"]

    def section_rms(name, variant=1):
        bars = [b.index for b in plan.bars if b.section == name and b.variant == variant]
        s, e = samples(grid.bar_time(bars[0])), samples(grid.bar_time(bars[-1] + 1))
        return rms(m[:, s:e])
    assert section_rms("drop") > 1.5 * section_rms("break")


def test_sidechain_pumps_the_chords(short_render):
    plan, grid, remix, stems = short_render
    drop = [b.index for b in plan.bars if b.section == "drop"][1]
    s, e = samples(grid.bar_time(drop)), samples(grid.bar_time(drop + 1))
    kicks = [k for k in remix.kicks if s <= k < e]
    assert kicks
    ch = np.abs(stems["chords"]).max(axis=0)
    at_kick = np.mean([ch[k: k + samples(0.02)].mean() for k in kicks])
    between = np.mean([ch[k + samples(0.25): k + samples(0.3)].mean() for k in kicks])
    assert at_kick < 0.6 * between


def test_midi_notes_cover_every_part(short_render):
    _, _, remix, _ = short_render
    tracks = {n.track for n in remix.notes}
    assert tracks == {"drums", "bass", "chords", "keys", "pluck", "chops"}
    assert all(n.beats > 0 and 0 <= n.midi <= 127 for n in remix.notes)


def test_vocal_is_mixed_and_chops_duck_under_it(short_form):
    plan = demo_plan(Key.parse("C"), short_form)
    grid = Grid.fixed(155, len(plan))
    n = samples(grid.bar_time(len(plan)))
    vocal = np.zeros((2, n))
    # A held sung note over the first drop, nowhere else.
    drop = [b.index for b in plan.bars if b.section == "drop"]
    s, e = samples(grid.bar_time(drop[0])), samples(grid.bar_time(drop[3] + 1))
    vocal[:, s:e] = ins.vox(67, (e - s) / SR, "a", attack=0.05, release=0.05) * 0.3
    with_v = Remix(plan, grid, vocal=vocal).render()
    without = Remix(plan, grid).render()
    assert rms(with_v["vocal"][:, s:e]) > 0.02
    assert rms(with_v["lead"][:, s:e]) < 0.6 * rms(without["lead"][:, s:e])


def test_chop_sampler_repitches_grains():
    grain = ins.vox(60, 0.35, "a", vibrato=0.0, shift=1.0)
    cs = ChopSampler([(grain, 60.0)])
    for target in (64, 67, 72):
        x = cs.note(target, 0.2)
        assert len(x) == samples(0.2)
        p, v = estimate_pitch(x[samples(0.02):samples(0.15)])
        assert p == pytest.approx(target, abs=0.5)
    with pytest.raises(ValueError):
        ChopSampler([])


def test_seed_changes_texture_not_structure(short_form):
    plan = demo_plan(Key.parse("C"), short_form)
    grid = Grid.fixed(155, len(plan))
    a, b = Remix(plan, grid, seed=1), Remix(plan, grid, seed=2)
    sa, sb = a.render(), b.render()
    assert [(n.track, n.beat, n.midi) for n in a.notes] == [(n.track, n.beat, n.midi) for n in b.notes]
    assert not np.allclose(sa["chords"], sb["chords"])
