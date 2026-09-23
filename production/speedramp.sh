#!/usr/bin/env bash
# Speed-ramp a generated clip: faster, with motion blur on the fast parts.
#
#   production/speedramp.sh IN OUT "start end speed blur" ["start end speed blur" ...]
#
# Each segment: start/end in seconds of IN, speed multiplier, blur = frames blended
# before speeding up (1 = none). Example (take 2 of the CapCut sequence):
#   production/speedramp.sh take2.mov out.mp4 "0 4 2.5 2" "4 9 4 3" "9 11.5 3 2" "11.5 13 1.5 1" "13 14.5 1 1"
set -euo pipefail
in=$1; out=$2; shift 2
fc=""; labels=""; i=0
for spec in "$@"; do
  read -r a b speed blur <<<"$spec"
  at=""; s=$speed
  while (( $(echo "$s > 2" | bc) )); do at+="atempo=2.0,"; s=$(echo "$s / 2" | bc -l); done
  at+="atempo=$s"
  vb=""; [ "$blur" -gt 1 ] && vb="tmix=frames=$blur,"
  fc+="[0:v]trim=$a:$b,setpts=PTS-STARTPTS,${vb}setpts=PTS/$speed,fps=24[v$i];"
  fc+="[0:a]atrim=$a:$b,asetpts=PTS-STARTPTS,$at[a$i];"
  labels+="[v$i][a$i]"; i=$((i+1))
done
ffmpeg -hide_banner -loglevel error -y -i "$in" -filter_complex "${fc}${labels}concat=n=$i:v=1:a=1[v][a]" \
  -map "[v]" -map "[a]" -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart "$out"
echo "$out: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out")s"
