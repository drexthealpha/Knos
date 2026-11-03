#!/usr/bin/env bash
# AI Hub, build 2026.3.0AI.154.0: %AI.ToolMgr.ExecuteTool ignores the required arguments and types its own schema advertises.
#   bash iris/bugs/2/run.sh <container>    Exit 0 and REPRODUCED when the bug shows.
set -uo pipefail
c="${1:?a build 154 container}"
here="$(cd "$(dirname "$0")" && pwd)"
export MSYS_NO_PATHCONV=1
docker cp "$here/EchoTool.cls" "$c:/tmp/Knos.Bugs.EchoTool.cls" >/dev/null
out=$(printf '%s\n' 'zn "USER"' 'do $system.OBJ.Load("/tmp/Knos.Bugs.EchoTool.cls", "ck-d")' 'do ##class(Knos.Bugs.EchoTool).Run()' 'halt' \
  | docker exec -i "$c" iris session IRIS -U %SYS 2>&1)
echo "$out" | grep -E '^(schema|ok   |BUG  )'
echo "$out" | grep -q '^RESULT=REPRODUCED' && { echo "REPRODUCED"; exit 0; }
echo "NOT REPRODUCED"; echo "$out" | grep '^RESULT=' ; exit 1
