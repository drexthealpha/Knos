#!/usr/bin/env bash
# The online demo on a fresh Ubuntu 24.04 VM (x64 or arm64): Docker from Docker's own apt repository, the build 154
# image from its tar, the production with the local model (KNOS_AI_MODE=local, no key) and a read-only demo user.
# Prints the demo URL. Creates no account anywhere; the image tar comes from the EAP portal and is never pushed.
#
#   sudo bash demo-vm.sh <path to the build 154 image tar for this VM's architecture> [--dry-run]
#
# --dry-run prints every command and runs none of them.
set -euo pipefail

tar="" dry=0
for a in "$@"; do
  case "$a" in
    --dry-run) dry=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) tar="$a" ;;
  esac
done
[ -n "$tar" ] || { echo "usage: sudo bash demo-vm.sh <image tar> [--dry-run]" >&2; exit 2; }

run() { if [ "$dry" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }
say() { echo "== $*"; }

repo=/opt/knos
user=demo

case "$(uname -m)" in
  x86_64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) echo "this VM is $(uname -m); the demo runs on x86_64 or aarch64" >&2; exit 2 ;;
esac
if [ "$dry" = 0 ]; then
  [ "$(id -u)" = 0 ] || { echo "run it with sudo" >&2; exit 2; }
  [ -s "$tar" ] || { echo "no such file: $tar" >&2; exit 2; }
  # shellcheck source=/dev/null
  . /etc/os-release
  [ "${VERSION_ID:-}" = "24.04" ] || echo "warning: written for Ubuntu 24.04, this is ${PRETTY_NAME:-unknown}" >&2
fi

say "Docker Engine and the compose plugin, from Docker's apt repository ($arch)"
if [ "$dry" = 1 ] || ! command -v docker >/dev/null 2>&1; then
  run apt-get update -q
  run apt-get install -y -q ca-certificates curl git openssl
  run install -m 0755 -d /etc/apt/keyrings
  run curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  run chmod a+r /etc/apt/keyrings/docker.asc
  line="deb [arch=$arch signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable"
  if [ "$dry" = 1 ]; then printf '+ echo %q > /etc/apt/sources.list.d/docker.list\n' "$line"; else echo "$line" > /etc/apt/sources.list.d/docker.list; fi
  run apt-get update -q
  run apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  run systemctl enable --now docker
fi

say "the code"
if [ "$dry" = 1 ] || [ ! -d "$repo/.git" ]; then run git clone --depth 1 https://github.com/drexthealpha/Knos "$repo"; fi

say "the IRIS for Health image (build 154) from its tar"
run bash "$repo/iris/scripts/load-image.sh" "$tar"
if [ "$dry" = 0 ]; then
  got=$(docker image inspect --format '{{.Architecture}}' irishealth-community:2026.3.0AI.154.0)
  [ "$got" = "$arch" ] || { echo "the tar holds a $got image and this VM is $arch: use the tar for $arch" >&2; exit 2; }
fi

say "the production, with the local model (no key)"
cd "$repo/iris" 2>/dev/null || [ "$dry" = 1 ]
if [ "$dry" = 1 ]; then
  echo "+ cd $repo/iris"
  echo "+ cp .env.example .env"
  echo "+ bash scripts/env-secrets.sh"
  echo "+ sed -i s/^KNOS_AI_MODE=.*/KNOS_AI_MODE=local/ .env"
else
  [ -f .env ] || cp .env.example .env
  bash scripts/env-secrets.sh
  sed -i 's/^KNOS_AI_MODE=.*/KNOS_AI_MODE=local/' .env
fi
run docker compose up -d --build
if [ "$dry" = 1 ]; then
  echo "+ wait for http://localhost:52773/api/knos/health to say production Running"
else
  set -a
  # shellcheck source=/dev/null
  . ./.env
  set +a
  for _ in $(seq 1 120); do
    h=$(curl -fsS -u "_SYSTEM:$IRIS_PASSWORD" http://localhost:52773/api/knos/health 2>/dev/null || true)
    case "$h" in *'"production":"Running"'*) break ;; esac
    sleep 10
  done
  echo "health: $h"
  case "$h" in *'"production":"Running"'*) ;; *) echo "the production did not start; see: docker compose logs iris" >&2; exit 1 ;; esac
fi

say "the read-only demo user"
if [ "$dry" = 1 ]; then
  echo "+ openssl rand -hex 12 > $repo/iris/.demo-user   (mode 600)"
  echo "+ docker exec -i knos-iris iris session IRIS -U KNOS   <<< do ##class(Knos.Iris.Setup).DemoUser(\"$user\", <the password>)"
else
  umask 077
  [ -s .demo-user ] || openssl rand -hex 12 > .demo-user
  pass=$(cat .demo-user)
  printf 'set sc = ##class(Knos.Iris.Setup).DemoUser("%s", "%s")\nwrite "DEMOUSER=", sc, !\nhalt\n' "$user" "$pass" \
    | docker exec -i knos-iris iris session IRIS -U KNOS | grep -q 'DEMOUSER=1' || { echo "the demo user was not made" >&2; exit 1; }
fi

host=$(hostname -I 2>/dev/null | awk '{print $1}')
say "the demo"
echo "URL:      http://${host:-<the VM address>}:52773/knos/"
echo "user:     $user (reads decisions, traces and tasks; cannot send proof or approve)"
echo "password: in $repo/iris/.demo-user"
echo "Open port 52773 in the VM's firewall to share it."
