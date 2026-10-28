#!/usr/bin/env bash
# Load the InterSystems IRIS for Health build 154 image from its EAP tar and give it the name the Dockerfile uses.
#   bash iris/scripts/load-image.sh <path to irishealth-community-2026.3.0AI.154.0-docker.tar.gz>
# The image (and any image built on it) is never pushed to a registry.
set -euo pipefail
tar="${1:?pass the image tar from the EAP portal}"
want="irishealth-community:2026.3.0AI.154.0"
[ -s "$tar" ] || { echo "no such file: $tar"; exit 1; }
out=$(docker load -i "$tar")
echo "$out"
loaded=$(printf '%s\n' "$out" | sed -n 's/^Loaded image: //p' | tail -1)
[ -n "$loaded" ] || loaded=$(printf '%s\n' "$out" | sed -n 's/^Loaded image ID: //p' | tail -1)
[ -n "$loaded" ] || { echo "docker load named no image"; exit 1; }
docker tag "$loaded" "$want"
echo "loaded: $loaded"
echo "tagged: $want"
