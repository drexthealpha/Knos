#!/usr/bin/env bash
# The online demo of Knos Referee on IRIS on a fresh Ubuntu 24.04 VM, in one command:
#   curl -fsSL https://raw.githubusercontent.com/drexthealpha/Knos/main/iris/cloud-start.sh | sudo bash -s -- <build 154 image tar>
# It installs Docker, starts IRIS and the local model (scripts/demo-vm.sh), runs three decisions on public data, sends
# one 80 USDC decision and approves it in IRIS Workflow, so the page shows a decision, its tokens and its approval.
# The demo user (read only: it can open everything and change nothing) is "demo" with the password DEMO_PASSWORD
# (default "demo"), so anyone with the URL can look.
set -euo pipefail
tar="${1:-}"
[ -n "$tar" ] || { echo "usage: sudo bash cloud-start.sh <irishealth-community-2026.3.0AI.154.0-docker.tar.gz>" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run it with sudo" >&2; exit 2; }
pass="${DEMO_PASSWORD:-demo}"
repo=/opt/knos
command -v git > /dev/null || { apt-get update -q && apt-get install -y -q git; }
[ -d "$repo/.git" ] || git clone --depth 1 https://github.com/drexthealpha/Knos "$repo"
umask 077
printf '%s' "$pass" > "$repo/iris/.demo-user"
bash "$repo/iris/scripts/demo-vm.sh" "$tar"
cd "$repo/iris"
set -a; . ./.env; set +a
auth="_SYSTEM:$IRIS_PASSWORD"
echo "== three decisions on public data"
bash scripts/public-decisions.sh
echo "== one decision above 50 USDC, approved in IRIS Workflow"
AMOUNT_USDC=80 bash scripts/smoke.sh | grep -E "^(gate|visual trace):" || true
PY=python3; command -v "$PY" > /dev/null || PY=python
for _ in $(seq 1 30); do
  id=$(curl -fsS -u "$auth" localhost:52773/api/knos/tasks | "$PY" -c 'import json,sys; t=[x for x in json.load(sys.stdin) if x.get("open")]; print(t[0]["id"] if t else "")')
  [ -n "$id" ] && break; sleep 2
done
[ -n "$id" ] && curl -fsS -u "$auth" -H 'Content-Type: application/json' -X POST "localhost:52773/api/knos/tasks/$id" -d '{"action":"Approve"}' > /dev/null && echo "approved task $id"
host=$(curl -fsS -m 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
echo "== the demo"
echo "URL:      http://$host:52773/knos/"
echo "user:     demo   password: $pass   (read only)"
echo "Open port 52773 in the VM's network rules to share it."
