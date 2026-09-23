#!/usr/bin/env python3
"""Generate the valkyrie shots through OpenMontage and cut them into one sequence.

    python production/produce.py                 # dry run: prompts + cost, spends nothing
    python production/produce.py --shots 1 --yes # paid sample of shot 1 only
    python production/produce.py --yes           # all shots, then assemble

Needs a video provider key in OpenMontage/.env (e.g. FAL_KEY for Seedance).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OM = ROOT / "OpenMontage"
OUT = ROOT / "production" / "output"
sys.path.insert(0, str(OM))

# Per-second rates from OpenMontage's seedance_video tool (fal.ai, 720p).
RATES = {"standard": 0.3034, "fast": 0.2419}


def build_prompt(shot, cfg):
    return " ".join(
        shot["prompt"]
        .replace("{identity_lock}", cfg["identity_lock"])
        .replace("{style}", cfg["style"])
        .split()
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="all", help="'all' or comma list of shot numbers, e.g. 1,3")
    ap.add_argument("--variant", choices=RATES, default="standard")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--yes", action="store_true", help="actually spend money and generate")
    ap.add_argument("--no-assemble", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "production" / "shots.yaml").read_text())
    d = cfg["defaults"]
    shots = cfg["shots"]
    if args.shots != "all":
        picks = {int(n) for n in args.shots.split(",")}
        shots = [s for i, s in enumerate(shots, 1) if i in picks]

    total = sum(RATES[args.variant] * int(s["duration"]) for s in shots)
    for s in shots:
        print(f"\n== {s['id']} ({s['duration']}s)\n{build_prompt(s, cfg)}")
    print(f"\nEstimated cost ({args.variant}, Seedance via fal.ai): ${total:.2f}")
    if not args.yes:
        print("Dry run. Re-run with --yes to generate.")
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(OM / ".env")
    except ImportError:
        pass
    from tools.tool_registry import registry

    registry.discover()
    selector = registry.get("video_selector")
    clips_dir = OUT / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    log = []
    for s in shots:
        out = clips_dir / f"{s['id']}.mp4"
        params = {
            "prompt": build_prompt(s, cfg),
            "preferred_provider": d["provider"],
            "operation": d["operation"],
            "aspect_ratio": d["aspect_ratio"],
            "duration": s["duration"],
            "resolution": d["resolution"],
            "generate_audio": d["generate_audio"],
            "model_variant": args.variant,
            "reference_image_paths": [str(ROOT / p) for p in d["reference_images"]],
            "output_path": str(out),
        }
        if args.seed is not None:
            params["seed"] = args.seed
        print(f"\nGenerating {s['id']} ...", flush=True)
        r = selector.execute(params)
        if not r.success:
            sys.exit(f"{s['id']} failed: {r.error}")
        log.append({"shot": s["id"], "output": str(out), "data": r.data, "cost_usd": r.cost_usd})
        print(f"  -> {out}")
    (OUT / "generation_log.json").write_text(json.dumps(log, indent=2, default=str))

    if args.no_assemble:
        return
    clips = [clips_dir / f"{s['id']}.mp4" for s in cfg["shots"]]
    if not all(c.exists() for c in clips):
        print("\nNot all shots exist yet; skipping assembly.")
        return
    # Re-encode to a common format so clips from different runs concat cleanly.
    inputs = sum((["-i", str(c)] for c in clips), [])
    n = len(clips)
    streams = "".join(
        f"[{i}:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=24,setsar=1[v{i}];"
        f"[{i}:a]aresample=48000[a{i}];"
        for i in range(n)
    )
    concat = "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    final = OUT / "valkyrie-portal-sequence.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", streams + concat, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(final)],
        check=True,
    )
    print(f"\nFinal sequence: {final}")


if __name__ == "__main__":
    main()
