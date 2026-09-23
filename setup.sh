#!/usr/bin/env bash
# Fetch the pinned OpenMontage submodule and install its deps.
set -euo pipefail
cd "$(dirname "$0")"
git submodule update --init --depth 1 OpenMontage
pip install -r OpenMontage/requirements.txt
command -v ffmpeg >/dev/null || echo "WARNING: ffmpeg not found; install it before composing."
[ -f OpenMontage/.env ] || echo "NOTE: create OpenMontage/.env with a video provider key (see README)."
