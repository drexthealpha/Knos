#!/usr/bin/env bash
# Embedded Python, build 154: iris.sql.exec with keyword arguments ("on some builds" a SIGSEGV).
#   bash run.sh <container>    Shows the bug when the IRIS session dies (no "session alive" line).
set -uo pipefail
c="${1:?a build 154 container}"
here="$(cd "$(dirname "$0")" && pwd)"
command -v cygpath >/dev/null && here="$(cygpath -w "$here")"
export MSYS_NO_PATHCONV=1
out=$(docker exec -i "$c" iris session IRIS -U %SYS < "$here/repro.script" 2>&1)
echo "$out" | grep -v '^%SYS>\|^USER>\|^$' | tail -3
if echo "$out" | grep -q "session alive"; then echo "NOT REPRODUCED: keyword arguments raise TypeError, the process lives"; exit 1; fi
echo "REPRODUCED: the session died"; exit 0
