#!/usr/bin/env bash
# Try the classes in a running IRIS container without a rebuild: copy Knos and iris/ in, make the KNOS namespace
# (first time), load and compile, run Setup.   bash iris/scripts/compile-probe.sh <container>
set -uo pipefail
c="${1:-knos-iris-probe}"
here="$(cd "$(dirname "$0")/../.." && pwd)"
command -v cygpath >/dev/null && here="$(cygpath -w "$here")"
export MSYS_NO_PATHCONV=1
docker exec "$c" mkdir -p /home/irisowner/knos/src /home/irisowner/knos/inbox/oru /home/irisowner/knos/inbox/checkruns /home/irisowner/knos/java
docker cp "$here\src\knos" "$c:/home/irisowner/knos/src/"
docker cp "$here\iris" "$c:/home/irisowner/knos/"
docker exec "$c" sh -c 'pip3 install --quiet --break-system-packages --target /usr/irissys/mgr/python "solders>=0.21,<0.30" "base58>=2" 2>&1 | tail -2'
docker exec "$c" sh -c 'ln -sfn /home/irisowner/knos/src/knos /usr/irissys/mgr/python/knos && ln -sfn /home/irisowner/knos/iris/python/knos_iris /usr/irissys/mgr/python/knos_iris'
docker exec "$c" sh -c 'cd /home/irisowner/knos/iris/java && javac -d /tmp/pex -cp "/usr/irissys/dev/java/lib/1.8/*" src/main/java/knos/iris/pex/SolanaSubmitOperation.java && (cd /tmp/pex && jar xf /usr/irissys/dev/java/lib/1.8/intersystems-pex-1.0.0-shaded.jar) && jar cf /home/irisowner/knos/java/knos-iris-pex.jar -C /tmp/pex . && echo "java: built"'
docker exec -i "$c" sh -c 'iris session IRIS' < "$here\iris\iris.script"
