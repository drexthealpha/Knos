#!/usr/bin/env bash
# A fresh Ubuntu 24.04 VM (4 GB RAM or more) to the running referee in replay mode, with the Portal password changed.
#   scp irishealth-community-2026.3.0AI.154.0-docker.tar.gz you@vm:~
#   ssh you@vm 'curl -fsSL https://raw.githubusercontent.com/drexthealpha/Knos/main/iris/scripts/vm-setup.sh | bash -s -- ~/irishealth-community-2026.3.0AI.154.0-docker.tar.gz'
# The new password is written to ~/knos-iris-password (mode 600) and printed nowhere. Open port 52773 in the VM's firewall.
set -euo pipefail
tar="${1:?pass the build 154 image tar copied to the VM}"
[ -s "$tar" ] || { echo "no such file: $tar"; exit 1; }
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  sudo apt-get update -q
  sudo apt-get install -y -q docker.io docker-compose-v2 git
fi
sudo usermod -aG docker "$USER" || true
D="sudo docker"
[ -d ~/Knos ] || git clone -q --depth 1 https://github.com/drexthealpha/Knos ~/Knos
cd ~/Knos/iris
sudo bash scripts/load-image.sh "$tar"
pw_file=~/knos-iris-password
[ -s "$pw_file" ] || { (umask 077; head -c 18 /dev/urandom | base64 | tr -d '/+=' > "$pw_file"); }
pw=$(cat "$pw_file")
[ -f .env ] || cp .env.example .env
chmod 600 .env
grep -q '^IRIS_PASSWORD=' .env || printf 'IRIS_PASSWORD=%s\n' "$pw" >> .env
$D compose up -d --build
# the instance answers on SYS until its passwords change; wait for it, then change them
for i in $(seq 1 120); do
  $D exec knos-iris env IRIS_PASSWORD=SYS python3 -I /home/irisowner/knos/iris/scripts/knos_http.py http://localhost:52773/api/knos/health >/dev/null 2>&1 && break
  sleep 15
done
printf '%s\n' 'zn "%SYS"' 'set p("Password") = $system.Util.GetEnviron("IRIS_PASSWORD"), p("ChangePassword") = 0' \
  'for u = "_SYSTEM", "SuperUser", "Admin" { write u, " ", ##class(Security.Users).Modify(u, .p), ! }' 'halt' \
  | $D exec -i knos-iris iris session IRIS -U %SYS
h=$($D exec knos-iris python3 -I /home/irisowner/knos/iris/scripts/knos_http.py http://localhost:52773/api/knos/health || true)
echo "health: $h"
case "$h" in *'"production":"Running"'*) echo "ready: http://<this VM's address>:52773/api/knos/health (user _SYSTEM, password in $pw_file)";; *) exit 1;; esac
