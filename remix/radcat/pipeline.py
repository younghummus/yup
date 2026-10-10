"""End-to-end: (optional) source song -> analysis -> plan -> render -> files."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .arrangement import DEMO_FORM, Grid, Plan, demo_plan, plan_from_labels
from .dsp import encode, master_to, pitch_shift, samples, write_wav
from .midi import write_midi
from .render import ChopSampler, Remix
from .theory import Chord, Key

TITLE = "Mind Over Matter (Rad Cat Remix)"
ARTIST = "Young the Giant (Rad Cat-style remix, personal use)"
STEM_GROUPS = {
    "drums": ("kick", "snare", "hats", "perc"),
    "bass": ("bass",),
    "chords": ("chords", "pad"),
    "keys": ("keys", "pluck"),
    "chops": ("lead",),
    "fx": ("fx", "returns"),
    "vocal": ("vocal",),
}


@dataclass
class Options:
    source: str | None = None
    acapella: str | None = None
    vocal_method: str = "auto"     # auto | demucs | centre
    bpm: float | None = None       # demo tempo, or a hint for analysis
    key: str | None = None         # demo key, or override for analysis
    transpose: int = 0
    chops: str = "auto"            # auto | synth | real
    instrumental: bool = False
    out: str = "output"
    name: str = "mind-over-matter-rad-cat-remix"
    title: str = TITLE
    stems: bool = False
    midi: bool = True
    mp3: bool = True
    lufs: float = -9.0
    seed: int = 0
    form: tuple = DEMO_FORM


@dataclass
class Result:
    plan: Plan
    grid: Grid
    files: dict[str, Path] = field(default_factory=dict)
    report: str = ""
    seconds: float = 0.0


def _log(msg: str, quiet: bool):
    if not quiet:
        print(msg, flush=True)


def build(opts: Options, quiet: bool = False) -> tuple[Plan, Grid, np.ndarray | None, ChopSampler | None, list[str]]:
    """Analyse (source mode) or compose (demo mode) the plan; no audio rendered yet."""
    lines: list[str] = []
    if not opts.source:
        key = Key.parse(opts.key or "C").transpose(opts.transpose)
        bpm = opts.bpm or 155.0
        plan = demo_plan(key, opts.form, title=opts.title)
        grid = Grid.fixed(bpm, len(plan))
        lines.append(f"demo mode: original instrumental at {bpm:g} BPM in {key.name}")
        return plan, grid, None, None, lines

    from .analysis import analyse, vocal_grains  # heavy imports only when needed

    _log(f"analysing {opts.source} ...", quiet)
    a = analyse(opts.source, bpm_hint=opts.bpm, key_hint=Key.parse(opts.key) if opts.key else None,
                vocal_method=opts.vocal_method, acapella=opts.acapella)
    lines.append("source: " + a.summary())
    lines += [f"  note: {n}" for n in a.notes]
    key = a.key.transpose(opts.transpose)
    chords = [Chord(c.root + opts.transpose, c.quality) for c in a.chords]
    plan = plan_from_labels(key, a.labels, chords, list(map(bool, a.vocal_bars)), title=opts.title)
    grid = Grid(a.beats + a.offset)

    vocal = None
    chop = None
    if a.vocal is not None:
        if opts.chops in ("auto", "real"):
            chorus = [i for i, lab in enumerate(a.labels) if lab == "chorus" and a.vocal_bars[i]]
            pool = chorus or [i for i in range(a.n_bars) if a.vocal_bars[i]]
            grains = vocal_grains(a.vocal, a.bar_times, pool)
            if grains:  # each chop is re-pitched to its target note, so transpose needs nothing
                chop = ChopSampler(grains)
                lines.append(f"chops: {len(grains)} syllables cut from the real vocal")
            elif opts.chops == "real":
                raise RuntimeError("no clearly pitched vocal syllables found to chop; use --chops synth")
        if not opts.instrumental:
            v = a.vocal
            if opts.transpose:
                v = pitch_shift(v, opts.transpose)
            pad = samples(a.offset)
            vocal = np.concatenate([np.zeros((2, pad)), v], axis=1) if pad else v
    return plan, grid, vocal, chop, lines


def run(opts: Options, quiet: bool = False) -> Result:
    t0 = time.time()
    plan, grid, vocal, chop, lines = build(opts, quiet)
    _log("\n".join(lines), quiet)
    _log(plan.describe(grid), quiet)
    _log("rendering ...", quiet)
    remix = Remix(plan, grid, seed=opts.seed, vocal=vocal, chop_source=chop)
    stems = remix.render()
    out = Path(opts.out)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    master = master_to(stems["master"], opts.lufs, ceiling_db=-1.5)
    wav = write_wav(out / f"{opts.name}.wav", master)
    files["wav"] = wav
    if opts.mp3:
        files["mp3"] = encode(wav, out / f"{opts.name}.mp3", title=opts.title, artist=ARTIST)
    if opts.midi:
        files["midi"] = write_midi(out / f"{opts.name}.mid", remix.notes, grid.bpm, opts.title)
    if opts.stems:
        for group, members in STEM_GROUPS.items():
            x = sum(stems[m] for m in members)
            if np.max(np.abs(x)) > 1e-6:
                files[f"stem:{group}"] = write_wav(out / "stems" / f"{opts.name}-{group}.wav", np.clip(x, -1, 1))
    report = "\n".join(lines + [plan.describe(grid)])
    rep = out / f"{opts.name}.txt"
    rep.write_text(report + "\n")
    files["report"] = rep
    dt = time.time() - t0
    _log(f"done in {dt:.0f}s: " + ", ".join(str(p) for p in files.values()), quiet)
    return Result(plan, grid, files, report, dt)
