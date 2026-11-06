#!/usr/bin/env bash
# AI Hub: %AI.RAG.VectorStore.IRIS makes its table in SQLUser whatever its Schema property says.
#   bash iris/bugs/3/run.sh <container>      (USER namespace)
set -euo pipefail
c="${1:-knos-iris}"
here="$(cd "$(dirname "$0")" && pwd)"
docker cp "$here/probe.script" "$c:/tmp/probe3.script"
docker exec "$c" bash -c "iris session IRIS -U USER < /tmp/probe3.script" | grep -aE "^(build|the store|table made)"
