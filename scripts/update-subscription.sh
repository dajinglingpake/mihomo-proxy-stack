#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${BASE_DIR}/config/config.yaml"
GEOIP_FILE="${BASE_DIR}/config/geoip.metadb"
MMDB_FILE="${BASE_DIR}/config/Country.mmdb"
STACK_ENV_FILE="${BASE_DIR}/config/stack.env"

if [[ -f "${STACK_ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${STACK_ENV_FILE}"
fi

: "${SUBSCRIPTION_URL:?SUBSCRIPTION_URL 未配置}"
: "${CONTROLLER_ADDR:=0.0.0.0:19090}"
: "${CONTROLLER_SECRET:=123456}"
GEOIP_URL="https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb"
MMDB_URL="https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/country.mmdb"

tmp_file="$(mktemp)"
trap 'rm -f "${tmp_file}"' EXIT

curl -L --fail --max-time 60 --silent --show-error "${SUBSCRIPTION_URL}" -o "${tmp_file}"
curl -L --fail --max-time 60 --silent --show-error "${GEOIP_URL}" -o "${GEOIP_FILE}"
curl -L --fail --max-time 60 --silent --show-error "${MMDB_URL}" -o "${MMDB_FILE}"

python3 - "${tmp_file}" "${CONFIG_FILE}" "${CONTROLLER_ADDR}" "${CONTROLLER_SECRET}" <<'PY'
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
controller = sys.argv[3]
secret = sys.argv[4]

text = src.read_text(encoding="utf-8")
text = text.replace("external-controller: '0.0.0.0:9090'", f"external-controller: '{controller}'", 1)
text = text.replace("secret: ''", f"secret: '{secret}'", 1)
if "geox-url:" not in text:
    marker = f"secret: '{secret}'"
    replacement = marker + "\ngeox-url:\n  geoip: 'https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb'\n  mmdb: 'https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/country.mmdb'"
    text = text.replace(marker, replacement, 1)
if "external-ui:" not in text:
    marker = f"secret: '{secret}'"
    replacement = marker + "\nexternal-ui: 'ui'"
    text = text.replace(marker, replacement, 1)
dst.write_text(text, encoding="utf-8")
PY

docker compose -f "${BASE_DIR}/docker-compose.yml" restart mihomo
