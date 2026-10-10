#!/usr/bin/env python3
"""Mind Over Matter — Rad Cat-style future bass remix generator.

    python remix/remix.py                                  # demo: original instrumental, C major, 155 BPM
    python remix/remix.py --source "Mind Over Matter.mp3"  # remix your own copy, with its vocal
    python remix/remix.py --source song.mp3 --acapella vocals.wav --stems

See remix/README.md for what each part of the sound does and how source mode works.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from radcat.pipeline import TITLE, Options, run  # noqa: E402


def parse(argv: list[str] | None = None) -> Options:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", help="your own copy of the original song (any format ffmpeg reads)")
    p.add_argument("--acapella", help="an isolated vocal aligned to --source (skips separation)")
    p.add_argument("--vocal-method", choices=("auto", "demucs", "centre"), default="auto",
                   help="vocal separation: demucs if installed (auto), or the built-in centre extractor")
    p.add_argument("--bpm", type=float, help="demo tempo (default 155) or a tempo hint for --source")
    p.add_argument("--key", help="demo key (default C) or a key override for --source, e.g. 'C', 'Am'")
    p.add_argument("--transpose", type=int, default=0, help="semitones to shift everything, vocal included")
    p.add_argument("--chops", choices=("auto", "synth", "real"), default="auto",
                   help="vocal chop source: cut from the real vocal (auto/real) or formant-synthesised")
    p.add_argument("--instrumental", action="store_true", help="source mode: leave the original vocal out")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "output"), help="output directory")
    p.add_argument("--name", default="mind-over-matter-rad-cat-remix", help="output file stem")
    p.add_argument("--title", default=TITLE)
    p.add_argument("--stems", action="store_true", help="also write drums/bass/chords/keys/chops/fx/vocal stems")
    p.add_argument("--no-midi", action="store_true", help="skip the .mid arrangement export")
    p.add_argument("--no-mp3", action="store_true", help="WAV only")
    p.add_argument("--lufs", type=float, default=-9.0, help="master loudness target, integrated LUFS (default -9)")
    p.add_argument("--seed", type=int, default=0, help="variation seed for the synth voices")
    a = p.parse_args(argv)
    if a.acapella and not a.source:
        p.error("--acapella needs --source (the acapella is aligned to it)")
    return Options(source=a.source, acapella=a.acapella, vocal_method=a.vocal_method, bpm=a.bpm, key=a.key,
                   transpose=a.transpose, chops=a.chops, instrumental=a.instrumental, out=a.out, name=a.name,
                   title=a.title, stems=a.stems, midi=not a.no_midi, mp3=not a.no_mp3, lufs=a.lufs, seed=a.seed)


def main(argv: list[str] | None = None) -> int:
    run(parse(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
