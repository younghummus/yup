"""A synthetic 'original song' with known ground truth, for testing source mode.

Band-style mix: drums on 1-2-3-4 with backbeat snare, bass on roots, chords as
hard-panned saw 'guitars' plus centre keys, and a centre-panned formant-synth singer
in the verse/chorus — mimicking how a real indie-pop record is laid out.
"""
from __future__ import annotations

import numpy as np

from radcat import instruments as ins
from radcat.dsp import Bus, filt, samples
from radcat.theory import Chord

PROG = [Chord.parse(c) for c in ("C", "G", "Am", "F")]
# (section, bars, vocal, loudness)
FORM = (("intro", 4, False, 0.45), ("verse", 8, True, 0.6), ("chorus", 8, True, 1.0), ("outro", 4, False, 0.5))
MELODY = ((0, 4, 0), (4, 2, 1), (6, 2, 2), (8, 6, 1), (14, 2, 0))  # (step, len, chord-tone index)


def make_song(bpm: float = 150.0, lead_in: float = 0.37, seed: int = 0, bpm_end: float | None = None):
    """Returns (mix, vocal, truth). `bpm_end` makes the tempo drift linearly, like a band
    playing without a click; truth['beats'] then holds the exact beat times."""
    bars = sum(f[1] for f in FORM)
    n_beats = bars * 4 + 1
    tempi = np.linspace(bpm, bpm_end or bpm, n_beats)
    beat_times = lead_in + np.concatenate(([0.0], np.cumsum(60.0 / tempi[:-1])))
    beat = 60.0 / bpm
    n = samples(beat_times[-1] + 1.0)
    band, voice = Bus(n), Bus(n)
    truth = {"bpm": bpm, "lead_in": lead_in, "beats": beat_times, "chords": [], "vocal": [], "labels": []}
    bar = 0
    for section, nb, sung, loud in FORM:
        for i in range(nb):
            ch = PROG[bar % 4]
            truth["chords"].append(ch)
            truth["vocal"].append(sung)
            truth["labels"].append(section)
            beat = beat_times[bar * 4 + 1] - beat_times[bar * 4]
            t0 = beat_times[bar * 4]
            at = lambda step, t0=t0, beat=beat: samples(t0 + step * beat / 4)  # noqa: E731
            for b in range(4):
                band.add(ins.kick(), at(4 * b), 0.5 * loud)
                if b % 2:
                    band.add(ins.snare(), at(4 * b), 0.45 * loud)
                for h in (0, 2):
                    band.add(ins.hat(), at(4 * b + h), 0.12 * loud, 0.3)
            root = 36 + ch.root
            band.add(ins.sub(root, 4 * beat * 0.95), at(0), 0.5 * loud)
            for k, m in enumerate(ch.voicing(center=60)):
                g = ins.supersaw(m, 4 * beat, voices=3, detune=0.1, seed=bar * 8 + k)[0]
                g = filt(g, "lowpass", 2500)
                band.add(g, at(0), 0.25 * loud, -0.8 if k % 2 else 0.8)
                band.add(ins.epiano(m, 4 * beat * 0.9, 0.7), at(0), 0.10 * loud)
            if sung:
                pool = ch.tones(64, 76)
                for step, length, idx in MELODY:
                    v = ins.vox(pool[min(idx, len(pool) - 1)], length * beat / 4 * 0.95, "a", shift=1.0,
                                seed=bar + step)
                    voice.add(v, at(step), 0.55 * loud)
            bar += 1
    mix = band.buf + voice.buf
    mix /= np.max(np.abs(mix)) * 1.1
    vocal_only = voice.buf / (np.max(np.abs(mix)) * 1.1 + 1e-12)
    return mix, vocal_only, truth
