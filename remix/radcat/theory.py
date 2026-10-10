"""Pitch, chord and key helpers.

Everything is pitch-class / MIDI based so the same arrangement works in any key: the
demo uses the original's listed key (C major) and source mode uses whatever key the
analysis finds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E"}

# Interval sets, semitones above the root. Extensions above the octave stay > 12 so
# voicing code can place them on top, the way a future bass chord stack is built.
QUALITIES: dict[str, tuple[int, ...]] = {
    "maj": (0, 4, 7),
    "min": (0, 3, 7),
    "dim": (0, 3, 6),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "6": (0, 4, 7, 9),
    "7": (0, 4, 7, 10),
    "maj7": (0, 4, 7, 11),
    "min7": (0, 3, 7, 10),
    "add9": (0, 4, 7, 14),
    "madd9": (0, 3, 7, 14),
    "maj9": (0, 4, 7, 11, 14),
    "min9": (0, 3, 7, 10, 14),
    "6/9": (0, 4, 7, 9, 14),
    "min11": (0, 3, 7, 10, 14, 17),
}

# Krumhansl-Kessler key profiles, used by analysis.detect_key.
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)


def midi_to_hz(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def pc_name(pc: int) -> str:
    return NOTE_NAMES[pc % 12]


def parse_pc(name: str) -> int:
    name = name.strip()
    name = _FLATS.get(name[:2], name[:2]) if len(name) >= 2 and name[1] == "b" else name
    name = name[0].upper() + name[1:]
    if name not in NOTE_NAMES:
        raise ValueError(f"unknown note name: {name!r}")
    return NOTE_NAMES.index(name)


def parse_note(text: str) -> int:
    """'C4' -> 60, 'F#3' -> 54, 'Bb2' -> 46."""
    m = re.fullmatch(r"([A-Ga-g][#b]?)(-?\d+)", text.strip())
    if not m:
        raise ValueError(f"bad note: {text!r}")
    return parse_pc(m.group(1)) + 12 * (int(m.group(2)) + 1)


@dataclass(frozen=True)
class Chord:
    root: int  # pitch class 0-11
    quality: str = "maj"

    def __post_init__(self):
        if self.quality not in QUALITIES:
            raise ValueError(f"unknown chord quality {self.quality!r}")
        object.__setattr__(self, "root", self.root % 12)

    @property
    def intervals(self) -> tuple[int, ...]:
        return QUALITIES[self.quality]

    @property
    def pcs(self) -> frozenset[int]:
        return frozenset((self.root + i) % 12 for i in self.intervals)

    @property
    def is_minor(self) -> bool:
        return 3 in self.intervals and 4 not in self.intervals

    @property
    def triad(self) -> "Chord":
        if self.quality == "dim":
            return self
        return Chord(self.root, "min" if self.is_minor else "maj")

    @property
    def name(self) -> str:
        q = {"maj": "", "min": "m", "min7": "m7", "min9": "m9", "min11": "m11"}.get(self.quality, self.quality)
        return pc_name(self.root) + q

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.name

    @classmethod
    def parse(cls, text: str) -> "Chord":
        m = re.fullmatch(r"([A-G][#b]?)(.*)", text.strip())
        if not m:
            raise ValueError(f"bad chord: {text!r}")
        root = parse_pc(m.group(1))
        q = m.group(2)
        aliases = {"": "maj", "m": "min", "m7": "min7", "m9": "min9", "m11": "min11", "M7": "maj7",
                   "madd9": "madd9", "dim": "dim"}
        q = aliases.get(q, q)
        return cls(root, q)

    def tones(self, low: int, high: int) -> list[int]:
        """Every MIDI note in [low, high] that belongs to the chord (melody pool)."""
        return [m for m in range(low, high + 1) if m % 12 in self.pcs]

    def voicing(self, center: int = 62, spread: int = 0) -> list[int]:
        """Stacked voicing: root at the bottom, extensions on top, centred near `center`.

        spread>0 adds an octave-up doubling of the top voices, the "huge" drop voicing.
        """
        base = self.root + 12 * ((center - 7 - self.root) // 12)
        notes = sorted(base + i for i in self.intervals)
        # Bring the voicing's centre of mass near `center`.
        while sum(notes) / len(notes) < center - 6:
            notes = [n + 12 for n in notes]
        while sum(notes) / len(notes) > center + 6:
            notes = [n - 12 for n in notes]
        if spread:
            notes += [n + 12 for n in notes[-spread:]]
        return sorted(set(notes))

    def flavoured(self, extended: bool = True) -> "Chord":
        """Future bass colouring: majors get maj9 / add9, minors get m9 / m7."""
        if self.quality not in ("maj", "min"):
            return self
        if self.is_minor:
            return Chord(self.root, "min9" if extended else "min7")
        return Chord(self.root, "maj9" if extended else "add9")


def voice_lead(prev: list[int] | None, chord: Chord, center: int = 62, spread: int = 0) -> list[int]:
    """Choose the octave of `chord`'s voicing that moves least from `prev`."""
    best = chord.voicing(center, spread)
    if not prev:
        return best
    candidates = [[n + 12 * o for n in best] for o in (-1, 0, 1)]
    candidates = [c for c in candidates if center - 14 <= sum(c) / len(c) <= center + 14] or [best]
    prev_mean = sum(prev) / len(prev)
    return min(candidates, key=lambda c: abs(sum(c) / len(c) - prev_mean))


@dataclass(frozen=True)
class Key:
    tonic: int
    mode: str = "major"  # 'major' | 'minor'

    def __post_init__(self):
        if self.mode not in ("major", "minor"):
            raise ValueError("mode must be 'major' or 'minor'")
        object.__setattr__(self, "tonic", self.tonic % 12)

    @property
    def scale(self) -> tuple[int, ...]:
        steps = MAJOR_SCALE if self.mode == "major" else MINOR_SCALE
        return tuple((self.tonic + s) % 12 for s in steps)

    @property
    def name(self) -> str:
        return f"{pc_name(self.tonic)} {self.mode}"

    @classmethod
    def parse(cls, text: str) -> "Key":
        """'C', 'C major', 'Am', 'A minor', 'F# min'."""
        t = text.strip()
        m = re.fullmatch(r"([A-Ga-g][#b]?)\s*(m|min|minor|maj|major)?", t)
        if not m:
            raise ValueError(f"bad key: {text!r}")
        mode = "minor" if (m.group(2) or "").lower() in ("m", "min", "minor") else "major"
        return cls(parse_pc(m.group(1)), mode)

    def diatonic_triads(self) -> list[Chord]:
        sc = self.scale
        out = []
        for i in range(7):
            r, third, fifth = sc[i], sc[(i + 2) % 7], sc[(i + 4) % 7]
            t3, t5 = (third - r) % 12, (fifth - r) % 12
            q = "maj" if (t3, t5) == (4, 7) else "min" if (t3, t5) == (3, 7) else "dim"
            out.append(Chord(r, q))
        return out

    def degree(self, n: int, quality: str | None = None) -> Chord:
        """1-based scale degree chord, optionally overriding the quality."""
        c = self.diatonic_triads()[(n - 1) % 7]
        return Chord(c.root, quality or c.quality)

    def transpose(self, semitones: int) -> "Key":
        return Key(self.tonic + semitones, self.mode)


def default_progressions(key: Key) -> dict[str, list[Chord]]:
    """The demo's harmony, written as scale degrees so it works in any key.

    Major: IV-V-iii-vi (the classic future bass lift) for the hook, I-vi-IV-V style
    verse. Minor keys use the relative-major equivalents (VI-VII-v-i).
    """
    d = key.degree
    if key.mode == "major":
        return {
            "verse": [d(6, "min9"), d(4, "maj9"), d(1, "add9"), d(5, "6")],
            "drop": [d(4, "maj9"), d(5, "6"), d(3, "min7"), d(6, "min9")],
            "drop2": [d(4, "maj9"), d(5, "add9"), d(6, "min9"), d(3, "min7")],
            "break": [d(4, "maj7"), d(1, "add9"), d(6, "min9"), d(5, "sus4")],
        }
    return {
        "verse": [d(1, "min9"), d(6, "maj9"), d(3, "add9"), d(7, "6")],
        "drop": [d(6, "maj9"), d(7, "6"), d(5, "min7"), d(1, "min9")],
        "drop2": [d(6, "maj9"), d(7, "add9"), d(1, "min9"), d(5, "min7")],
        "break": [d(6, "maj7"), d(3, "add9"), d(1, "min9"), d(7, "sus4")],
    }
