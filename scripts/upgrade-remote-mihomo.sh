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
PULL_TIMEOUT_SECONDS="${PULL_TIMEOUT_SECONDS:-60}"

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

print_stack_status() {
  sudo_remote "cd $(shell_quote "$REMOTE_DIR") && if docker compose version >/dev/null 2>&1; then docker compose -f $(shell_quote "$COMPOSE_FILE") ps; else docker-compose -f $(shell_quote "$COMPOSE_FILE") ps; fi"
}

pull_external_images_remote() {
  sudo_remote "cd $(shell_quote "$REMOTE_DIR") && if docker compose version >/dev/null 2>&1; then timeout $(shell_quote "$PULL_TIMEOUT_SECONDS") docker compose -f $(shell_quote "$COMPOSE_FILE") pull mihomo sub-store proxy-portal; else timeout $(shell_quote "$PULL_TIMEOUT_SECONDS") docker-compose -f $(shell_quote "$COMPOSE_FILE") pull mihomo sub-store proxy-portal; fi || echo 'Warning: failed to pull external images within $(shell_quote "$PULL_TIMEOUT_SECONDS")s; reusing local images. Core may still show an older version.' >&2"
}

sync_project() {
  sudo_remote "mkdir -p $(shell_quote "$REMOTE_DIR") && uid=\$(id -u $(shell_quote "$REMOTE_USER")) && gid=\$(id -g $(shell_quote "$REMOTE_USER")) && chown -R \"\$uid:\$gid\" $(shell_quote "$REMOTE_DIR")"
  tar \
    --exclude './.git' \
    --exclude './.codex' \
    --exclude './.debug-substore-*.js' \
    --exclude './metacubexd-gh-pages.zip' \
    --exclude './scripts/upgrade-remote-mihomo.local.env' \
    -C "$ROOT" \
    -cf - . | ssh_remote "tar -C $(shell_quote "$REMOTE_DIR") -xmf -"
}

wait_for_panel() {
  for _ in $(seq 1 30); do
    if curl -fsS "http://$REMOTE_HOST:$PORT" >/dev/null; then
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

echo "[1/5] Checking local tools..."
require_cmd sshpass
require_cmd tar
require_cmd curl
require_var REMOTE_HOST
require_var REMOTE_USER
require_var REMOTE_PASS
require_var SUDO_PASS

echo "[2/5] Checking remote Docker..."
ssh_remote "test -d $(shell_quote "$REMOTE_DIR") || true"
sudo_remote "command -v docker; docker --version; docker compose version 2>/dev/null || docker-compose version 2>/dev/null"

echo "[3/5] Syncing project files..."
sync_project

echo "[4/5] Starting remote stack..."
if [ "$REBUILD" = "1" ]; then
  pull_external_images_remote
  compose_remote "up -d --build --force-recreate"
else
  compose_remote "up -d"
fi

echo "[5/5] Waiting for panel..."
wait_for_panel
