# Valkyrie Portal Sequence

Three-shot cinematic sequence (15s total), produced with
[OpenMontage](https://github.com/calesthio/OpenMontage) via its `cinematic` pipeline.

| # | Shot | Duration | Prompt |
|---|------|----------|--------|
| 1 | Portal burst over the ocean | 4s | `shots/shot-1-portal-burst.txt` |
| 2 | Low ocean fly-by with V-wake | 5s | `shots/shot-2-ocean-flyby.txt` |
| 3 | Shoreline landing, battle stance | 6s | `shots/shot-3-shoreline-landing.txt` |

## Layout

- `shots/` — one prompt per shot.
- `reference/` — character images, mood image, previous motion take, and
  `CHARACTER.md` (identity block to keep her consistent across shots).
- `OpenMontage/` — production toolkit, pinned as a git submodule.

## Setup

    git clone --recurse-submodules <this repo>   # or: ./setup.sh after a plain clone
    ./setup.sh

A video-generation provider key is required (e.g. `FAL_KEY`, `ATLASCLOUD_API_KEY`,
`ARK_API_KEY`, `KLING_API_KEY`) in OpenMontage's `.env`.
