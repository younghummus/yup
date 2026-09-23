# Valkyrie Portal Sequence

Three-shot cinematic sequence (15s total), produced with
[OpenMontage](https://github.com/calesthio/OpenMontage) via its `cinematic` pipeline.

| # | Shot | Duration | Prompt |
|---|------|----------|--------|
| 1 | Portal burst over the ocean | 4s | `shots/shot-1-portal-burst.txt` |
| 2 | Low ocean fly-by with V-wake | 5s | `shots/shot-2-ocean-flyby.txt` |
| 3 | Shoreline landing, battle stance | 6s | `shots/shot-3-shoreline-landing.txt` |

## Setup

    ./setup.sh

Put the valkyrie character reference image in `reference/` (used for
image-to-video / reference-to-video so she stays consistent across shots).

A video-generation provider key is required (e.g. `FAL_KEY`, `ATLASCLOUD_API_KEY`,
`ARK_API_KEY`, `KLING_API_KEY`) in OpenMontage's `.env`.
