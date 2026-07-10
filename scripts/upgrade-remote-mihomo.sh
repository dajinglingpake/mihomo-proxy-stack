#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONFIG_FILE="${CONFIG_FILE:-$ROOT/scripts/upgrade-remote-mihomo.local.env}"
if [ -f "$CONFIG_FILE" ]; then
  set -a
  . "$CONFIG_FILE"
  set +a
fi

REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_USER="${REMOTE_USER:-}"
REMOTE_PASS="${REMOTE_PASS:-}"
SUDO_PASS="${SUDO_PASS:-$REMOTE_PASS}"
REMOTE_DIR="${REMOTE_DIR:-/volume1/docker/mihomo}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
PORT="${PORT:-3001}"
REBUILD="${REBUILD:-1}"
PULL_TIMEOUT_SECONDS="${PULL_TIMEOUT_SECONDS:-}"
METACUBEXD_VERSION="${METACUBEXD_VERSION:-1.267.0}"
CONFIG_HELPER_CACHE_BUST="${CONFIG_HELPER_CACHE_BUST:-v${METACUBEXD_VERSION//./}-groups11}"
MIHOMO_SYNC_VERSION="${MIHOMO_SYNC_VERSION:-local}"
METACUBEXD_IMAGE="mihomo-metacubexd:$METACUBEXD_VERSION"
MIHOMO_SYNC_IMAGE="mihomo-sync:$MIHOMO_SYNC_VERSION"
REMOTE_IMAGE_TAR="${REMOTE_IMAGE_TAR:-/tmp/mihomo-project-images.tar}"
EXTERNAL_IMAGES=(
  "metacubex/mihomo:latest"
  "xream/sub-store:latest"
  "nginx:alpine"
)

SSH_OPTIONS=(
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR
)

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

require_var() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Missing required config: $name" >&2
    echo "Create $CONFIG_FILE from scripts/upgrade-remote-mihomo.local.env.example" >&2
    exit 1
  fi
}

shell_quote() {
  printf "'%s'" "$(printf "%s" "$1" | sed "s/'/'\\\\''/g")"
}

ssh_remote() {
  SSHPASS="$REMOTE_PASS" sshpass -e ssh "${SSH_OPTIONS[@]}" "$REMOTE_USER@$REMOTE_HOST" "$@"
}

sudo_remote() {
  local cmd="$1"
  ssh_remote "printf '%s\n' $(shell_quote "$SUDO_PASS") | sudo -S -p '' sh -lc $(shell_quote "PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/var/packages/ContainerManager/target/usr/bin:\$PATH; $cmd")"
}

compose_remote() {
  local args="$1"
  sudo_remote "cd $(shell_quote "$REMOTE_DIR") && if docker compose version >/dev/null 2>&1; then docker compose -f $(shell_quote "$COMPOSE_FILE") $args; else docker-compose -f $(shell_quote "$COMPOSE_FILE") $args; fi"
}

remote_docker_arch() {
  sudo_remote "docker info --format '{{.Architecture}}'"
}

print_stack_status() {
  sudo_remote "cd $(shell_quote "$REMOTE_DIR") && if docker compose version >/dev/null 2>&1; then docker compose -f $(shell_quote "$COMPOSE_FILE") ps; else docker-compose -f $(shell_quote "$COMPOSE_FILE") ps; fi"
}

pull_external_images_local() {
  local pull_cmd=(docker compose pull mihomo sub-store proxy-portal)
  if [ -n "$PULL_TIMEOUT_SECONDS" ]; then
    pull_cmd=(timeout "$PULL_TIMEOUT_SECONDS" "${pull_cmd[@]}")
  fi
  "${pull_cmd[@]}" || {
    echo "Failed to pull external images locally. Deployment stopped to avoid publishing old images." >&2
    exit 1
  }
}

check_docker_arch() {
  local local_arch
  local remote_arch
  local_arch="$(docker info --format '{{.Architecture}}' | tr -d '\r')"
  remote_arch="$(remote_docker_arch | tr -d '\r')"
  if [ "$local_arch" != "$remote_arch" ]; then
    echo "Docker architecture mismatch: local=$local_arch remote=$remote_arch" >&2
    exit 1
  fi
}

build_project_images() {
  docker compose build metacubexd mihomo-sync
}

load_images_remote() {
  docker save "$METACUBEXD_IMAGE" "$MIHOMO_SYNC_IMAGE" "${EXTERNAL_IMAGES[@]}" | ssh_remote "cat > $(shell_quote "$REMOTE_IMAGE_TAR")"
  sudo_remote "docker load -i $(shell_quote "$REMOTE_IMAGE_TAR") && rm -f $(shell_quote "$REMOTE_IMAGE_TAR")"
}

sync_project() {
  sudo_remote "mkdir -p $(shell_quote "$REMOTE_DIR") && uid=\$(id -u $(shell_quote "$REMOTE_USER")) && gid=\$(id -g $(shell_quote "$REMOTE_USER")) && chown -R \"\$uid:\$gid\" $(shell_quote "$REMOTE_DIR")"
  tar \
    --exclude './.git' \
    --exclude './.codex' \
    --exclude './.debug-substore-*.js' \
    --exclude './metacubexd-gh-pages.zip' \
    --exclude './config/*.local.*' \
    --exclude './scripts/upgrade-remote-mihomo.local.env' \
    -C "$ROOT" \
    -cf - . | ssh_remote "tar -C $(shell_quote "$REMOTE_DIR") -xmf -"
}

wait_for_panel() {
  for _ in $(seq 1 30); do
    if html="$(curl -fsS "http://$REMOTE_HOST:$PORT" 2>/dev/null)"; then
      printf "%s" "$html" | grep -q "appVersion:\"$METACUBEXD_VERSION\"" || {
        sleep 2
        continue
      }
      printf "%s" "$html" | grep -q "config-helper.js?v=$CONFIG_HELPER_CACHE_BUST" || {
        sleep 2
        continue
      }
      printf "%s" "$html" | grep -q "local-backend" || {
        sleep 2
        continue
      }
      print_stack_status
      echo "mihomo stack upgraded: http://$REMOTE_HOST:$PORT"
      exit 0
    fi
    sleep 2
  done

  echo "mihomo stack did not become reachable in time. Recent logs:" >&2
  sudo_remote "cd $(shell_quote "$REMOTE_DIR") && if docker compose version >/dev/null 2>&1; then docker compose -f $(shell_quote "$COMPOSE_FILE") logs --tail=120; else docker-compose -f $(shell_quote "$COMPOSE_FILE") logs --tail=120; fi" >&2 || true
  exit 1
}

MODE="${1:-upgrade}"
case "$MODE" in
  upgrade) ;;
  status)
    require_cmd sshpass
    require_var REMOTE_HOST
    require_var REMOTE_USER
    require_var REMOTE_PASS
    require_var SUDO_PASS
    print_stack_status
    exit 0
    ;;
  *)
    echo "Usage: $0 [upgrade|status]" >&2
    exit 1
    ;;
esac

echo "[1/6] Checking local tools..."
require_cmd sshpass
require_cmd tar
require_cmd curl
require_cmd docker
if [ -n "$PULL_TIMEOUT_SECONDS" ]; then
  require_cmd timeout
fi
require_var REMOTE_HOST
require_var REMOTE_USER
require_var REMOTE_PASS
require_var SUDO_PASS

echo "[2/6] Checking remote Docker..."
ssh_remote "test -d $(shell_quote "$REMOTE_DIR") || true"
sudo_remote "command -v docker; docker --version; docker compose version 2>/dev/null || docker-compose version 2>/dev/null"
check_docker_arch

echo "[3/6] Pulling external images and building project images locally..."
pull_external_images_local
build_project_images

echo "[4/6] Syncing project files and images..."
sync_project
load_images_remote

echo "[5/6] Starting remote stack..."
compose_remote "up -d --force-recreate --no-build"

echo "[6/6] Waiting for panel..."
wait_for_panel
