#!/usr/bin/env bash
# Fetch OpenMontage (the production toolkit) next to this repo and install its deps.
set -euo pipefail
DIR="${OPENMONTAGE_DIR:-../OpenMontage}"
[ -d "$DIR" ] || git clone --depth 1 https://github.com/calesthio/OpenMontage.git "$DIR"
pip install -r "$DIR/requirements.txt"
command -v ffmpeg >/dev/null || echo "WARNING: ffmpeg not found; install it before composing."
