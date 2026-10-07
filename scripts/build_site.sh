#!/usr/bin/env bash
# Assemble the Pages site:  bash scripts/build_site.sh <out dir> <commit sha>
# The web app, the JavaScript client it imports, the passkey wallet's helper, the claim workflow, the capability manifest
# (docs/capabilities.json, which the Capabilities page reads) and the second deployment's program ids (the
# first deployment's addresses are in the page, as history). A template that still names its workflows by
# KNOS_COMMIT_SHA is given the commit the site was built from; the page hands out a file only when every workflow it
# calls is named by a full commit, so a placeholder left in one is said on the page and never handed out.
# The public record as static files (bounties.json, u/, r/, badge/, rank/, latency.json, operations.json) is written
# here with nothing measured, so a build with no network has every file and each says it is empty; the Pages build
# (.github/workflows/network.yml) writes them again from the chain and GitHub.
# The Index page reads the repository's weekly table (docs/agent_weekly.json). The Reproduce page counts the reproductions
# people outside have sent: the build carries the JSON files of reproductions/ and reproductions.json, their names
# ({"files": []} while the folder holds none).
# The registry of published terms (terms/) is carried whole, and web/demo_data.json is held to the documents it is cut from.
# The upgrade feed (upgrades.json, upgrades.xml) is the committed one of web/; the Pages build runs
# scripts/upgrade_feed.py on it, which writes nothing when the cluster does not answer, so the committed files stay.
set -euo pipefail
cd "$(dirname "$0")/.."
out="$1"; sha="$2"
case "$sha" in *[!0-9a-f]*|"") echo "the commit must be a full sha"; exit 1;; esac
[ "${#sha}" = 40 ] || { echo "the commit must be a full sha"; exit 1; }
mkdir -p "$out"
cp -r web/. "$out/"
# the documents the command palette can open (web/palette.js reads it; without it the palette has no documents)
"${PYTHON:-python3}" scripts/docs_index.py "$out/docs_index.json"
# The name in the bar, the favicon and the card of a shared link are files of web/ (web/brand/, written by
# scripts/brand.py and committed). The traced originals they were made from stay in the repository.
rm -rf "$out/brand/src"
for f in icon.svg brand/mark.svg brand/wordmark.svg brand/mark.js brand/apple-touch-icon.png brand/card.png; do
  [ -s "$out/$f" ] || { echo "web/$f is missing: python scripts/brand.py --png writes it"; exit 1; }
done
cp src/knos/settle/v2/program_ids.json "$out/program_ids.json"
cp sdk/settle/index.js "$out/settle.js"
cp sdk/settle/passkey.js "$out/passkey.js"
cp examples/knos-claim.yml "$out/knos-claim.yml"
cp docs/capabilities.json "$out/capabilities.json"
cp docs/agent_weekly.json "$out/agent_weekly.json"
# The Index page's leaderboard also reads the feed (which rows are disputed, and where), and the page links its Atom
# feed; both are held to the weekly table first.
"${PYTHON:-python3}" scripts/agent_pr_index.py board --check
cp docs/index.json "$out/agent_index.json"
cp docs/index.atom "$out/index.atom"
# A supplier's public record (docs/RECORD.md): the file and its badge, which the record page reads.
mkdir -p "$out/records" && cp docs/records/*.json "$out/records/"
# The registry of published terms (terms/, which scripts/terms_registry.py builds): the Terms page reads terms/index.json,
# and the address `knos terms cite` prints is a file here.
rm -rf "$out/terms" && cp -r terms "$out/terms"
# The round the first screen replays (web/demo_data.json) is cut out of this repository's documents: a build whose
# copy is not what they say stops here.
"${PYTHON:-python3}" scripts/demo_data.py --check
"${PYTHON:-python3}" - "$out" <<'PY'
import json, shutil, sys
from pathlib import Path
out = Path(sys.argv[1])
files = sorted(p for p in Path("reproductions").glob("*.json") if p.is_file())
for p in files:
    (out / "reproductions").mkdir(exist_ok=True)
    shutil.copyfile(p, out / "reproductions" / p.name)
(out / "reproductions.json").write_text(json.dumps({"files": [p.name for p in files]}) + "\n", encoding="utf-8", newline="")
PY
# The Buy page is web/buyer.js. A build without it gets a file that fills nothing, so the page asks for no file that
# is not there and the menu does not offer Buy.
[ -f "$out/buyer.js" ] || printf '%s\n' '// No Buy page in this build.' 'export const renderBuyer = () => {};' > "$out/buyer.js"
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
