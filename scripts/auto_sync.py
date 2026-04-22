#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from email.message import Message
from email.utils import collapse_rfc2231_value
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
SUBSTORE_DATA_DIR = BASE_DIR / "sub-store-data"
SUBSTORE_RUNTIME_DATA_FILE = SUBSTORE_DATA_DIR / "sub-store.json"
SUBSTORE_LOCAL_DATA_FILE = SUBSTORE_DATA_DIR / "sub-store.local.json"
SUBSTORE_ROOT_DATA_FILE = SUBSTORE_DATA_DIR / "root.local.json"
SUBSTORE_ROOT_FALLBACK_FILE = SUBSTORE_DATA_DIR / "root.json"
SUBSTORE_FLOW_CACHE_FILE = SUBSTORE_DATA_DIR / "flow-cache.local.json"
STACK_ENV_FILE = CONFIG_DIR / "stack.env"
STACK_LOCAL_ENV_FILE = CONFIG_DIR / "stack.local.env"
BASE_CONFIG_FILE = CONFIG_DIR / "base.yaml"
GENERATED_CONFIG_FILE = CONFIG_DIR / "generated.yaml"
GEOIP_FILE = CONFIG_DIR / "geoip.metadb"
MMDB_FILE = CONFIG_DIR / "Country.mmdb"
GEOSITE_FILE = CONFIG_DIR / "GeoSite.dat"
GEOIP_URL = "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb"
MMDB_URL = "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/country.mmdb"
GEOSITE_URL = "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geosite.dat"
MIHOMO_CONFIG_PATH = "/root/.config/mihomo/generated.yaml"
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
DEFAULT_SUBSTORE_PROCESS = [
    {
        "type": "Quick Setting Operator",
        "args": {
            "useless": "DISABLED",
            "udp": "DEFAULT",
            "scert": "DEFAULT",
            "tfo": "DEFAULT",
            "vmess aead": "DEFAULT",
        },
    }
]
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")

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


def get_writable_env_file() -> Path:
    return STACK_LOCAL_ENV_FILE if STACK_LOCAL_ENV_FILE.exists() else STACK_ENV_FILE


def load_stack_env() -> dict[str, str]:
    env = load_env_file(STACK_ENV_FILE)
    env.update(load_env_file(STACK_LOCAL_ENV_FILE))
    return env


def save_stack_env(values: dict[str, str]) -> None:
    save_env_file(get_writable_env_file(), values)


def ensure_generated_config_exists() -> None:
    if GENERATED_CONFIG_FILE.exists() or not BASE_CONFIG_FILE.exists():
        return
    GENERATED_CONFIG_FILE.write_bytes(BASE_CONFIG_FILE.read_bytes())


def load_substore_data() -> dict:
    source_file = SUBSTORE_RUNTIME_DATA_FILE if SUBSTORE_RUNTIME_DATA_FILE.exists() else SUBSTORE_LOCAL_DATA_FILE
    if not source_file.exists():
        return {
            "subs": [],
            "collections": [],
            "artifacts": [],
            "rules": [],
            "files": [],
            "tokens": [],
            "schemaVersion": "2.0",
            "settings": {},
            "archives": [],
            "modules": [],
        }
    return json.loads(source_file.read_text(encoding="utf-8"))


def save_substore_data(payload: dict) -> None:
    SUBSTORE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SUBSTORE_RUNTIME_DATA_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_flow_cache() -> dict[str, dict]:
    data = load_json_file(SUBSTORE_FLOW_CACHE_FILE)
    return data if isinstance(data, dict) else {}


def save_flow_cache(cache: dict[str, dict]) -> None:
    SUBSTORE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SUBSTORE_FLOW_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def cache_flow_result(name: str, payload: dict) -> None:
    cache = load_flow_cache()
    cache[name] = {
        "cached_at": int(time.time()),
        "data": payload,
    }
    save_flow_cache(cache)


def get_cached_flow_result(name: str) -> dict | None:
    cached = load_flow_cache().get(name)
    if not isinstance(cached, dict):
        return None
    data = cached.get("data")
    return data if isinstance(data, dict) else None


def get_cached_flow_overview() -> dict[str, dict]:
    payload: dict[str, dict] = {}
    for name, item in load_flow_cache().items():
        if not isinstance(item, dict):
            continue
        data = item.get("data")
        if isinstance(data, dict):
            cached_entry = dict(data)
            cached_at = item.get("cached_at")
            if isinstance(cached_at, int):
                cached_entry["cached_at"] = cached_at
            payload[name] = cached_entry
    return payload


def derive_source_display_name(source_url: str) -> str:
    host = urllib.parse.urlparse(source_url).hostname or "订阅链接"
    host = host.removeprefix("www.")
    return host


def inspect_subscription_display_name(source_url: str) -> str | None:
    request = urllib.request.Request(source_url, headers={"User-Agent": "clash.meta"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content_disposition = response.headers.get("content-disposition", "")
            if content_disposition:
                message = Message()
                message["content-disposition"] = content_disposition
                filename = message.get_param("filename*", header="content-disposition")
                if filename is None:
                    filename = message.get_param("filename", header="content-disposition")
                if isinstance(filename, tuple):
                    filename = collapse_rfc2231_value(filename)
                if filename:
                    if filename.lower().startswith("utf-8''"):
                        filename = urllib.parse.unquote(filename[7:])
                    filename = urllib.parse.unquote(filename).strip()
                    if filename:
                        return filename

            profile_title = response.headers.get("profile-title", "").strip()
            if profile_title:
                return urllib.parse.unquote(profile_title)
    except Exception:
        return None
    return None


def derive_source_name(source_url: str) -> str:
    parsed = urllib.parse.urlparse(source_url)
    host = (parsed.hostname or "auto-subscription").removeprefix("www.")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", host).strip("-")
    return safe or "auto-subscription"


def list_substore_subs(base_url: str) -> list[dict]:
    payload = json.loads(http_request(f"{base_url}/api/subs").decode("utf-8"))
    return payload.get("data") or []


def build_remote_source(name: str, source_url: str) -> dict[str, object]:
    display_name = inspect_subscription_display_name(source_url) or derive_source_display_name(source_url)
    return {
        "name": name,
        "displayName": display_name,
        "form": "",
        "remark": "",
        "mergeSources": "",
        "ignoreFailedRemoteSub": False,
        "passThroughUA": False,
        "icon": "",
        "isIconColor": True,
        "process": DEFAULT_SUBSTORE_PROCESS,
        "source": "remote",
        "url": source_url,
        "content": "",
        "ua": "",
        "tag": [],
        "subscriptionTags": [],
        "display-name": display_name,
    }


def is_substore_resource_not_found(exc: urllib.error.HTTPError) -> bool:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        return False
    error = payload.get("error")
    return isinstance(error, dict) and error.get("code") == "RESOURCE_NOT_FOUND"


def recreate_substore_source(base_url: str, source: dict[str, object]) -> None:
    name = (source.get("name") or "").strip()
    if not name:
        raise ValueError("来源名称不能为空")
    encoded_name = urllib.parse.quote(name, safe="")
    try:
        http_request(f"{base_url}/api/sub/{encoded_name}", method="DELETE", timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code != 404 and not is_substore_resource_not_found(exc):
            raise
    http_request(
        f"{base_url}/api/subs",
        method="POST",
        data=json.dumps(source, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        timeout=30,
    )


def get_substore_items(kind: str) -> list[dict]:
    payload = load_substore_data()
    key = "collections" if kind == "collection" else "subs"
    items = payload.get(key)
    return items if isinstance(items, list) else []


def delete_substore_source(kind: str, name: str) -> dict[str, str]:
    base_url = load_stack_env().get("SUBSTORE_BASE_URL", DEFAULT_SUBSTORE_BASE_URL).rstrip("/")
    encoded_name = urllib.parse.quote(name, safe="")
    endpoint = f"{base_url}/api/collection/{encoded_name}" if kind == "collection" else f"{base_url}/api/sub/{encoded_name}"
    try:
        http_request(endpoint, method="DELETE", timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError("要删除的配置不存在") from exc
        raise

    env = load_stack_env()
    active_kind = (env.get("SUBSTORE_SOURCE_KIND") or "sub").strip() or "sub"
    active_name = (env.get("SUBSTORE_SOURCE_NAME") or "").strip()
    if active_kind == kind and active_name == name:
        save_stack_env(
            {
                "SUBSTORE_SOURCE_KIND": "",
                "SUBSTORE_SOURCE_NAME": "",
            }
        )

    return {
        "kind": kind,
        "name": name,
        "active_cleared": "true" if active_kind == kind and active_name == name else "false",
    }


def choose_source_name(source_url: str, existing_names: set[str]) -> str:
    base_name = derive_source_name(source_url)
    if base_name not in existing_names:
        return base_name
    for index in range(2, 1000):
        candidate = f"{base_name}-{index}"
        if candidate not in existing_names:
            return candidate
    raise ValueError("自动生成来源名称失败")


def find_substore_sub(name: str) -> dict | None:
    name = name.strip()
    if not name:
        return None
    sources: list[dict] = []
    for path in (SUBSTORE_RUNTIME_DATA_FILE, SUBSTORE_LOCAL_DATA_FILE):
        payload = load_json_file(path)
        subs = payload.get("subs")
        if isinstance(subs, list):
            sources.extend(item for item in subs if isinstance(item, dict))
    for item in sources:
        if (item.get("name") or "").strip() == name:
            return item
    return None


def find_substore_sub_by_url(source_url: str) -> dict | None:
    target_url = source_url.strip()
    if not target_url:
        return None
    sources: list[dict] = []
    for path in (SUBSTORE_RUNTIME_DATA_FILE, SUBSTORE_LOCAL_DATA_FILE):
        payload = load_json_file(path)
        subs = payload.get("subs")
        if isinstance(subs, list):
            sources.extend(item for item in subs if isinstance(item, dict))
    for item in sources:
        if (item.get("url") or "").strip() == target_url:
            return item
    return None


def parse_flow_header_value(raw_value: str) -> dict | None:
    if not raw_value.strip():
        return None
    parsed: dict[str, int] = {}
    for chunk in raw_value.split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            continue
        try:
            parsed[key] = int(value)
        except ValueError:
            continue
    total = parsed.get("total")
    upload = parsed.get("upload")
    download = parsed.get("download")
    if total is None or upload is None or download is None:
        return None
    payload = {
        "total": total,
        "usage": {
            "upload": upload,
            "download": download,
        },
    }
    expire = parsed.get("expire")
    if expire is not None:
        payload["expires"] = expire
    return payload


def parse_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None
    return None


def normalize_flow_signature(payload: dict | None) -> tuple[int, int, int] | None:
    if not isinstance(payload, dict):
        return None
    total = parse_int(payload.get("total"))
    usage = payload.get("usage")
    upload = parse_int((usage or {}).get("upload")) if isinstance(usage, dict) else None
    download = parse_int((usage or {}).get("download")) if isinstance(usage, dict) else None
    if total is None or upload is None or download is None:
        return None
    return total, upload, download


def iter_root_resource_caches() -> list[dict]:
    items: list[dict] = []
    for path in (SUBSTORE_ROOT_DATA_FILE, SUBSTORE_ROOT_FALLBACK_FILE):
        payload = load_json_file(path)
        raw = payload.get("sub-store-cached-resource")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            caches = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(caches, dict):
            continue
        for cache_key, item in caches.items():
            if not isinstance(item, dict):
                continue
            data = item.get("data")
            if not isinstance(data, str) or not data.strip():
                continue
            items.append(
                {
                    "key": cache_key,
                    "time": int(item.get("time") or 0),
                    "data": data,
                }
            )
    return items


def iter_root_header_caches() -> list[dict]:
    items: list[dict] = []
    for path in (SUBSTORE_ROOT_DATA_FILE, SUBSTORE_ROOT_FALLBACK_FILE):
        payload = load_json_file(path)
        raw = payload.get("sub-store-cached-headers-resource")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            caches = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(caches, dict):
            continue
        for cache_key, item in caches.items():
            if not isinstance(item, dict):
                continue
            flow_data = parse_flow_header_value(str(item.get("data") or ""))
            if not flow_data:
                continue
            items.append(
                {
                    "key": cache_key,
                    "time": int(item.get("time") or 0),
                    "raw": str(item.get("data") or ""),
                    "data": flow_data,
                }
            )
    return items


def get_latest_root_cached_flow() -> dict | None:
    entries = iter_root_header_caches()
    if not entries:
        return None
    latest = max(entries, key=lambda item: item["time"])
    return latest["data"]


def get_cached_or_local_flow(name: str) -> dict | None:
    cached = get_cached_flow_result(name)
    if cached:
        return cached

    return None


def extract_search_tokens(*values: str) -> set[str]:
    ignored = {
        "api",
        "authorize",
        "clash",
        "clashmeta",
        "com",
        "download",
        "http",
        "https",
        "meta",
        "substore",
        "token",
        "www",
    }
    tokens: set[str] = set()
    for value in values:
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", value.lower()):
            if token in ignored or token.isdigit():
                continue
            if re.search(r"[\u4e00-\u9fff]", token):
                if len(token) >= 2:
                    tokens.add(token)
                continue
            if len(token) >= 4:
                tokens.add(token)
    return tokens


def find_cached_subscription_resource(name: str) -> bytes | None:
    source = find_substore_sub(name) or {}
    flow = refresh_live_flow(name) or get_cached_flow_result(name)
    flow_signature = normalize_flow_signature(flow)
    if flow_signature is None:
        return None

    header_entries = {item["key"]: item for item in iter_root_header_caches()}
    markers = extract_search_tokens(
        name,
        str(source.get("displayName") or ""),
        str(source.get("display-name") or ""),
        str(source.get("url") or ""),
    )

    matched_by_signature: list[dict] = []
    matched_by_marker: list[dict] = []
    for resource in iter_root_resource_caches():
        resource_text = resource["data"].lower()
        marker_score = sum(len(token) for token in markers if token in resource_text)
        marker_matched = marker_score > 0
        if marker_matched:
            matched_by_marker.append({**resource, "marker_score": marker_score})
        header = header_entries.get(resource["key"])
        if not header:
            continue
        if normalize_flow_signature(header.get("data")) != flow_signature:
            continue
        matched_by_signature.append({**resource, "marker_score": marker_score})

    if matched_by_signature:
        prioritized = [item for item in matched_by_signature if item in matched_by_marker]
        best = max(prioritized or matched_by_signature, key=lambda item: (item["marker_score"], item["time"]))
        return best["data"].encode("utf-8")

    if not matched_by_marker:
        return None

    best = max(matched_by_marker, key=lambda item: (item["marker_score"], item["time"]))
    return best["data"].encode("utf-8")


def refresh_live_flow(name: str) -> dict | None:
    encoded_name = urllib.parse.quote(name, safe="")
    try:
        response = json.loads(http_request(f"http://127.0.0.1:3002/api/sub/flow/{encoded_name}", timeout=15).decode("utf-8"))
        data = response.get("data")
        if response.get("status") == "success" and isinstance(data, dict):
            cache_flow_result(name, data)
            return data
    except Exception:
        pass
    return None


def fetch_live_or_cached_flow(name: str) -> dict:
    live = refresh_live_flow(name)
    if live:
        return {"status": "success", "data": live}

    cached = get_cached_or_local_flow(name)
    if cached:
        return {"status": "success", "data": cached}

    return {
        "status": "failed",
        "error": {
            "code": "NO_FLOW_INFO",
            "type": "InternalServerError",
            "message": "No flow info",
            "details": "No cached flow info available",
        },
    }


def ensure_auto_remote_source(source_url: str, env: dict[str, str]) -> dict[str, str]:
    base_url = env.get("SUBSTORE_BASE_URL", DEFAULT_SUBSTORE_BASE_URL).rstrip("/")
    resolved_display_name = inspect_subscription_display_name(source_url) or derive_source_display_name(source_url)
    for item in list_substore_subs(base_url):
        if (item.get("url") or "").strip() == source_url:
            source_name = (item.get("name") or "").strip()
            current_display_name = (
                item.get("displayName") or item.get("display-name") or derive_source_display_name(source_url)
            ).strip()
            if current_display_name != resolved_display_name:
                recreate_substore_source(base_url, build_remote_source(source_name, source_url))
                current_display_name = resolved_display_name
            return {"name": source_name, "displayName": current_display_name}

    existing_names = {(item.get("name") or "").strip() for item in list_substore_subs(base_url) if (item.get("name") or "").strip()}
    source_name = choose_source_name(source_url, existing_names)
    source = build_remote_source(source_name, source_url)
    recreate_substore_source(base_url, source)
    return {
        "name": source_name,
        "displayName": (source.get("displayName") or "").strip(),
        "created": "true",
    }


def verify_substore_source(kind: str, name: str, env: dict[str, str]) -> str:
    base_url = env.get("SUBSTORE_BASE_URL", DEFAULT_SUBSTORE_BASE_URL).rstrip("/")
    encoded_name = urllib.parse.quote(name, safe="")
    if kind == "collection":
        source_url = f"{base_url}/download/collection/{encoded_name}?target=ClashMeta"
    else:
        source_url = f"{base_url}/download/{encoded_name}?target=ClashMeta"
    last_error: Exception | None = None
    for _ in range(5):
        try:
            http_request(source_url, timeout=30)
            return source_url
        except Exception as exc:
            last_error = exc
            time.sleep(0.6)
    if last_error is not None:
        raise last_error
    return source_url


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


def build_subscription_request_headers() -> dict[str, str]:
    return {"User-Agent": "clash.meta"}


def fetch_subscription_payload(
    url: str,
    *,
    timeout: int = 60,
    substore_name: str | None = None,
) -> tuple[bytes, dict[str, str], dict[str, object]]:
    request = urllib.request.Request(url, headers=build_subscription_request_headers(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), {key.lower(): value for key, value in response.headers.items()}, {"used_cached": False}
    except Exception:
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-L",
                    "--fail",
                    "--max-time",
                    str(timeout),
                    "--silent",
                    "--show-error",
                    "-A",
                    "clash.meta",
                    url,
                ],
                check=True,
                capture_output=True,
            )
            return result.stdout, {}, {"used_cached": False}
        except Exception:
            cached_payload = find_cached_subscription_resource(substore_name or "")
            if cached_payload is None:
                raise
            log(f"订阅 {substore_name} 回源失败，已回退到本地缓存配置")
            return cached_payload, {}, {"used_cached": True, "substore_name": substore_name or ""}


def fetch_subscription_content(url: str, *, timeout: int = 60) -> bytes:
    body, _, _ = fetch_subscription_payload(url, timeout=timeout)
    return body


def extract_subscription_flow(headers: dict[str, str]) -> dict | None:
    return parse_flow_header_value(str(headers.get("subscription-userinfo") or ""))


def fetch_geoip_via_proxy(provider: str) -> dict:
    if provider not in GEOIP_PROVIDER_URLS:
        raise ValueError(f"不支持的 provider: {provider}")
    env = load_stack_env()
    body = http_request(
        GEOIP_PROVIDER_URLS[provider],
        proxy_url=build_mihomo_proxy_url(env),
        timeout=15,
    )
    return json.loads(body.decode("utf-8"))


def probe_latency_via_proxy(target_url: str) -> dict[str, int | str | bool]:
    env = load_stack_env()
    proxy_url = build_mihomo_proxy_url(env)
    start = time.perf_counter()

    def is_reachable_http_error(exc: urllib.error.HTTPError) -> bool:
        return 200 <= exc.code < 500

    try:
        http_request(
            target_url,
            method="HEAD",
            proxy_url=proxy_url,
            timeout=15,
            headers={"Cache-Control": "no-store"},
        )
    except urllib.error.HTTPError as exc:
        if not is_reachable_http_error(exc):
            raise
    except Exception:
        try:
            http_request(
                target_url,
                method="GET",
                proxy_url=proxy_url,
                timeout=15,
                headers={"Cache-Control": "no-store"},
            )
        except urllib.error.HTTPError as exc:
            if not is_reachable_http_error(exc):
                raise
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


def describe_source_transport(env: dict[str, str]) -> str:
    source_name = env.get("SUBSTORE_SOURCE_NAME", "").strip()
    if not source_name:
        return "原始远程订阅直连"
    source_kind = env.get("SUBSTORE_SOURCE_KIND", "sub").strip() or "sub"
    if source_kind == "collection":
        return "通过 Sub-Store 组合启用"
    return "通过 Sub-Store 单条启用"


def describe_parse_format(env: dict[str, str]) -> str:
    source_name = env.get("SUBSTORE_SOURCE_NAME", "").strip()
    if not source_name:
        return "Clash / Mihomo"
    return "ClashMeta（Clash）"


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
    default_mode = env.get("MIHOMO_DEFAULT_MODE", "global").strip() or "global"

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
    if not re.search(r"^mode:\s*.*$", text, flags=re.MULTILINE):
        text = replace_or_append_line(
            text,
            r"^mode:\s*.*$",
            f"mode: {default_mode}",
            anchor=f"bind-address: '{bind_address}'",
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
        env = load_stack_env()
        source_url = resolve_source_url(env)
        secret = env.get("CONTROLLER_SECRET", "123456").strip() or "123456"
        set_state(last_status="running", last_error=None, last_source_url=source_url)

        subscription_body, subscription_headers, subscription_meta = fetch_subscription_payload(
            source_url,
            substore_name=(env.get("SUBSTORE_SOURCE_NAME") or "").strip() or None,
        )
        raw_config = subscription_body.decode("utf-8")
        patched_config = patch_config(raw_config, env).encode("utf-8")

        ensure_generated_config_exists()
        config_changed = write_if_changed(GENERATED_CONFIG_FILE, patched_config)
        geoip_changed = write_if_changed(GEOIP_FILE, http_request(GEOIP_URL))
        mmdb_changed = write_if_changed(MMDB_FILE, http_request(MMDB_URL))
        geosite_changed = write_if_changed(GEOSITE_FILE, http_request(GEOSITE_URL))

        used_cached_subscription = bool(subscription_meta.get("used_cached"))
        if any((config_changed, geoip_changed, mmdb_changed, geosite_changed)):
            reload_mihomo(secret)
            message = "配置已更新并通知 mihomo 热重载"
        else:
            message = "配置未变化，跳过重载"
        if used_cached_subscription:
            message = f"源站不可用，已使用本地缓存配置；{message}"

        active_name = (env.get("SUBSTORE_SOURCE_NAME") or "").strip()
        if active_name:
            refresh_live_flow(active_name)
        else:
            mirror_source = find_substore_sub_by_url(source_url)
            direct_flow = extract_subscription_flow(subscription_headers)
            mirror_name = ((mirror_source or {}).get("name") or "").strip()
            if mirror_name and direct_flow:
                cache_flow_result(mirror_name, direct_flow)

        timestamp = datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
        set_state(last_sync_at=timestamp, last_status="ok", last_error=None, last_source_url=source_url)
        log(message)
        return {
            "message": message,
            "last_sync_at": timestamp,
            "source_url": source_url,
            "used_cached_subscription": used_cached_subscription,
        }


def fetch_substore_sources() -> dict[str, list[dict[str, str]]]:
    env = load_stack_env()
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
                    "url": (item.get("url") or "").strip(),
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
    env = load_stack_env()
    if mode == "remote":
        candidate_env = dict(env)
        candidate_env.update(
            {
                "SUBSTORE_SOURCE_KIND": "",
                "SUBSTORE_SOURCE_NAME": "",
            }
        )
        candidate_url = resolve_source_url(candidate_env)
        try:
            fetch_subscription_content(candidate_url, timeout=30)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"直连订阅不可用，未启用：{exc}") from exc
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

    save_stack_env(updates)
    env = load_stack_env()
    return {
        "mode": "substore" if env.get("SUBSTORE_SOURCE_NAME", "").strip() else "remote",
        "kind": env.get("SUBSTORE_SOURCE_KIND", ""),
        "name": env.get("SUBSTORE_SOURCE_NAME", ""),
        "source_url": resolve_source_url(env),
    }


def update_source_url(payload: dict[str, str]) -> dict[str, str]:
    source_url = (payload.get("url") or "").strip()
    if not source_url:
        raise ValueError("订阅链接不能为空")

    env = load_stack_env()
    display_name = inspect_subscription_display_name(source_url) or derive_source_display_name(source_url)
    try:
        fetch_subscription_content(source_url, timeout=30)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"直连订阅不可用，当前配置保持不变：{exc}") from exc

    auto_source: dict[str, str] | None = None
    try:
        auto_source = ensure_auto_remote_source(source_url, env)
    except Exception as exc:  # noqa: BLE001
        log(f"创建 Sub-Store 镜像来源失败，已忽略：{exc}")

    save_stack_env(
        {
            "SUBSCRIPTION_URL": source_url,
            "SUBSTORE_SOURCE_KIND": "",
            "SUBSTORE_SOURCE_NAME": "",
        }
    )
    current_env = load_stack_env()
    return {
        "mode": "remote",
        "kind": "",
        "name": "",
        "display_name": (auto_source or {}).get("displayName") or display_name,
        "created": (auto_source or {}).get("created") == "true",
        "source_url": resolve_source_url(current_env),
    }


def remove_source(payload: dict[str, str]) -> dict[str, str]:
    kind = (payload.get("kind") or "sub").strip()
    name = (payload.get("name") or "").strip()
    if kind not in {"sub", "collection"}:
        raise ValueError("kind 只能是 sub 或 collection")
    if not name:
        raise ValueError("name 不能为空")
    return delete_substore_source(kind, name)


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
            env = load_stack_env()
            state = get_state()
            source_name = env.get("SUBSTORE_SOURCE_NAME", "").strip()
            response = {
                "status": "success",
                "data": {
                    "sync": state,
                    "config": {
                        "mode": "substore" if source_name else "remote",
                        "sourceKind": env.get("SUBSTORE_SOURCE_KIND", ""),
                        "sourceName": source_name,
                        "sourceUrl": resolve_source_url(env),
                        "sourceTransport": describe_source_transport(env),
                        "parseFormat": describe_parse_format(env),
                        "intervalSeconds": env.get("SYNC_INTERVAL_SECONDS", "300"),
                    },
                },
            }
            self._send_json(200, response)
            return

        if self.path == "/sources":
            self._send_json(200, {"status": "success", "data": fetch_substore_sources()})
            return

        if self.path == "/flow-cache":
            self._send_json(200, {"status": "success", "data": get_cached_flow_overview()})
            return

        if parsed.path.startswith("/substore-flow/"):
            try:
                name = urllib.parse.unquote(parsed.path.removeprefix("/substore-flow/")).strip()
                if not name:
                    raise ValueError("name 不能为空")
                self._send_json(200, fetch_live_or_cached_flow(name))
            except ValueError as exc:
                self._send_json(400, {"status": "error", "message": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"status": "error", "message": str(exc)})
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

            if self.path == "/source-url":
                payload = self._read_json()
                result = update_source_url(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            if self.path == "/source-delete":
                payload = self._read_json()
                result = remove_source(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            self._send_json(404, {"status": "error", "message": "Not Found"})
        except ValueError as exc:
            set_state(last_status="error", last_error=str(exc))
            self._send_json(400, {"status": "error", "message": str(exc)})
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

        env = load_stack_env()
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
