#!/usr/bin/env bash
# Is the online demo up? Run it once a day while people review it:
#   bash iris/uptime-check.sh http://<the VM's address>:52773 [demo password]
# It opens the page, signs in as the read-only user and reads the decisions, then prints UP or DOWN with the reason,
# and adds the line to uptime-log.txt beside this script. Exit 0 when up, 1 when down.
set -u
base="${1:?usage: bash iris/uptime-check.sh http://<host>:52773 [demo password]}"
base="${base%/}"
pass="${2:-demo}"
log="$(cd "$(dirname "$0")" && pwd)/uptime-log.txt"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
say() { echo "$now $1" | tee -a "$log"; }
page=$(curl -s -o /dev/null -m 20 -w '%{http_code} %{time_total}' "$base/knos/") || page="000 0"
[ "${page%% *}" = 200 ] || { say "DOWN: the page $base/knos/ answered ${page%% *}"; exit 1; }
body=$(curl -s -m 30 -u "demo:$pass" -w '\n%{http_code}' "$base/api/knos/decisions") || body=$'\n000'
code="${body##*$'\n'}"
[ "$code" = 200 ] || { say "DOWN: signing in as demo and reading decisions answered $code"; exit 1; }
n=$(printf '%s' "${body%$'\n'*}" | grep -o '"brief"' | wc -l)
[ "$n" -gt 0 ] || { say "DOWN: signed in, but no decision is shown (run iris/cloud-start.sh again)"; exit 1; }
say "UP: page in ${page#* } s, $n decisions readable as demo"
