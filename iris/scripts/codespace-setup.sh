#!/usr/bin/env bash
# Prepare a GitHub Codespace (4 cores, 16 GB) to build and run the IRIS app.
#   bash iris/scripts/codespace-setup.sh [path to the image tar; default /workspaces/iris154.tar.gz]
# Docker's images go to /tmp (the large disk); the IRIS image is pulled once, else loaded from the tar.
# No key enters the codespace: iris/.env is made from .env.example only.
set -uo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
want="irishealth-community:2026.3.0AI.154.0"
# the tar is kept on /workspaces, which a stopped codespace keeps (/tmp, Docker's store, is emptied at every stop)
tar="${1:-/workspaces/iris154.tar.gz}"
log() { echo "$(date -u +%T) $*"; }

root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)
command -v setfacl >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq acl; }
# /tmp here carries a default ACL (other: rw-, no x): image layers extracted under it cannot be entered by a non-root
# build step (libc.so.6: Permission denied), and clearing the ACL afterwards leaves the x bits off. A stopped codespace
# loses /tmp, and containerd then makes /tmp/store again under that ACL: such a store is removed and made afresh.
bad_store() { [ ! -d /tmp/store/containerd ] || getfacl -p /tmp/store 2>/dev/null | grep -q '^default:'; }
# Docker here keeps images in containerd's store (/var/lib/containerd on the 32 GB disk): move that to /tmp as well
if ! grep -q "^root = '/tmp/store/containerd'" /etc/containerd/config.toml || bad_store; then
  log "making containerd root /tmp/store/containerd without /tmp's default ACL"
  sudo pkill dockerd; for i in $(seq 1 20); do pgrep -x dockerd >/dev/null || break; sleep 1; done
  sudo pkill -x containerd; for i in $(seq 1 20); do pgrep -x containerd >/dev/null || break; sleep 1; done
  sudo sed -i "s|^root = .*|root = '/tmp/store/containerd'|" /etc/containerd/config.toml
  sudo rm -rf /tmp/store
  sudo mkdir -p /tmp/store/containerd /tmp/store/docker && sudo setfacl -R -b -k /tmp/store && sudo chmod 711 /tmp/store /tmp/store/containerd
  sudo sh -c 'nohup containerd --config /etc/containerd/config.toml > /tmp/store/containerd.log 2>&1 &'
  sleep 3; root=""
fi
if [ "$root" != "/tmp/store/docker" ]; then
  log "moving docker data-root from $root to /tmp/store/docker"
  sudo mkdir -p /tmp/store/docker /etc/docker
  echo '{"data-root":"/tmp/store/docker"}' | sudo tee /etc/docker/daemon.json >/dev/null
  sudo pkill dockerd
  for i in $(seq 1 20); do pgrep -x dockerd >/dev/null || break; sleep 1; done
  sudo rm -f /var/run/docker.pid
  sudo sh -c 'nohup dockerd --containerd /run/containerd/containerd.sock --dns 168.63.129.16 > /tmp/store/dockerd.log 2>&1 &'
  for i in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 2; done
  log "docker root now $(docker info --format '{{.DockerRootDir}}')"
fi

if ! docker image inspect "$want" >/dev/null 2>&1; then
  t=$(date +%s)
  if docker pull "containers.intersystems.com/intersystems/$want"; then
    docker tag "containers.intersystems.com/intersystems/$want" "$want"
    log "image method=pull seconds=$(( $(date +%s) - t ))"
  elif [ -s "$tar" ]; then
    bash "$here/scripts/load-image.sh" "$tar" && log "image method=tar ($tar) seconds=$(( $(date +%s) - t ))"
  else
    log "no image: pull refused and no tar at $tar"; exit 1
  fi
fi
[ -f "$here/.env" ] || cp "$here/.env.example" "$here/.env"
log "ready: $(nproc) cores, $(free -g | awk '/Mem:/{print $2}') GB, docker $(docker version --format '{{.Server.Version}}')"
