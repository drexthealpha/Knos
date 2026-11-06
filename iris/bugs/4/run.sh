#!/usr/bin/env bash
# Embedded Python: iris.sql.exec("SELECT ?", <an int past 64 bits>) fails with SystemError, not an error naming the value.
#   bash iris/bugs/4/run.sh <container>      (USER namespace)
set -euo pipefail
c="${1:-knos-iris}"
here="$(cd "$(dirname "$0")" && pwd)"
for f in Bug4.cls probe.script; do docker cp "$here/$f" "$c:/tmp/$f"; done
docker exec "$c" bash -c "iris session IRIS -U USER < /tmp/probe.script" | grep -aE "^(load|py |os )"
