#!/bin/sh

set -eu

CONFIG_DIR="/root/.config/mihomo"
BASE_CONFIG_FILE="${CONFIG_DIR}/base.yaml"
GENERATED_CONFIG_FILE="${CONFIG_DIR}/generated.yaml"

if [ ! -f "${GENERATED_CONFIG_FILE}" ]; then
  cp "${BASE_CONFIG_FILE}" "${GENERATED_CONFIG_FILE}"
fi

exec /mihomo -d "${CONFIG_DIR}" -f "${GENERATED_CONFIG_FILE}"
