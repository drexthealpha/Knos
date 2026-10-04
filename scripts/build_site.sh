#!/usr/bin/env bash
# Assemble the Pages site:  bash scripts/build_site.sh <out dir> <commit sha>
# The web app, the JavaScript client it imports, the passkey wallet's helper, the claim workflow and the second deployment's program ids (the
# first deployment's addresses are in the page, as history). A template that still names its workflows by
# KNOS_COMMIT_SHA is given the commit the site was built from; the page hands out a file only when every workflow it
# calls is named by a full commit, so a placeholder left in one is said on the page and never handed out.
# The public record as static files (bounties.json, u/, r/, badge/, rank/, latency.json, operations.json) is written
# here with nothing measured, so a build with no network has every file and each says it is empty; the Pages build
# (.github/workflows/network.yml) writes them again from the chain and GitHub.
set -euo pipefail
cd "$(dirname "$0")/.."
out="$1"; sha="$2"
case "$sha" in *[!0-9a-f]*|"") echo "the commit must be a full sha"; exit 1;; esac
[ "${#sha}" = 40 ] || { echo "the commit must be a full sha"; exit 1; }
mkdir -p "$out"
cp -r web/. "$out/"
cp src/knos/settle/v2/program_ids.json "$out/program_ids.json"
cp sdk/settle/index.js "$out/settle.js"
cp sdk/settle/passkey.js "$out/passkey.js"
cp examples/knos-claim.yml "$out/knos-claim.yml"
sed -i.bak "s/KNOS_COMMIT_SHA/$sha/g" "$out/front.js" && rm -f "$out/front.js.bak"
! grep -q KNOS_COMMIT_SHA "$out/front.js"
# The recording at the top of the first screen is a release asset: web/config.js says none until KNOS_VIDEO_URL (and,
# optionally, KNOS_VIDEO_POSTER) name one, and only this repository's own release downloads are accepted.
asset='^https://github\.com/drexthealpha/Knos/releases/download/[A-Za-z0-9._%/-]+$'
if [ -n "${KNOS_VIDEO_URL:-}" ]; then
  printf '%s' "$KNOS_VIDEO_URL" | grep -Eq "$asset" || { echo "KNOS_VIDEO_URL must be a release download of drexthealpha/Knos"; exit 1; }
  poster=null
  if [ -n "${KNOS_VIDEO_POSTER:-}" ]; then
    printf '%s' "$KNOS_VIDEO_POSTER" | grep -Eq "$asset" || { echo "KNOS_VIDEO_POSTER must be a release download of drexthealpha/Knos"; exit 1; }
    poster="\"$KNOS_VIDEO_POSTER\""
  fi
  sed -i.bak "s|^  video: null,|  video: { src: \"$KNOS_VIDEO_URL\", poster: $poster },|" "$out/config.js" && rm -f "$out/config.js.bak"
  grep -q "video: { src" "$out/config.js"
fi
"${PYTHON:-python3}" scripts/pages_data.py --out "$out" --empty
