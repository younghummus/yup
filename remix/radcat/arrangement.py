"""Tempo grid and song structure.

A `Plan` is a list of bars, each tagged with a section (intro, verse, build, drop, chorus,
break, outro) and a chord. The demo plan is a hand-written Rad Cat-style form; source
mode builds the plan bar-for-bar from the original song so the real vocal lines up.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .theory import Chord, Key, default_progressions

SECTIONS = ("intro", "verse", "build", "drop", "chorus", "break", "outro")


class Grid:
    """Maps beats (float, 4 per bar) to seconds. Built from explicit beat times so a
    remix can follow a live band's drifting tempo, not just a fixed BPM."""

    def __init__(self, beat_times, beats_per_bar: int = 4):
        bt = np.asarray(beat_times, dtype=np.float64)
        if bt.ndim != 1 or len(bt) < 2 or np.any(np.diff(bt) <= 0):
            raise ValueError("beat_times must be >= 2 strictly increasing times")
        self.beats = bt
        self.bpb = beats_per_bar

    @classmethod
    def fixed(cls, bpm: float, n_bars: int, offset: float = 0.0, beats_per_bar: int = 4) -> "Grid":
        n = n_bars * beats_per_bar + 1
        return cls(offset + np.arange(n) * 60.0 / bpm, beats_per_bar)

    @property
    def bpm(self) -> float:
        return 60.0 / float(np.median(np.diff(self.beats)))

    def t(self, beat) -> np.ndarray | float:
        """Seconds at (fractional) beat index; extrapolates linearly past either end."""
        b = np.asarray(beat, dtype=np.float64)
        idx = np.arange(len(self.beats))
        out = np.interp(b, idx, self.beats)
        lo_d, hi_d = self.beats[1] - self.beats[0], self.beats[-1] - self.beats[-2]
        out = np.where(b < 0, self.beats[0] + b * lo_d, out)
        out = np.where(b > idx[-1], self.beats[-1] + (b - idx[-1]) * hi_d, out)
        return float(out) if np.ndim(out) == 0 else out

    def step(self, bar: int, step: float, swing: float = 0.0) -> float:
        """Seconds at a 16th-note step of a bar. `swing` delays the off-8th 16ths
        (steps 2, 6, 10, 14) by that fraction of a 16th."""
        s = step + (swing if (int(step) % 4 == 2 and float(step).is_integer()) else 0.0)
        return self.t(bar * self.bpb + s / 4.0)

    def beat_len(self, bar: int = 0) -> float:
        b = bar * self.bpb
        return self.t(b + 1) - self.t(b)

    def bar_time(self, bar: int) -> float:
        return self.t(bar * self.bpb)


@dataclass
class Bar:
    index: int
    section: str
    chord: Chord
    pos: int = 0          # bar number within its section
    length: int = 1       # bars in this section
    variant: int = 1      # 1st or 2nd occurrence of this section type
    vocal: bool = False   # the original vocal is singing in this bar (source mode)

    def __post_init__(self):
        if self.section not in SECTIONS:
            raise ValueError(f"unknown section {self.section!r}")

    @property
    def last(self) -> bool:
        return self.pos == self.length - 1

    @property
    def phrase_end(self) -> bool:
        return self.pos % 4 == 3 or self.last


@dataclass
class Plan:
    key: Key
    bars: list[Bar] = field(default_factory=list)
    title: str = ""

    def __len__(self) -> int:
        return len(self.bars)

    def sections(self) -> list[tuple[str, int, int, int]]:
        """(section, first bar, n bars, variant) runs."""
        out: list[tuple[str, int, int, int]] = []
        for b in self.bars:
            if out and out[-1][0] == b.section and b.pos != 0:
                s, start, n, v = out[-1]
                out[-1] = (s, start, n + 1, v)
            else:
                out.append((b.section, b.index, 1, b.variant))
        return out

    def describe(self, grid: Grid | None = None) -> str:
        lines = [f"{self.title or 'Remix'} — key {self.key.name}, {len(self)} bars"]
        for s, start, n, v in self.sections():
            when = ""
            if grid is not None:
                t = grid.bar_time(start)
                when = f"{int(t // 60)}:{t % 60:05.2f}  "
            chords = " ".join(dict.fromkeys(b.chord.name for b in self.bars[start:start + n]))
            lines.append(f"  {when}{s:<7} x{n:<3} bars {start + 1:>3}-{start + n:<3} {chords}")
        return "\n".join(lines)


def _section_bars(start: int, section: str, chords: list[Chord], n: int, variant: int = 1) -> list[Bar]:
    return [Bar(start + i, section, chords[i % len(chords)], i, n, variant) for i in range(n)]


# The demo form: (section, progression, bars, variant). 96 bars ≈ 2:29 at 155 BPM.
DEMO_FORM = (
    ("intro", "drop", 8, 1),
    ("verse", "verse", 16, 1),
    ("build", "drop", 8, 1),
    ("drop", "drop", 16, 1),
    ("break", "break", 8, 1),
    ("verse", "verse", 8, 2),
    ("build", "drop", 8, 2),
    ("drop", "drop2", 16, 2),
    ("outro", "drop", 8, 1),
)


def demo_plan(key: Key, form=DEMO_FORM, title: str = "") -> Plan:
    progs = default_progressions(key)
    plan = Plan(key, title=title)
    for section, prog, n, variant in form:
        plan.bars += _section_bars(len(plan.bars), section, progs[prog], n, variant)
    return plan


def plan_from_labels(key: Key, labels: list[str], chords: list[Chord], vocal: list[bool] | None = None,
                     title: str = "") -> Plan:
    """Build a plan from per-bar section labels (source mode)."""
    if len(labels) != len(chords):
        raise ValueError("labels and chords must have one entry per bar")
    vocal = vocal or [False] * len(labels)
    plan = Plan(key, title=title)
    runs: list[tuple[str, int, int]] = []
    for i, lab in enumerate(labels):
        if runs and runs[-1][0] == lab:
            runs[-1] = (lab, runs[-1][1], runs[-1][2] + 1)
        else:
            runs.append((lab, i, 1))
    seen: dict[str, int] = {}
    for lab, start, n in runs:
        seen[lab] = seen.get(lab, 0) + 1
        variant = 2 if seen[lab] % 2 == 0 else 1
        for i in range(n):
            plan.bars.append(Bar(start + i, lab, chords[start + i], i, n, variant, vocal[start + i]))
    return plan
