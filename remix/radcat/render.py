"""The producer: turns a Plan + Grid into stems and a mastered stereo mix.

Rad Cat's sound, as he describes it, is "R&B and upbeat house music having a child":
future bass supersaw chords that pump against the kick, hip-hop / trap drums in a
half-time feel, sub and 808 bass, warm R&B keys, a melody-first chopped vocal hook,
and big build-ups with risers into each drop. Each section below maps onto that.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import instruments as ins
from .arrangement import Bar, Grid, Plan
from .dsp import (Bus, compress, db, delay, fade, filt, limit, mono_below, reverb, reverb_ir, samples, saturate,
                  sidechain_curve, sweep, width)
from .theory import Chord, voice_lead

BUSES = ("kick", "snare", "hats", "perc", "bass", "chords", "keys", "pluck", "lead", "pad", "fx", "vocal")

# Chop hook: 16th-note (step, length) rhythms and chord-tone contours, two bars long.
HOOK_RHYTHMS = (
    ((0, 2), (3, 1), (4, 2), (7, 1), (8, 2), (10, 2), (12, 3)),
    ((0, 2), (3, 2), (6, 2), (8, 1), (10, 1), (11, 1), (12, 4)),
)
HOOK_CONTOURS = ((0, 1, 0, -1, 0, 1, 2), (1, 0, -1, -2, -1, 0, -1))
HOOK_VOWELS = (("a", "a", "o", "e", "a", "u", "o"), ("o", "a", "e", "a", "i", "a", "u"))

# Drum grooves (16th steps). Two-bar patterns, index by bar parity.
GROOVES = {
    "verse": {"kick": ((0, 10), (0, 7, 10)), "snare": (8,), "ghost": ((), (15,)), "rim": ((), (12,)),
              "swing": 0.22, "level": 0.6},
    "drop": {"kick": ((0, 10), (0, 3, 10, 14)), "snare": (8,), "ghost": ((), ()), "rim": ((), ()),
             "swing": 0.0, "ohat": (6, 14), "level": 1.0},
}


@dataclass
class Note:
    track: str
    beat: float
    beats: float
    midi: int
    vel: float = 0.8


@dataclass
class ChopNote:
    step: float
    length: float
    midi: int
    vowel: str
    slide: bool = False


def hook_for(chords: list[Chord], low: int = 64, high: int = 81, anchor: float = 72.0) -> list[list[ChopNote]]:
    """Melody-first chop hook: a fixed rhythmic/contour motif mapped onto each bar's
    chord tones, so it sequences through the progression the way a producer would
    re-pitch a vocal chop to every chord."""
    out = []
    for i, ch in enumerate(chords):
        r = i % 2
        pool = ch.flavoured().tones(low, high)
        base = min(range(len(pool)), key=lambda k: abs(pool[k] - anchor))
        bar = []
        for k, (step, length) in enumerate(HOOK_RHYTHMS[r]):
            idx = int(np.clip(base + HOOK_CONTOURS[r][k], 0, len(pool) - 1))
            bar.append(ChopNote(step, length, pool[idx], HOOK_VOWELS[r][k]))
        if i % 4 == 3:
            bar[-1].slide = True
        anchor = 0.6 * anchor + 0.4 * pool[base]
        out.append(bar)
    return out


def bass_note(ch: Chord, low: int = 33) -> int:
    """Chord root in the 808 register (A1..G#2)."""
    return low + (ch.root - low) % 12


class Remix:
    def __init__(self, plan: Plan, grid: Grid, seed: int = 0, vocal: np.ndarray | None = None,
                 chop_source: "ChopSampler | None" = None, tail: float = 4.0):
        self.plan, self.grid, self.seed = plan, grid, seed
        self.end_t = grid.bar_time(len(plan))
        self.n = samples(self.end_t + tail)
        self.bus = {k: Bus(self.n) for k in BUSES}
        self.kicks: list[int] = []
        self.pumps: list[int] = []
        self.notes: list[Note] = []
        self.vocal = vocal
        self.chops = chop_source
        self.automation: list[tuple[str, int, int, float, float]] = []
        self.hook = hook_for([b.chord for b in plan.bars])
        self._voicing: list[int] | None = None
        self._last_bass: int | None = None
        self._last_chop: int | None = None

    # ------------------------------------------------------------- timing
    def at(self, bar: int, step: float, swing: float = 0.0) -> int:
        return samples(self.grid.step(bar, step, swing))

    def dur(self, bar: int, step: float, length: float) -> float:
        return self.grid.step(bar, step + length) - self.grid.step(bar, step)

    def beat(self, bar: int, step: float) -> float:
        return bar * self.grid.bpb + step / 4.0

    def _note(self, track: str, bar: int, step: float, length: float, midi: int, vel: float = 0.8):
        self.notes.append(Note(track, self.beat(bar, step), length / 4.0, int(midi), vel))

    # ------------------------------------------------------------- render
    def render(self) -> dict[str, np.ndarray]:
        for b in self.plan.bars:
            self._bar(b)
        for section, start, n, variant in self.plan.sections():
            self._section_fx(section, start, n, variant)
        self._apply_automation()
        return self.mix()

    def _bar(self, b: Bar):
        s = b.section
        drop_like = s in ("drop", "chorus")
        self._voicing = voice_lead(self._voicing, b.chord.flavoured(), center=64,
                                   spread=2 if drop_like else 0)
        if s == "intro":
            self._chords_sustain(b, bright=0.18 + 0.35 * b.pos / max(1, b.length - 1))
            if b.pos % 2 == 1:
                self._chops(b, gain=0.35, only_last=True)
            if b.pos >= b.length - 2:
                self._hats(b, swing=0.0, vel=0.35)
                self._snap(b, (8,))
        elif s == "verse":
            self._groove(b, "verse")
            self._bass(b, "verse")
            self._keys(b)
            if b.variant == 2:
                self._pad(b, gain=0.5)
                self._shaker(b)
            if not b.vocal:
                self._topline(b)
        elif s == "build":
            self._build(b)
        elif drop_like:
            self._groove(b, "drop")
            self._bass(b, "drop")
            self._drop_chords(b)
            self._chops(b, gain=0.55 if b.vocal else 1.0, octave=(b.variant == 2 and not b.vocal))
            if b.variant == 2 or b.pos >= b.length // 2:
                self._arp(b)
        elif s == "break":
            self._keys(b, sustain=True)
            self._choir(b)
            self._snap(b, (8,) if b.pos < b.length - 2 else (8, 12))
            if b.pos % 2 == 0:
                self._chops(b, gain=0.35, only_last=True)
        elif s == "outro":
            self._chords_sustain(b, bright=0.6 * (1 - b.pos / max(1, b.length)) + 0.08)
            if b.pos < b.length // 2:
                self._groove(b, "drop", fill=False)
                self._bass(b, "drop")
            if b.pos < b.length - 1:
                self._chops(b, gain=0.6 * (1 - b.pos / b.length) + 0.15)

    # ---------------------------------------------------------- drums
    def _kick(self, bar: int, step: float, vel: float = 1.0, pump: bool = True):
        i = self.at(bar, step)
        self.bus["kick"].add(ins.kick(), i, vel)
        self.kicks.append(i)
        if pump:
            self.pumps.append(i)
        self._note("drums", bar, step, 1, 36, vel)

    def _groove(self, b: Bar, style: str, fill: bool = True):
        g = GROOVES[style]
        par = b.pos % 2
        lv = g["level"]  # verses sit a few dB under the drop so the drop hits
        for st in g["kick"][par]:
            self._kick(b.index, st, lv * (1.0 if st == 0 else 0.85))
        if style == "drop":
            for q in (4, 8, 12):  # ghost sidechain on every beat: the future bass pump
                self.pumps.append(self.at(b.index, q))
        for st in g["snare"]:
            i = self.at(b.index, st)
            self.bus["snare"].add(ins.clap(), i, 0.9 * lv)
            self.bus["snare"].add(ins.snare(), i, 0.55 * lv)
            self._note("drums", b.index, st, 1, 39, 1.0)
        for st in g["ghost"][par]:
            self.bus["snare"].add(ins.snare(0.15), self.at(b.index, st), 0.22)
        for st in g["rim"][par]:
            self.bus["perc"].add(ins.rim(), self.at(b.index, st), 0.35, 0.3)
            self._note("drums", b.index, st, 1, 37, 0.5)
        roll = fill and (b.pos % 2 == 1 or b.phrase_end)
        self._hats(b, swing=g["swing"], vel=0.6 if style == "verse" else 0.75,
                   roll="triplet" if (roll and style == "drop") else ("32nd" if roll and b.phrase_end else None))
        for st in g.get("ohat", ()):
            self.bus["hats"].add(ins.hat(True), self.at(b.index, st), 0.32, -0.2)
            self._note("drums", b.index, st, 1, 46, 0.5)
        if b.pos == 0 and style == "drop":
            self.bus["fx"].add(ins.crash(), self.at(b.index, 0), 0.5)

    def _hats(self, b: Bar, swing: float, vel: float, roll: str | None = None):
        steps = list(range(0, 16, 2))
        rolls: list[float] = []
        if roll == "triplet":
            steps = [s for s in steps if s < 12]
            rolls = [12 + k * 2 / 3 for k in range(6)]
        elif roll == "32nd":
            steps = [s for s in steps if s < 14]
            rolls = [14 + k * 0.5 for k in range(4)]
        for st in steps:
            accent = 1.0 if st % 4 == 0 else 0.7
            p = 0.25 if st % 4 == 0 else 0.35
            self.bus["hats"].add(ins.hat(), self.at(b.index, st, swing), vel * accent, p)
            self._note("drums", b.index, st, 1, 42, vel * accent)
        for k, st in enumerate(rolls):
            i = samples(self.grid.step(b.index, st))
            self.bus["hats"].add(ins.hat(), i, vel * (0.45 + 0.4 * k / max(1, len(rolls) - 1)), 0.3)
            self._note("drums", b.index, st, 0.5, 42, 0.6)

    def _snap(self, b: Bar, steps):
        for st in steps:
            self.bus["snare"].add(ins.snap(), self.at(b.index, st), 0.5)
            self._note("drums", b.index, st, 1, 39, 0.5)

    def _shaker(self, b: Bar):
        for st in range(16):
            v = 0.32 if st % 2 else 0.18
            self.bus["perc"].add(ins.shaker(), self.at(b.index, st, 0.25), v, -0.35)

    # ---------------------------------------------------------- bass
    def _bass(self, b: Bar, style: str):
        pattern = GROOVES[style]["kick"][b.pos % 2]
        root = bass_note(b.chord)
        steps = list(pattern) + [16]
        for k, st in enumerate(steps[:-1]):
            length = steps[k + 1] - st
            midi = root
            if style == "drop" and b.phrase_end and k == len(steps) - 2:
                midi = root + 12  # octave pop at the end of the phrase
            d = self.dur(b.index, st, length)
            i = self.at(b.index, st)
            glide = self._last_bass if self._last_bass is not None and abs(self._last_bass - midi) <= 12 else None
            if style == "drop":
                x = ins.bass808(midi, d + 0.05, glide_from=glide if glide != midi else None)
                self.bus["bass"].add(x, i, 0.85)
            else:
                x = ins.sub(midi, d, glide_from=glide if glide != midi else None)
                self.bus["bass"].add(x, i, 0.5)
            self._note("bass", b.index, st, length, midi, 0.9)
            self._last_bass = midi

    # ---------------------------------------------------------- harmony
    def _drop_chords(self, b: Bar):
        notes = self._voicing
        wobble = b.variant == 2 and b.pos < b.length // 2
        if wobble:
            hits = ((0, 16),)
        elif b.phrase_end:
            hits = ((0, 6), (6, 10))
        else:
            hits = ((0, 6), (6, 6), (12, 4))  # 3-3-2 tresillo
        for k, (st, length) in enumerate(hits):
            d = self.dur(b.index, st, length)
            scoop = 7.0 if (b.pos == 0 and k == 0) else (0.6 if k == 0 else 0.0)
            x = ins.future_chord(notes, d, scoop=scoop, seed=self.seed + b.index * 7 + k,
                                 wobble_hz=(2 / self.grid.beat_len(b.index)) if wobble else 0.0,
                                 wobble_depth=0.8 if wobble else 0.0)
            self.bus["chords"].add(x, self.at(b.index, st), 0.75)
            for m in notes:
                self._note("chords", b.index, st, length, m, 0.85)
        # Warm sub-octave root layer glued under the stack (low-passed, faded per bar).
        root = bass_note(b.chord) + 12
        layer = ins.supersaw(root, self.dur(b.index, 0, 16), voices=3, detune=0.08)
        layer = fade(filt(layer, "lowpass", 900.0, order=2), 0.004, 0.02)
        self.bus["chords"].add(layer * 0.3, self.at(b.index, 0))

    def _chords_sustain(self, b: Bar, bright: float):
        d = self.dur(b.index, 0, 16)
        notes = self._voicing
        c = (400 + 1500 * bright, 900 + 9000 * bright, 600 + 5000 * bright)
        x = ins.future_chord(notes, d + 0.05, cutoff=c, attack=0.03, release=0.12, seed=self.seed + b.index, air=0.04)
        self.bus["chords"].add(x, self.at(b.index, 0), 0.45)
        for m in notes:
            self._note("chords", b.index, 0, 16, m, 0.6)

    def _keys(self, b: Bar, sustain: bool = False):
        voicing = voice_lead(None, b.chord.flavoured(), center=60)
        gain = 0.15 if sustain else 0.17
        if sustain:
            hits = ((0, 16, 0.75),)
        elif b.pos % 2 == 0:
            hits = ((0, 5, 0.85), (6, 4, 0.55), (10, 6, 0.7))
        else:
            hits = ((0, 3, 0.8), (3, 7, 0.6), (10, 6, 0.7))
        for st, length, vel in hits:
            d = self.dur(b.index, st, length)
            i = self.at(b.index, st, 0.22)
            for k, m in enumerate(voicing):
                # Slight strum: R&B keys never hit perfectly together.
                self.bus["keys"].add(ins.epiano(m, d, vel, seed=k), i + samples(0.007 * k), gain)
                self._note("keys", b.index, st, length, m, vel)

    def _pad(self, b: Bar, gain: float = 0.6):
        notes = voice_lead(None, b.chord.flavoured(False), center=57)
        d = self.dur(b.index, 0, 16)
        self.bus["pad"].add(ins.pad(notes, d + 0.4, seed=b.index), self.at(b.index, 0), gain)

    def _choir(self, b: Bar):
        notes = voice_lead(None, b.chord.triad, center=65)
        d = self.dur(b.index, 0, 16)
        self.bus["pad"].add(ins.choir(notes, d + 0.4, "u" if b.pos % 2 == 0 else "o", seed=b.index),
                            self.at(b.index, 0), 0.17)

    def _arp(self, b: Bar):
        tones = b.chord.flavoured().tones(72, 88)
        if not tones:
            return
        seq = tones + tones[-2:0:-1]
        for st in range(16):
            m = seq[(st + b.pos * 3) % len(seq)]
            d = self.dur(b.index, st, 1)
            self.bus["pluck"].add(ins.pluck(m, d * 2.5, decay=0.18), self.at(b.index, st), 0.28,
                                  0.4 if st % 2 else -0.4)
            self._note("pluck", b.index, st, 1, m, 0.6)

    # ---------------------------------------------------------- chops
    def _chops(self, b: Bar, gain: float = 1.0, only_last: bool = False, octave: bool = False):
        notes = self.hook[b.index]
        if only_last:
            notes = notes[-1:]
        for k, c in enumerate(notes):
            d = self.dur(b.index, c.step, c.length)
            i = self.at(b.index, c.step)
            glide = self._last_chop if self._last_chop is not None and abs(self._last_chop - c.midi) <= 7 else None
            x = self._chop_audio(c, d, glide, seed=b.index * 16 + k)
            p = (-0.15, 0.15)[k % 2]
            self.bus["lead"].add(x, i, gain * 0.9, p)
            if octave:
                self.bus["lead"].add(self._chop_audio(ChopNote(c.step, c.length, c.midi + 12, c.vowel), d, None,
                                                      seed=k + 1), i, gain * 0.28, -p)
            self._note("chops", b.index, c.step, c.length, c.midi, 0.9)
            self._last_chop = c.midi

    def _topline(self, b: Bar):
        """Verse melody when nobody is singing: the hook's notes as soft, dark 'ooh' chops,
        call (first half-bar) and response (second half), so the verse already sings the
        tune the drop will shout."""
        notes = [c for c in self.hook[b.index] if (c.step < 8) == (b.pos % 2 == 0)]
        if b.phrase_end:
            notes = notes[:1]
        for k, c in enumerate(notes):
            d = self.dur(b.index, c.step, c.length * 1.4)
            x = ins.vox(c.midi, d, "u" if k % 2 == 0 else "o", shift=1.0, vibrato=0.3, attack=0.02,
                        release=0.08, breath=0.08, seed=b.index * 8 + k)
            self.bus["lead"].add(filt(x, "lowpass", 2600.0), self.at(b.index, c.step), 0.5, (-0.25, 0.25)[k % 2])
            self._note("chops", b.index, c.step, c.length, c.midi, 0.5)

    def _chop_audio(self, c: ChopNote, d: float, glide: int | None, seed: int) -> np.ndarray:
        if self.chops is not None:
            x = self.chops.note(c.midi, d, seed)
        else:
            x = ins.vox(c.midi, d, c.vowel, glide_from=glide if glide != c.midi else None, seed=seed,
                        to_vowel="u" if c.length >= 3 else None)
        if c.slide:  # pitched-up 'yip' on the phrase's last chop
            yip = ins.vox(c.midi + 12, min(0.12, d), "i", glide_from=c.midi, glide=0.04, seed=seed)
            x = x.copy()
            st = max(0, len(x) - len(yip))
            # Duck the held chop under the yip with a 10 ms ramp, not a hard step.
            duck = np.full(len(x) - st, 0.3)
            r = min(len(duck), samples(0.01))
            duck[:r] = np.linspace(1.0, 0.3, r)
            x[st:] = x[st:] * duck + yip[: len(x) - st]
        return x

    # ---------------------------------------------------------- build-up
    def _build(self, b: Bar):
        f = b.pos / b.length
        last = b.last
        # Kick: quarters, then eighths; drop out on the last beat.
        kick_steps = range(0, 16, 4) if f < 0.75 else range(0, 16, 2)
        for st in kick_steps:
            if last and st >= 12:
                continue
            self._kick(b.index, st, 0.55 + 0.25 * f)
        # Snare roll that doubles in density.
        div = 4 if f < 0.25 else 2 if f < 0.5 else 1 if f < 0.75 else 0.5
        st = 0.0
        while st < 16:
            if last and st >= 12:
                break
            prog = (b.pos + st / 16) / b.length
            x = ins.snare(0.18, tune=1.0 + 0.6 * prog)
            x = filt(x, "highpass", 200 + 1800 * prog)
            self.bus["snare"].add(x, samples(self.grid.step(b.index, st)), 0.12 + 0.45 * prog)
            self._note("drums", b.index, st, div, 38, 0.3 + 0.6 * prog)
            st += div
        # Chords: pumping eighth stabs with the filter opening across the build.
        bright = 0.25 + 0.7 * f
        for st in range(0, 16, 2):
            if last and st >= 12:
                break
            d = self.dur(b.index, st, 2)
            c = (400 + 2000 * bright, 900 + 8000 * bright, 600 + 4500 * bright)
            self.bus["chords"].add(ins.future_chord(self._voicing, d, cutoff=c, seed=self.seed + st), self.at(b.index, st),
                                   0.45 + 0.25 * f)
            self.pumps.append(self.at(b.index, st))
        self._pad(b, gain=0.35 + 0.3 * f)
        if f < 0.5:
            self._bass(b, "verse")
        if last:
            # The pre-drop shout: one pitched-up chop alone in the gap.
            top = max(b.chord.flavoured().tones(76, 84) or [76])
            x = ins.vox(top, self.dur(b.index, 13, 3), "a", glide_from=top - 5, glide=0.06, shift=1.2, seed=99)
            self.bus["lead"].add(x, self.at(b.index, 13), 0.9)
            self._note("chops", b.index, 13, 3, top, 1.0)

    # ---------------------------------------------------------- section FX
    def _section_fx(self, section: str, start: int, n: int, variant: int):
        t0, t1 = self.grid.bar_time(start), self.grid.bar_time(start + n)
        i0 = samples(t0)
        if section == "build":
            self.bus["fx"].add(ins.riser(t1 - t0, seed=start), i0, 0.22)
            rc = min(1.6, t1 - t0)
            self.bus["fx"].add(ins.reverse_cymbal(rc), samples(t1 - rc), 0.4)
        if section in ("drop", "chorus"):
            self.bus["fx"].add(ins.impact(), i0, 0.6)
            if n >= 16:
                self.bus["fx"].add(ins.crash(), samples(self.grid.bar_time(start + 8)), 0.35)
            self.bus["fx"].add(ins.downlifter(min(3.0, self.grid.beat_len(start) * 8)), samples(t1), 0.35)
        if section in ("intro", "break", "outro"):
            self.bus["fx"].add(ins.vinyl(t1 - t0, seed=start), i0, 0.22)
        if section == "intro":
            self.automation.append(("chords", i0, samples(t1), 450.0, 6000.0))
            self.bus["fx"].add(ins.riser(min(t1 - t0, self.grid.beat_len(start) * 8), seed=start + 5),
                               samples(t1 - min(t1 - t0, self.grid.beat_len(start) * 8)), 0.3)
        if section == "outro":
            self.automation.append(("chords", i0, samples(t1), 7000.0, 350.0))
            self.automation.append(("lead", i0, samples(t1), 9000.0, 900.0))

    def _apply_automation(self):
        pre = samples(0.05)
        for name, s, e, c0, c1 in self.automation:
            buf = self.bus[name].buf
            s0 = max(0, s - pre)
            seg = buf[:, s0:e]
            if seg.shape[1] <= pre:
                continue
            k = np.linspace(0, 1, seg.shape[1])
            cut = c0 * (c1 / c0) ** k
            out = sweep(seg, cut, "lowpass", q=0.8)
            xf = min(samples(0.03), out.shape[1] - (s - s0))
            if xf > 0:
                w = np.linspace(0, 1, xf)
                out[:, s - s0: s - s0 + xf] = out[:, s - s0: s - s0 + xf] * w + seg[:, s - s0: s - s0 + xf] * (1 - w)
            buf[:, s:e] = out[:, s - s0:]

    # ---------------------------------------------------------- mix + master
    def mix(self) -> dict[str, np.ndarray]:
        n = self.n
        st = {k: v.buf.copy() for k, v in self.bus.items()}
        pump = sidechain_curve(n, sorted(set(self.pumps)), depth=0.82, release=0.75 * self.grid.beat_len(0))
        kick_duck = sidechain_curve(n, sorted(set(self.kicks)), depth=0.55, release=0.12)
        st["chords"] *= pump
        st["pad"] *= np.minimum(pump * 0.4 + 0.6, 1.0)
        st["pluck"] *= np.minimum(pump * 0.5 + 0.5, 1.0)
        st["keys"] *= kick_duck * 0.3 + 0.7
        st["bass"] *= kick_duck
        st["fx"] *= kick_duck * 0.4 + 0.6

        # Channel EQ / dynamics.
        st["kick"] = filt(st["kick"], "peak", 3500, q=1.0, gain_db=2.0)
        st["snare"] = compress(st["snare"], -16, 3, 0.003, 0.1, makeup_db=2)
        st["chords"] = filt(filt(st["chords"], "highpass", 140, order=2), "peak", 380, q=0.8, gain_db=-3)
        st["chords"] = width(st["chords"], 1.35)
        st["keys"] = filt(st["keys"], "highpass", 120)
        st["pad"] = filt(st["pad"], "highpass", 160)
        st["lead"] = compress(filt(st["lead"], "peak", 3000, q=0.9, gain_db=3), -18, 4, 0.002, 0.08, makeup_db=3)
        st["bass"] = filt(st["bass"], "lowpass", 4000)

        if self.vocal is not None:
            v = np.zeros((2, n))
            m = min(n, self.vocal.shape[1])
            v[:, :m] = self.vocal[:, :m]
            v = filt(v, "highpass", 120, order=2)
            # Level-match the singer: -16 dB RMS over the sung (non-silent) parts.
            frames = np.abs(v).max(axis=0)
            sung = frames > 0.05 * (frames.max() + 1e-12)
            if np.any(sung):
                v *= db(-16) / (np.sqrt(np.mean(v[:, sung] ** 2)) + 1e-12)
            v = compress(v, -20, 3.5, 0.004, 0.12, makeup_db=3)
            st["vocal"] = v
            # Duck the chop hook under the real singer so they never fight.
            env = np.abs(v).max(axis=0)
            env = filt(env, "lowpass", 6.0)
            env = env / (np.percentile(env[env > 0], 95) + 1e-9) if np.any(env > 0) else env
            st["lead"] *= 1 - 0.75 * np.clip(env, 0, 1)

        ir = reverb_ir(2.8)
        sends = {"snare": 0.22, "lead": 0.35, "keys": 0.25, "chords": 0.12, "pad": 0.35, "fx": 0.25,
                 "pluck": 0.3, "vocal": 0.16, "perc": 0.15}
        verb = reverb(sum(st[k] * g for k, g in sends.items()), ir) * 0.9
        verb *= pump * 0.5 + 0.5
        beat = self.grid.beat_len(0)
        echo = delay(st["lead"] * 0.3 + st["pluck"] * 0.25 + st["vocal"] * 0.12, beat * 0.75, feedback=0.42)

        # Calibrated so a drop sits around kick -14, bass -15, chords -15, chops -18,
        # clap -22, hats -30 dB RMS before the master bus: chords as loud as the kick.
        levels = {"kick": 0.38, "snare": 1.7, "hats": 0.64, "perc": 0.8, "bass": 0.32, "chords": 2.5,
                  "keys": 0.7, "pluck": 0.7, "lead": 1.1, "pad": 0.9, "fx": 0.5, "vocal": 1.0}
        stems = {k: st[k] * g for k, g in levels.items()}
        stems["returns"] = verb + echo * 0.6
        bus = sum(stems.values())
        master = compress(bus, -10, 1.6, 0.015, 0.2, makeup_db=1.0, knee_db=8)  # gentle glue
        master = filt(master, "highshelf", 9000, gain_db=1.5)
        master = mono_below(master, 120)
        master = self._tape_stop(master)
        peak = np.max(np.abs(master)) + 1e-12
        master = saturate(master / peak * 1.2, 1.15) * 0.9
        master = limit(master, -1.0)
        stems["master"] = master
        return stems

    def _tape_stop(self, x: np.ndarray) -> np.ndarray:
        """Slow the final beat down to a halt, then let it ring out."""
        if not self.plan.bars or self.plan.bars[-1].section != "outro":
            return x
        last = len(self.plan) - 1
        s = samples(self.grid.t(last * self.grid.bpb + 2))
        e = samples(self.end_t)
        if e - s < 100:
            return x
        L = e - s
        speed = np.linspace(1.0, 0.0, L) ** 1.5
        pos = s + np.cumsum(speed)
        y = x.copy()
        idx = np.arange(x.shape[1])
        for c in range(2):
            y[c, s:e] = np.interp(pos, idx, x[c]) * np.linspace(1, 0.2, L)
        y[:, e:] *= 0.15  # keep only a breath of reverb tail after the stop
        tail = y.shape[1] - e
        if tail > 0:
            y[:, e:] *= np.linspace(1, 0, tail)
        return y


class ChopSampler:
    """Re-pitches grains cut from a real vocal stem into chop notes (source mode)."""

    def __init__(self, grains: list[tuple[np.ndarray, float]]):
        if not grains:
            raise ValueError("need at least one vocal grain")
        self.grains = grains  # (mono audio, detected MIDI pitch)

    def note(self, midi: float, dur: float, seed: int = 0) -> np.ndarray:
        g, p = self.grains[seed % len(self.grains)]
        ratio = 2 ** ((midi - p) / 12)
        n = samples(dur)
        pos = np.arange(n) * ratio
        pos = pos[pos < len(g) - 1]
        x = np.interp(pos, np.arange(len(g)), g)
        if len(x) < n:
            x = np.pad(x, (0, n - len(x)))
        x /= max(1e-9, np.max(np.abs(x))) * 1.2
        env = np.ones(n)
        a, r = min(n, samples(0.004)), min(n, samples(0.03))
        env[:a] = np.linspace(0, 1, a)
        env[n - r:] *= np.linspace(1, 0, r)
        return x * env
