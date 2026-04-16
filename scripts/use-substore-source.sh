#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "用法: $0 sub|collection 名称"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
STACK_ENV_FILE="${BASE_DIR}/config/stack.env"

if [[ ! -f "${STACK_ENV_FILE}" ]]; then
  echo "缺少共享配置文件: ${STACK_ENV_FILE}"
  exit 1
fi

kind="$1"
name="$2"

if [[ "${kind}" != "sub" && "${kind}" != "collection" ]]; then
  echo "第一个参数只能是 sub 或 collection"
  exit 1
fi

# shellcheck disable=SC1090
source "${STACK_ENV_FILE}"

: "${SUBSTORE_BASE_URL:=http://127.0.0.1:3001/substore}"

encoded_name="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "${name}")"
new_url="${SUBSTORE_BASE_URL}/download/"

if [[ "${kind}" == "collection" ]]; then
  new_url+="collection/"
fi

new_url+="${encoded_name}?target=ClashMeta"

python3 - "${STACK_ENV_FILE}" "${new_url}" <<'PY'
import re
import sys
from pathlib import Path

env_file = Path(sys.argv[1])
new_url = sys.argv[2]
text = env_file.read_text(encoding="utf-8")
updated, count = re.subn(
    r'^SUBSCRIPTION_URL=".*"$',
    f'SUBSCRIPTION_URL="{new_url}"',
    text,
    count=1,
    flags=re.MULTILINE,
)
if count == 0:
    updated = text.rstrip() + f'\nSUBSCRIPTION_URL="{new_url}"\n'
env_file.write_text(updated, encoding="utf-8")
PY

echo "已切换 mihomo 订阅源:"
echo "${new_url}"
echo
echo "执行以下命令使其生效:"
echo "bash \"${BASE_DIR}/scripts/update-subscription.sh\""
