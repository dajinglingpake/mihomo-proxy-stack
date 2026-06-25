#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

METACUBEXD_VERSION="${METACUBEXD_VERSION:-1.261.8}"
CONFIG_HELPER_CACHE_BUST="${CONFIG_HELPER_CACHE_BUST:-v${METACUBEXD_VERSION//./}}"
PORT="${PORT:-3001}"
MODE="${1:-upgrade}"
ARCHIVE="$ROOT/vendor/metacubexd/compressed-dist-v${METACUBEXD_VERSION}.tgz"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

check_archive() {
  if [ ! -f "$ARCHIVE" ]; then
    echo "Missing MetaCubeXD archive: $ARCHIVE" >&2
    exit 1
  fi

  tar -tzf "$ARCHIVE" ./index.html >/dev/null
  tar -tzf "$ARCHIVE" ./_nuxt/ >/dev/null
}

compose() {
  docker compose "$@"
}

wait_for_panel() {
  for _ in $(seq 1 30); do
    if html="$(curl -fsS "http://127.0.0.1:$PORT" 2>/dev/null)"; then
      printf "%s" "$html" | grep -q "appVersion:\"$METACUBEXD_VERSION\""
      printf "%s" "$html" | grep -q "config-helper.js?v=$CONFIG_HELPER_CACHE_BUST"
      printf "%s" "$html" | grep -q "local-backend"
      compose ps
      echo "mihomo stack upgraded locally: http://127.0.0.1:$PORT"
      return 0
    fi
    sleep 2
  done

  echo "mihomo stack did not become reachable in time. Recent logs:" >&2
  compose logs --tail=120 >&2 || true
  exit 1
}

case "$MODE" in
  upgrade)
    echo "[1/4] Checking local tools..."
    require_cmd docker
    require_cmd tar
    require_cmd curl
    echo "[2/4] Checking MetaCubeXD archive..."
    check_archive
    echo "[3/4] Building and recreating local stack..."
    compose up -d --build --force-recreate
    echo "[4/4] Waiting for local panel..."
    wait_for_panel
    ;;
  status)
    require_cmd docker
    compose ps
    ;;
  *)
    echo "Usage: $0 [upgrade|status]" >&2
    exit 1
    ;;
esac
