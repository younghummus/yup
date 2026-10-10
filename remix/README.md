# Mind Over Matter — Rad Cat Remix (fan remix, personal use)

A future bass remix of Young the Giant's **"Mind Over Matter"** in the style of
**Rad Cat** (Christian Ariza, San Diego), rendered entirely in code. This is a
non-commercial fan project, made for personal enjoyment only.

**Listen:** [`../renders/mind-over-matter-rad-cat-remix.mp3`](../renders/mind-over-matter-rad-cat-remix.mp3)
(2:33, 155 BPM, C major, mastered to -9 LUFS / -1.5 dBTP).
**Open it in a DAW:** [`../renders/mind-over-matter-rad-cat-remix.mid`](../renders/mind-over-matter-rad-cat-remix.mid)

No copyrighted audio is in this repo. The committed render is an **original instrumental**
built on the song's listed key and tempo (C, 155 BPM). To hear it with the real
vocal, point the engine at your own copy of the song (see [Source mode](#source-mode)).
It will analyse the track and build the remix around the singer, bar for bar.

## The sound

Rad Cat calls his style *"R&B and upbeat House music having a child"*. He produces in
Ableton with Serum, makes future bass with hip-hop drums, "starts from a melody", and
lists Flume, Mura Masa, Porter Robinson, Madeon, SG Lewis and FKJ as influences. Here is
how each part of that maps to the engine:

| Rad Cat trait | In the remix | Code |
|---|---|---|
| Future bass supersaw chords | 7-voice detuned polyBLEP supersaw stacks, filter envelope, Serum-style noise layer, extended voicings (maj9 / m9 / 6) | `instruments.future_chord` |
| The pump | Sidechain on every beat in the drops, plus kick-ducked bass and keys | `dsp.sidechain_curve`, `Remix.mix` |
| Pitch-rise chord swell | Every drop opens with a 7-semitone scoop into the chord | `future_chord(scoop=…)` |
| Wobble chords (Flume-ish) | Drop 2 opens on 1/8-note filter + volume wobble chords | `future_chord(wobble_hz=…)` |
| Hip-hop / trap drums | Half-time groove, layered clap + snare on 3, swung hats in the verse, triplet hat rolls in the drop | `GROOVES`, `_groove`, `_hats` |
| 808 + sub | Gliding saturated 808 in the drops, clean sine sub in the verses | `bass808`, `sub` |
| R&B keys | FM Rhodes with stereo tremolo and strummed voicings | `epiano`, `_keys` |
| "Starts from a melody" | A chopped-vocal hook: one rhythmic motif mapped onto each chord's tones, so it sequences through the progression, with a pitched-up "yip" ending each phrase. The verses sing the same tune softly as call-and-response | `hook_for`, `_chops`, `_topline` |
| Vocal chops | Formant-synthesised sung vowels (demo), or syllables cut from the real vocal and re-pitched (source mode) | `vox`, `ChopSampler` |
| Porter / Madeon sparkle | 16th-note pluck arpeggios in the drops | `pluck`, `_arp` |
| Builds and drops | Doubling snare roll, rising kick, noise riser, reverse cymbal, a one-beat gap with a pre-drop chop shout, then impact + crash | `_build`, `_section_fx` |
| Lo-fi R&B intro / break | Vinyl crackle, filtered chords, "ooh" choir, snaps | `vinyl`, `choir` |

Harmony for the demo, written as scale degrees so it works in any key:

| Section | Progression (C major) |
|---|---|
| Drop | Fmaj9 – G6 – Em7 – Am9 (IV–V–iii–vi, the classic future bass lift) |
| Drop 2 | Fmaj9 – Gadd9 – Am9 – Em7 |
| Verse | Am9 – Fmaj9 – Cadd9 – G6 |
| Break | Fmaj7 – Cadd9 – Am9 – Gsus4 |

### Arrangement (demo)

| Time | Section | Bars | What happens |
|---|---|---|---|
| 0:00 | Intro | 8 | Filtered chords open up over vinyl, chop teasers, riser |
| 0:12 | Verse | 16 | R&B half-time groove, Rhodes, sub, soft "ooh" topline |
| 0:37 | Build | 8 | Snare roll 1/4 → 1/32, rising chords and riser, gap, shout |
| 0:50 | **Drop** | 16 | Supersaw chords pumping, 808, trap drums, chop hook, arps |
| 1:14 | Break | 8 | Rhodes + choir, snaps, chop echoes |
| 1:27 | Verse 2 | 8 | Groove returns with pad and shaker |
| 1:39 | Build 2 | 8 | Second build-up |
| 1:51 | **Drop 2** | 16 | Wobble chords first, then stabs; octave-doubled chops |
| 2:16 | Outro | 8 | Chords filter down, chops fade, tape-stop ending |

Measured on the master: intro -15.0, verse -12.3, build -11.6, **drop -9.8**,
break -16.2, drop 2 -9.9 dB RMS, so the drops really do hit.

## Run it

Needs Python 3.10+, `numpy`, `scipy` and `ffmpeg`.

    pip install -r remix/requirements.txt
    python remix/remix.py                     # demo -> remix/output/  (~90 s on 4 cores)
    python remix/remix.py --stems             # + drums/bass/chords/keys/chops/fx stems
    python remix/remix.py --key Am --bpm 150  # same remix, different key / tempo

Every run writes `<name>.wav` (24-bit master), `<name>.mp3` (320 kbps, tagged),
`<name>.mid` (the arrangement: one track per part, GM drums on channel 10) and
`<name>.txt` (analysis + section map).

### Source mode

    python remix/remix.py --source "Mind Over Matter.mp3"

1. **Analysis.** It finds the tempo (onset autocorrelation, then a fine pulse-train
   search), tracks beats (Ellis dynamic programming), and locks the grid to the
   transients to within a few ms. It follows a live band's drift. It then finds the
   downbeat (where harmony and bass change), the key (Krumhansl-Kessler on
   harmonic-salience chroma) and one chord per bar (templates, bass-root bonus,
   Viterbi smoothing).
2. **Vocal.** It uses [Demucs](https://github.com/facebookresearch/demucs) if it is
   installed (`pip install demucs`; cleanest). Otherwise a built-in extractor keeps
   what is centre-panned and harmonic. Or pass your own aligned acapella with
   `--acapella vocals.wav`.
3. **Structure.** Each 4-bar phrase is labelled from its loudness and whether someone
   is singing: intro, verse, chorus, instrumental drop, break, outro. The phrase before
   every chorus becomes a build-up.
4. **Remix.** The instrumental is generated on the song's own beat grid, re-harmonised
   with future bass chord colours (maj → maj9, m → m9). The real vocal sits on top.
   Choruses get the drop treatment with the vocal over it. The chop hook is cut from
   the singer's own syllables, re-pitched to every chord, and ducks under the lead
   vocal so the two never fight.

Useful options: `--bpm 155` (tempo hint), `--key C` (override), `--transpose -2`
(everything, vocal included, via rubberband), `--instrumental`, `--chops synth|real`,
`--vocal-method demucs|centre`, `--lufs -8`, `--seed 3` (new synth textures,
same notes).

### Keep producing it

Drag `renders/mind-over-matter-rad-cat-remix.mid` into Ableton. Put Serum's supersaw
on `chords`, a vocal-chop sampler or Serum on `chops`, an 808 on `bass`, and drums on
`drums`. That's the same arrangement as a real project, ready to swap in better
sounds.

## How it's checked

`python -m pytest remix/tests` runs 112 tests in about 3½ minutes. Source mode is
verified against synthetic band recordings with exact ground truth (`tests/fixtures.py`:
drums, bass, panned "guitars", keys, and a centre-panned formant singer):

| Check | Result |
|---|---|
| Tempo, 96–170 BPM | within 0.1 BPM |
| Beat and bar positions | median < 3 ms, max < 10 ms (click-tracked) |
| Live drift 155 → 149 BPM | median < 5 ms, max < 35 ms |
| Key and chords | correct key, every bar's chord correct |
| Vocal bars and sections | intro / verse / build / chorus / outro all correct, pickup bar handled |
| Vocal placement in the remix | lands within 3 ms of where the grid says |

Also covered: oscillator aliasing (polyBLEP vs naive), filter responses, the pan law,
the sidechain shape, compressor and true-peak limiter, the BS.1770 loudness meter
(reads the spec's -3.01 LUFS reference tone and matches ffmpeg), WAV round-trips, MP3
loudness, rubberband pitch shift, the pitch of every voiced instrument, the formant
vowels, hook harmony, sidechain pumping, vocal ducking, MIDI file structure, and the
full CLI in both modes.

## Layout

| File | Role |
|---|---|
| `remix.py` | CLI |
| `radcat/theory.py` | Notes, chords, voicings, voice leading, keys, demo progressions |
| `radcat/dsp.py` | Oscillators, filters, reverb/delay, sidechain, compressor, limiter, LUFS, I/O |
| `radcat/instruments.py` | Supersaw, future bass chord, pad, pluck, Rhodes, sub, 808, drums, FX, vocal chops |
| `radcat/arrangement.py` | Beat grid (fixed or tracked), bars, sections, demo form |
| `radcat/render.py` | The producer: parts, hook, builds, mix and master |
| `radcat/analysis.py` | Tempo, beats, downbeats, key, chords, vocal stem, sections |
| `radcat/midi.py` | Standard MIDI File export |
| `radcat/pipeline.py` | Source/demo → plan → render → files |

## Limits

- Every sound is synthesised from scratch in numpy, not played through Serum. The
  vocal chops in the demo are formant synthesis, so they sound like a vocal synth,
  not a real singer. Source mode chops the real voice.
- The C major / 155 BPM figures come from public song databases. Source mode measures
  them from your file and uses what it finds.
- The analysis assumes 4/4. The built-in vocal extractor is rougher than Demucs on
  dense mixes.
- Personal, non-commercial use only. "Mind Over Matter" belongs to Young the Giant,
  and Rad Cat is not involved in this project.
