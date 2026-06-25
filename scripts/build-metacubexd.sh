#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

METACUBEXD_VERSION="${METACUBEXD_VERSION:-1.261.8}"
CONFIG_HELPER_CACHE_BUST="${CONFIG_HELPER_CACHE_BUST:-v${METACUBEXD_VERSION//./}}"
ARCHIVE="$ROOT/vendor/metacubexd/compressed-dist-v${METACUBEXD_VERSION}.tgz"
PORT="${PORT:-3001}"
MODE="${1:-upgrade}"

compose() {
  docker compose "$@"
}

check_archive() {
  if [ ! -f "$ARCHIVE" ]; then
    echo "Missing MetaCubeXD archive: $ARCHIVE" >&2
    exit 1
  fi

  tar -tzf "$ARCHIVE" ./index.html >/dev/null
  tar -tzf "$ARCHIVE" ./_nuxt/ >/dev/null
}

build_image() {
  compose build \
    --build-arg "METACUBEXD_VERSION=$METACUBEXD_VERSION" \
    --build-arg "CONFIG_HELPER_CACHE_BUST=$CONFIG_HELPER_CACHE_BUST" \
    metacubexd
}

start_service() {
  compose up -d --no-deps metacubexd
}

wait_for_panel() {
  for _ in $(seq 1 30); do
    if html="$(curl -fsS "http://127.0.0.1:$PORT" 2>/dev/null)"; then
      printf "%s" "$html" | grep -q "appVersion:\"$METACUBEXD_VERSION\""
      printf "%s" "$html" | grep -q "config-helper.js?v=$CONFIG_HELPER_CACHE_BUST"
      printf "%s" "$html" | grep -q "local-backend"
      compose ps metacubexd
      echo "MetaCubeXD upgraded locally: http://127.0.0.1:$PORT"
      return 0
    fi
    sleep 2
  done

  echo "MetaCubeXD did not become reachable in time. Recent logs:" >&2
  compose logs --tail=120 metacubexd >&2 || true
  exit 1
}

case "$MODE" in
  upgrade)
    echo "[1/4] Checking MetaCubeXD archive..."
    check_archive
    echo "[2/4] Building MetaCubeXD image..."
    build_image
    echo "[3/4] Restarting local MetaCubeXD service..."
    start_service
    echo "[4/4] Waiting for local panel..."
    wait_for_panel
    ;;
  build)
    check_archive
    build_image
    ;;
  restart)
    start_service
    wait_for_panel
    ;;
  status)
    compose ps metacubexd
    ;;
  *)
    echo "Usage: $0 [upgrade|build|restart|status]" >&2
    exit 1
    ;;
esac
