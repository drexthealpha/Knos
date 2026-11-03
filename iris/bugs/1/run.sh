#!/usr/bin/env bash
# Embedded Python, build 2026.3.0AI.154.0: a Python int past the signed 64-bit range becomes -1 in ObjectScript.
#   bash iris/bugs/1/run.sh <container>    Exit 0 and REPRODUCED when the bug shows.
set -uo pipefail
c="${1:?a build 154 container}"
here="$(cd "$(dirname "$0")" && pwd)"
export MSYS_NO_PATHCONV=1
docker cp "$here/BigInt.cls" "$c:/tmp/Knos.Bugs.BigInt.cls" >/dev/null
out=$(printf '%s\n' 'zn "USER"' 'do $system.OBJ.Load("/tmp/Knos.Bugs.BigInt.cls", "ck-d")' 'do ##class(Knos.Bugs.BigInt).Run()' 'halt' \
  | docker exec -i "$c" iris session IRIS -U %SYS 2>&1)
echo "$out" | grep -E '^(ok  |BUG )'
echo "$out" | grep -q '^RESULT=REPRODUCED' && { echo "REPRODUCED"; exit 0; }
echo "NOT REPRODUCED"; exit 1
