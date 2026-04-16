#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
STACK_ENV_FILE = CONFIG_DIR / "stack.env"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
GEOIP_FILE = CONFIG_DIR / "geoip.metadb"
MMDB_FILE = CONFIG_DIR / "Country.mmdb"
GEOIP_URL = "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb"
MMDB_URL = "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/country.mmdb"
MIHOMO_CONFIG_PATH = "/root/.config/mihomo/config.yaml"
SYNC_API_PORT = 3010
DEFAULT_SUBSTORE_BASE_URL = "http://127.0.0.1:3001/substore"
DEFAULT_MIHOMO_PROXY_HOST = "127.0.0.1"
DEFAULT_MIHOMO_PROXY_PORT = "7890"
GEOIP_PROVIDER_URLS = {
    "ip.sb": "https://api.ip.sb/geoip",
    "ipwho.is": "https://ipwho.is/",
    "ipapi.is": "https://api.ipapi.is/",
}
LATENCY_PROBE_URLS = {
    "google": "https://www.google.com/generate_204",
    "cloudflare": "https://www.cloudflare.com/cdn-cgi/trace",
    "github": "https://github.com/",
}

STATE: dict[str, str | bool | None] = {
    "last_sync_at": None,
    "last_status": "idle",
    "last_error": None,
    "last_source_url": None,
}
STATE_LOCK = threading.Lock()
SYNC_LOCK = threading.Lock()


def log(message: str) -> None:
    print(f"[auto-sync] {message}", flush=True)


def set_state(**kwargs: str | bool | None) -> None:
    with STATE_LOCK:
        STATE.update(kwargs)


def get_state() -> dict[str, str | bool | None]:
    with STATE_LOCK:
        return dict(STATE)


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def save_env_file(path: Path, values: dict[str, str]) -> None:
    existing = load_env_file(path)
    merged = dict(existing)
    merged.update(values)
    lines = [f'{key}="{merged[key]}"' for key in sorted(merged.keys())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def http_request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    proxy_url: str | None = None,
) -> bytes:
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    opener = urllib.request.build_opener()
    if proxy_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(
                {
                    "http": proxy_url,
                    "https": proxy_url,
                }
            )
        )
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def build_mihomo_proxy_url(env: dict[str, str]) -> str:
    host = env.get("MIHOMO_PROXY_HOST", DEFAULT_MIHOMO_PROXY_HOST).strip() or DEFAULT_MIHOMO_PROXY_HOST
    port = env.get("MIHOMO_MIXED_PORT", DEFAULT_MIHOMO_PROXY_PORT).strip() or DEFAULT_MIHOMO_PROXY_PORT
    return f"http://{host}:{port}"


def fetch_geoip_via_proxy(provider: str) -> dict:
    if provider not in GEOIP_PROVIDER_URLS:
        raise ValueError(f"不支持的 provider: {provider}")
    env = load_env_file(STACK_ENV_FILE)
    body = http_request(
        GEOIP_PROVIDER_URLS[provider],
        proxy_url=build_mihomo_proxy_url(env),
        timeout=15,
    )
    return json.loads(body.decode("utf-8"))


def probe_latency_via_proxy(target_url: str) -> dict[str, int | str | bool]:
    env = load_env_file(STACK_ENV_FILE)
    proxy_url = build_mihomo_proxy_url(env)
    start = time.perf_counter()
    try:
        http_request(
            target_url,
            method="HEAD",
            proxy_url=proxy_url,
            timeout=15,
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        http_request(
            target_url,
            method="GET",
            proxy_url=proxy_url,
            timeout=15,
            headers={"Cache-Control": "no-store"},
        )
    delay = int((time.perf_counter() - start) * 1000)
    return {"url": target_url, "delay": delay, "ok": True}


def resolve_source_url(env: dict[str, str]) -> str:
    substore_name = env.get("SUBSTORE_SOURCE_NAME", "").strip()
    if substore_name:
        kind = env.get("SUBSTORE_SOURCE_KIND", "sub").strip() or "sub"
        if kind not in {"sub", "collection"}:
            raise ValueError(f"不支持的 SUBSTORE_SOURCE_KIND: {kind}")
        base_url = env.get("SUBSTORE_BASE_URL", DEFAULT_SUBSTORE_BASE_URL).rstrip("/")
        encoded_name = urllib.parse.quote(substore_name, safe="")
        if kind == "collection":
            return f"{base_url}/download/collection/{encoded_name}?target=ClashMeta"
        return f"{base_url}/download/{encoded_name}?target=ClashMeta"

    source_url = env.get("SUBSCRIPTION_URL", "").strip()
    if not source_url:
        raise ValueError("SUBSCRIPTION_URL 未配置")
    return source_url


def replace_or_append_line(text: str, pattern: str, replacement: str, *, anchor: str | None = None) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count:
        return updated
    if anchor and anchor in updated:
        return updated.replace(anchor, f"{anchor}\n{replacement}", 1)
    return f"{updated.rstrip()}\n{replacement}\n"


def patch_config(raw_text: str, env: dict[str, str]) -> str:
    controller_addr = env.get("CONTROLLER_ADDR", "0.0.0.0:19090").strip() or "0.0.0.0:19090"
    controller_secret = env.get("CONTROLLER_SECRET", "123456").strip() or "123456"
    mixed_port = env.get("MIHOMO_MIXED_PORT", "7890").strip() or "7890"
    allow_lan = env.get("MIHOMO_ALLOW_LAN", "true").strip().lower()
    bind_address = env.get("MIHOMO_BIND_ADDRESS", "*").strip() or "*"

    text = raw_text.replace("\r\n", "\n")
    text = replace_or_append_line(
        text,
        r"^external-controller:\s*.*$",
        f"external-controller: '{controller_addr}'",
        anchor="log-level: silent",
    )
    text = replace_or_append_line(
        text,
        r"^secret:\s*.*$",
        f"secret: '{controller_secret}'",
        anchor=f"external-controller: '{controller_addr}'",
    )
    text = replace_or_append_line(
        text,
        r"^external-ui:\s*.*$",
        "external-ui: 'ui'",
        anchor=f"secret: '{controller_secret}'",
    )
    text = replace_or_append_line(
        text,
        r"^mixed-port:\s*.*$",
        f"mixed-port: {mixed_port}",
        anchor="external-ui: 'ui'",
    )
    text = replace_or_append_line(
        text,
        r"^allow-lan:\s*.*$",
        f"allow-lan: {'true' if allow_lan == 'true' else 'false'}",
        anchor=f"mixed-port: {mixed_port}",
    )
    text = replace_or_append_line(
        text,
        r"^bind-address:\s*.*$",
        f"bind-address: '{bind_address}'",
        anchor=f"allow-lan: {'true' if allow_lan == 'true' else 'false'}",
    )

    geox_block = (
        "geox-url:\n"
        "  geoip: 'https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb'\n"
        "  mmdb: 'https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/country.mmdb'"
    )
    text, count = re.subn(
        r"^geox-url:\n(?:[ \t].*\n?)*",
        f"{geox_block}\n",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count == 0:
        text = text.replace("external-ui: 'ui'", f"external-ui: 'ui'\n{geox_block}", 1)

    if not text.endswith("\n"):
        text += "\n"
    return text


def write_if_changed(path: Path, content: bytes) -> bool:
    if path.exists() and path.read_bytes() == content:
        return False
    path.write_bytes(content)
    return True


def reload_mihomo(secret: str) -> None:
    payload = json.dumps({"path": MIHOMO_CONFIG_PATH}).encode("utf-8")
    http_request(
        "http://127.0.0.1:19090/configs?force=true",
        method="PUT",
        data=payload,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        },
    )


def sync_once() -> dict[str, str]:
    with SYNC_LOCK:
        env = load_env_file(STACK_ENV_FILE)
        source_url = resolve_source_url(env)
        secret = env.get("CONTROLLER_SECRET", "123456").strip() or "123456"
        set_state(last_status="running", last_error=None, last_source_url=source_url)

        raw_config = http_request(source_url).decode("utf-8")
        patched_config = patch_config(raw_config, env).encode("utf-8")

        config_changed = write_if_changed(CONFIG_FILE, patched_config)
        geoip_changed = write_if_changed(GEOIP_FILE, http_request(GEOIP_URL))
        mmdb_changed = write_if_changed(MMDB_FILE, http_request(MMDB_URL))

        if any((config_changed, geoip_changed, mmdb_changed)):
            reload_mihomo(secret)
            message = "配置已更新并通知 mihomo 热重载"
        else:
            message = "配置未变化，跳过重载"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        set_state(last_sync_at=timestamp, last_status="ok", last_error=None, last_source_url=source_url)
        log(message)
        return {
            "message": message,
            "last_sync_at": timestamp,
            "source_url": source_url,
        }


def fetch_substore_sources() -> dict[str, list[dict[str, str]]]:
    env = load_env_file(STACK_ENV_FILE)
    base_url = env.get("SUBSTORE_BASE_URL", DEFAULT_SUBSTORE_BASE_URL).rstrip("/")

    def load_list(endpoint: str, kind: str) -> list[dict[str, str]]:
        payload = json.loads(http_request(f"{base_url}/api/{endpoint}").decode("utf-8"))
        items = payload.get("data") or []
        result: list[dict[str, str]] = []
        for item in items:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            result.append(
                {
                    "kind": kind,
                    "name": name,
                    "displayName": (item.get("displayName") or item.get("display-name") or "").strip(),
                }
            )
        return result

    return {
        "subs": load_list("subs", "sub"),
        "collections": load_list("collections", "collection"),
    }


def update_source(payload: dict[str, str]) -> dict[str, str]:
    mode = (payload.get("mode") or "substore").strip()
    updates: dict[str, str]
    if mode == "remote":
        updates = {
            "SUBSTORE_SOURCE_KIND": "",
            "SUBSTORE_SOURCE_NAME": "",
        }
    else:
        kind = (payload.get("kind") or "sub").strip()
        name = (payload.get("name") or "").strip()
        if kind not in {"sub", "collection"}:
            raise ValueError("kind 只能是 sub 或 collection")
        if not name:
            raise ValueError("name 不能为空")
        updates = {
            "SUBSTORE_SOURCE_KIND": kind,
            "SUBSTORE_SOURCE_NAME": name,
        }

    save_env_file(STACK_ENV_FILE, updates)
    env = load_env_file(STACK_ENV_FILE)
    return {
        "mode": "substore" if env.get("SUBSTORE_SOURCE_NAME", "").strip() else "remote",
        "kind": env.get("SUBSTORE_SOURCE_KIND", ""),
        "name": env.get("SUBSTORE_SOURCE_NAME", ""),
        "source_url": resolve_source_url(env),
    }


class SyncHandler(BaseHTTPRequestHandler):
    server_version = "MihomoSync/1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if self.path == "/status":
            env = load_env_file(STACK_ENV_FILE)
            state = get_state()
            response = {
                "status": "success",
                "data": {
                    "sync": state,
                    "config": {
                        "mode": "substore" if env.get("SUBSTORE_SOURCE_NAME", "").strip() else "remote",
                        "sourceKind": env.get("SUBSTORE_SOURCE_KIND", ""),
                        "sourceName": env.get("SUBSTORE_SOURCE_NAME", ""),
                        "sourceUrl": resolve_source_url(env),
                        "intervalSeconds": env.get("SYNC_INTERVAL_SECONDS", "300"),
                    },
                },
            }
            self._send_json(200, response)
            return

        if self.path == "/sources":
            self._send_json(200, {"status": "success", "data": fetch_substore_sources()})
            return

        if parsed.path == "/proxy-geoip":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                provider = (query.get("provider") or ["ipwho.is"])[0]
                payload = fetch_geoip_via_proxy(provider)
                self._send_json(200, {"status": "success", "provider": provider, "data": payload})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"status": "error", "message": str(exc)})
            return

        if parsed.path == "/proxy-latency":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                target_url = (query.get("url") or [""])[0].strip()
                if not target_url:
                    raise ValueError("url 不能为空")
                payload = probe_latency_via_proxy(target_url)
                self._send_json(200, {"status": "success", "data": payload})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"status": "error", "message": str(exc)})
            return

        self._send_json(404, {"status": "error", "message": "Not Found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/sync":
                result = sync_once()
                self._send_json(200, {"status": "success", "data": result})
                return

            if self.path == "/source":
                payload = self._read_json()
                result = update_source(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            self._send_json(404, {"status": "error", "message": "Not Found"})
        except Exception as exc:  # noqa: BLE001
            set_state(last_status="error", last_error=str(exc))
            self._send_json(500, {"status": "error", "message": str(exc)})

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def loop_sync() -> None:
    while True:
        try:
            sync_once()
        except Exception as exc:  # noqa: BLE001
            set_state(last_status="error", last_error=str(exc))
            log(f"同步失败: {exc}")

        env = load_env_file(STACK_ENV_FILE)
        try:
            interval = int(env.get("SYNC_INTERVAL_SECONDS", "300"))
        except ValueError:
            interval = 300
        time.sleep(max(interval, 30))


def main() -> int:
    thread = threading.Thread(target=loop_sync, daemon=True)
    thread.start()
    server = ThreadingHTTPServer(("0.0.0.0", SYNC_API_PORT), SyncHandler)
    log(f"控制接口已监听 {SYNC_API_PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
