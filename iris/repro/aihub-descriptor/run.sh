#!/usr/bin/env bash
# AI Hub, build 154: on a fresh instance, creating an LLM provider fails with ERROR #26414 "No descriptor found for
# AI.LLM" until %ConfigStore.DescriptorManager.RebuildRegistry() has run. Run on a clean build 154 container:
#   bash run.sh <container>
# Shows the bug when the output holds "26414".
set -uo pipefail
c="${1:?a clean build 154 container}"
here="$(cd "$(dirname "$0")" && pwd)"
command -v cygpath >/dev/null && here="$(cygpath -w "$here")"
export MSYS_NO_PATHCONV=1
out=$(docker exec -i "$c" iris session IRIS -U %SYS < "$here/repro.script" 2>&1)
echo "$out" | grep -v "^%SYS>\|^$"
if echo "$out" | grep -q "26414"; then echo "REPRODUCED: ERROR #26414 on a fresh instance"; exit 0; fi
echo "NOT REPRODUCED"; exit 1
