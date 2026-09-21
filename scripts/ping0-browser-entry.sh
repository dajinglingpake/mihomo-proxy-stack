#!/bin/sh
# Ping0 浏览器检测服务启动脚本：
#   Xvfb   -> 提供虚拟桌面，让 Chromium 以有头模式运行（更容易通过真人环境校验）
#   x11vnc -> 只监听本机，供 websockify 转接
#   novnc  -> 浏览器里打开的远程桌面地址，人工在这里点掉验证码
set -eu

DISPLAY_NUM="${PING0_DISPLAY:-99}"
NOVNC_PORT="${PING0_NOVNC_PORT:-6080}"
WORKER_PORT="${PING0_WORKER_PORT:-3021}"
VNC_PORT=5900

export DISPLAY=":${DISPLAY_NUM}"
export HOME="${HOME:-/root}"

if ! ls -d /ms-playwright/chromium-* >/dev/null 2>&1; then
    echo "[ping0-browser] 警告：镜像里没有完整 Chromium（构建时下载失败），浏览器兜底会不可用，只能走直连/备用数据源"
    echo "[ping0-browser] 重新构建：docker compose build --no-cache ping0-browser"
fi

mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix 2>/dev/null || true
rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}"

Xvfb ":${DISPLAY_NUM}" -screen 0 1440x900x24 -nolisten tcp &
sleep 1

if [ -n "${PING0_VNC_PASSWORD:-}" ]; then
    x11vnc -display ":${DISPLAY_NUM}" -forever -shared -localhost \
        -rfbport "${VNC_PORT}" -passwd "${PING0_VNC_PASSWORD}" &
else
    echo "[ping0-browser] 未设置 PING0_VNC_PASSWORD，远程桌面无密码，请勿把 ${NOVNC_PORT} 端口暴露到公网"
    x11vnc -display ":${DISPLAY_NUM}" -forever -shared -localhost -nopw \
        -rfbport "${VNC_PORT}" &
fi

websockify --web=/usr/share/novnc "${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" &

exec python -u /app/scripts/ping0_browser.py --serve --port "${WORKER_PORT}"
