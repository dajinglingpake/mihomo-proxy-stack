#!/usr/bin/env python3

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime
from email.message import Message
from email.utils import collapse_rfc2231_value
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
SUBSTORE_DATA_DIR = BASE_DIR / "sub-store-data"
SUBSTORE_RUNTIME_DATA_FILE = SUBSTORE_DATA_DIR / "sub-store.json"
SUBSTORE_LOCAL_DATA_FILE = SUBSTORE_DATA_DIR / "sub-store.local.json"
SUBSTORE_ROOT_DATA_FILE = SUBSTORE_DATA_DIR / "root.local.json"
SUBSTORE_ROOT_FALLBACK_FILE = SUBSTORE_DATA_DIR / "root.json"
SUBSTORE_FLOW_CACHE_FILE = SUBSTORE_DATA_DIR / "flow-cache.local.json"
RENDERED_CONFIG_CACHE_DIR = SUBSTORE_DATA_DIR / "rendered-config-cache"
STACK_ENV_FILE = CONFIG_DIR / "stack.env"
STACK_LOCAL_ENV_FILE = CONFIG_DIR / "stack.local.env"
BASE_CONFIG_FILE = CONFIG_DIR / "base.yaml"
GENERATED_CONFIG_FILE = CONFIG_DIR / "generated.yaml"
GEOIP_FILE = CONFIG_DIR / "geoip.metadb"
MMDB_FILE = CONFIG_DIR / "Country.mmdb"
GEOSITE_FILE = CONFIG_DIR / "GeoSite.dat"
CUSTOM_PROXY_GROUPS_FILE = CONFIG_DIR / "proxy-group-overrides.local.json"
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
ACTIVE_UPDATE_STAGES = [
    ("prepare", "读取当前订阅"),
    ("subscription", "下载最新订阅"),
    ("render", "处理当前配置"),
    ("write-config", "更新运行配置"),
    ("geoip", "检查 GeoIP 数据"),
    ("mmdb", "检查 MMDB 数据"),
    ("geosite", "检查 GeoSite 数据"),
    ("cache", "保存当前快照"),
    ("reload", "应用到 Mihomo"),
    ("metadata", "更新当前状态"),
]
UPDATE_SNAPSHOT_STAGES = [
    ("prepare", "读取订阅信息"),
    ("subscription", "下载订阅"),
    ("render", "处理订阅配置"),
    ("write-config", "保存列表快照"),
    ("geoip", "保存链接快照"),
    ("mmdb", "更新流量信息"),
    ("geosite", "核对当前来源"),
    ("cache", "保留当前配置"),
    ("reload", "跳过配置应用"),
    ("metadata", "完成订阅更新"),
]

STATE: dict[str, object] = {
    "last_sync_at": None,
    "last_status": "idle",
    "last_error": None,
    "last_source_url": None,
    "sync_id": None,
    "sync_trigger": None,
    "operation_label": "同步订阅",
    "sync_started_at": None,
    "sync_elapsed_ms": None,
    "current_stage": None,
    "current_stage_label": None,
    "current_stage_detail": None,
    "current_stage_index": 0,
    "current_stage_total": 10,
    "current_stage_started_at": None,
    "current_stage_elapsed_ms": None,
    "stage_history": [],
    "stage_labels": [],
}
STATE_LOCK = threading.Lock()
SYNC_LOCK = threading.Lock()
SYNC_STAGE_TOTAL = 10
CUSTOM_GROUP_TYPES = {"select", "url-test", "fallback"}
CUSTOM_GROUP_BLOCK_START = "    # custom-proxy-group-overrides:start"
CUSTOM_GROUP_BLOCK_END = "    # custom-proxy-group-overrides:end"
RESERVED_PROXY_GROUP_NAMES = {"GLOBAL", "DIRECT", "REJECT", "REJECT-DROP", "PASS", "PASS-RULE"}


def redact_sensitive(value: object) -> str:
    return re.sub(
        r"(?i)([?&](?:token|key|secret|auth|password)=)[^&\s\"'；,，)\]}]+",
        r"\1<redacted>",
        str(value),
    )


def log(message: str) -> None:
    print(f"[auto-sync] {redact_sensitive(message)}", flush=True)


def get_sync_operation_label(trigger: str) -> str:
    return {
        "api-import": "下载并应用",
        "api-switch-local": "切换订阅",
        "api-update-active": "更新当前订阅",
        "scheduled": "自动同步",
    }.get(trigger, "同步订阅")


def get_sync_stage_label(trigger: str, index: int, default: str) -> str:
    if trigger == "api-update-active":
        return ACTIVE_UPDATE_STAGES[index - 1][1]
    return default


def set_state(**kwargs: object) -> None:
    with STATE_LOCK:
        STATE.update(kwargs)


def get_state() -> dict[str, object]:
    with STATE_LOCK:
        return dict(STATE)


def append_stage_history(
    *,
    code: str,
    label: str,
    index: int,
    status: str,
    elapsed_ms: int,
    detail: object,
) -> None:
    with STATE_LOCK:
        history = list(STATE.get("stage_history") or [])
        history.append(
            {
                "code": code,
                "label": label,
                "index": index,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "detail": detail,
            }
        )
        STATE["stage_history"] = history


@contextmanager
def sync_stage(sync_id: str, index: int, code: str, label: str):
    started = time.monotonic()
    metrics: dict[str, int] = {}
    set_state(
        current_stage=code,
        current_stage_label=label,
        current_stage_detail=None,
        current_stage_index=index,
        current_stage_total=SYNC_STAGE_TOTAL,
        current_stage_started_at=time.time(),
        current_stage_elapsed_ms=None,
    )
    log(f"同步 {sync_id} 阶段 {index}/{SYNC_STAGE_TOTAL} 开始: {label}")
    try:
        yield metrics
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        error = redact_sensitive(exc)
        set_state(current_stage_detail=error, current_stage_elapsed_ms=elapsed_ms)
        append_stage_history(
            code=code,
            label=label,
            index=index,
            status="error",
            elapsed_ms=elapsed_ms,
            detail=error,
        )
        log(f"同步 {sync_id} 阶段 {index}/{SYNC_STAGE_TOTAL} 失败: {label} elapsed_ms={elapsed_ms} error={error}")
        raise
    else:
        elapsed_ms = metrics.get("elapsed_ms", round((time.monotonic() - started) * 1000))
        metrics["elapsed_ms"] = elapsed_ms
        detail = get_state().get("current_stage_detail")
        set_state(current_stage_elapsed_ms=elapsed_ms)
        append_stage_history(
            code=code,
            label=label,
            index=index,
            status="done",
            elapsed_ms=elapsed_ms,
            detail=detail,
        )
        log(f"同步 {sync_id} 阶段 {index}/{SYNC_STAGE_TOTAL} 完成: {label} elapsed_ms={elapsed_ms}")


def set_sync_stage_detail(detail: str) -> None:
    set_state(current_stage_detail=detail)


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

def yaml_scalar(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)

def names_in_section(text: str, section: str) -> set[str]:
    match = re.search(rf"^{re.escape(section)}:\n((?:[ \t].*\n?)*)", text, flags=re.MULTILINE)
    section_text = match.group(1) if match else ""
    names: set[str] = set()
    for match in re.finditer(r"-\s*(?:\{\s*)?name:\s*(?:'([^']+)'|\"([^\"]+)\"|([^,\n}]+))", section_text):
        name = next((item for item in match.groups() if item), "").strip()
        if name:
            names.add(name)
    return names

def load_custom_proxy_groups() -> list[dict]:
    payload = load_json_file(CUSTOM_PROXY_GROUPS_FILE)
    groups = payload.get("groups") if isinstance(payload, dict) else []
    return groups if isinstance(groups, list) else []

def save_custom_proxy_groups(groups: list[dict]) -> None:
    CUSTOM_PROXY_GROUPS_FILE.write_text(
        json.dumps({"groups": groups}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

def strip_custom_proxy_group_block(text: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(CUSTOM_GROUP_BLOCK_START)}\n.*?^{re.escape(CUSTOM_GROUP_BLOCK_END)}\n?",
        flags=re.MULTILINE | re.DOTALL,
    )
    return pattern.sub("", text)

def native_proxy_group_names(text: str) -> set[str]:
    clean_text = strip_custom_proxy_group_block(text)
    return names_in_section(clean_text, "proxy-groups")

def custom_group_names_in_text(text: str) -> list[str]:
    names: list[str] = []
    block_match = re.search(
        rf"^{re.escape(CUSTOM_GROUP_BLOCK_START)}\n(.*?)^{re.escape(CUSTOM_GROUP_BLOCK_END)}",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not block_match:
        return names
    for match in re.finditer(r"-\s*\{\s*name:\s*(?:'([^']+)'|\"([^\"]+)\"|([^,\n}]+))", block_match.group(1)):
        name = next((item for item in match.groups() if item), "").strip()
        if name:
            names.append(name)
    return names

def validate_custom_proxy_group(payload: dict, *, existing_custom_names: set[str], native_names: set[str]) -> dict:
    name = str(payload.get("name") or "").strip()
    group_type = str(payload.get("type") or "fallback").strip()
    proxies = [str(item).strip() for item in payload.get("proxies") or [] if str(item).strip()]
    source_group = str(payload.get("sourceGroup") or "").strip()

    if not name:
        raise ValueError("策略组名称不能为空")
    if name in RESERVED_PROXY_GROUP_NAMES:
        raise ValueError(f"{name} 是保留名称")
    if name in native_names and name not in existing_custom_names:
        raise ValueError(f"{name} 已存在于订阅策略组，不能覆盖")
    if group_type not in CUSTOM_GROUP_TYPES:
        raise ValueError("策略组类型只能是 select、url-test 或 fallback")
    if not proxies:
        raise ValueError("至少选择一个节点")

    group = {
        "name": name,
        "type": group_type,
        "sourceGroup": source_group,
        "proxies": proxies,
    }
    if group_type in {"url-test", "fallback"}:
        group["url"] = str(payload.get("url") or "http://www.gstatic.com/generate_204").strip()
        try:
            group["interval"] = max(60, int(payload.get("interval") or 300))
        except (TypeError, ValueError):
            group["interval"] = 300
    return group

def custom_proxy_group_line(group: dict) -> str:
    parts = [
        f"name: {yaml_scalar(group['name'])}",
        f"type: {group['type']}",
        "proxies: [" + ", ".join(yaml_scalar(item) for item in group.get("proxies", [])) + "]",
    ]
    if group.get("type") in {"url-test", "fallback"}:
        parts.append(f"url: {yaml_scalar(group.get('url') or 'http://www.gstatic.com/generate_204')}")
        parts.append(f"interval: {int(group.get('interval') or 300)}")
    return "    - { " + ", ".join(parts) + " }"

def valid_custom_proxy_groups_for_text(text: str, groups: list[dict]) -> list[dict]:
    clean_text = strip_custom_proxy_group_block(text)
    available = names_in_section(clean_text, "proxies") | native_proxy_group_names(clean_text) | RESERVED_PROXY_GROUP_NAMES
    valid_groups: list[dict] = []
    for group in groups:
        name = str(group.get("name") or "").strip()
        if not name:
            continue
        proxies = [str(item).strip() for item in group.get("proxies") or [] if str(item).strip()]
        valid_proxies = [proxy for proxy in proxies if proxy in available]
        missing_proxies = [proxy for proxy in proxies if proxy not in available]
        if missing_proxies:
            log(f"自定义策略组 {name} 生成配置时已跳过不存在节点引用: {', '.join(missing_proxies)}")
        if not valid_proxies:
            log(f"自定义策略组 {name} 没有可用节点，已跳过写入")
            continue
        sanitized = dict(group)
        sanitized["name"] = name
        sanitized["proxies"] = valid_proxies
        valid_groups.append(sanitized)
    return valid_groups

def add_custom_names_to_main_selectors(text: str, custom_names: list[str]) -> str:
    if not custom_names:
        return text

    custom_items = [yaml_scalar(name) for name in custom_names]
    lines = text.splitlines()
    result: list[str] = []
    for line in lines:
        if "type: select" in line and "proxies: [" in line and "自动选择" in line and "故障转移" in line:
            prefix, rest = line.split("proxies: [", 1)
            current = rest.split("]", 1)[0]
            missing = [item for item, name in zip(custom_items, custom_names) if name not in current]
            if missing:
                line = f"{prefix}proxies: [{', '.join(missing)}, {rest}"
        result.append(line)
    return "\n".join(result) + ("\n" if text.endswith("\n") else "")

def remove_custom_names_from_main_selectors(text: str, custom_names: list[str]) -> str:
    if not custom_names:
        return text

    lines = text.splitlines()
    result: list[str] = []
    encoded_names = {yaml_scalar(name) for name in custom_names}
    raw_names = set(custom_names)
    for line in lines:
        if "type: select" in line and "proxies: [" in line and "自动选择" in line and "故障转移" in line:
            prefix, rest = line.split("proxies: [", 1)
            values, suffix = rest.split("]", 1)
            kept = [
                item.strip()
                for item in values.split(",")
                if item.strip() and item.strip() not in encoded_names and item.strip().strip("'\"") not in raw_names
            ]
            line = f"{prefix}proxies: [{', '.join(kept)}]{suffix}"
        result.append(line)
    return "\n".join(result) + ("\n" if text.endswith("\n") else "")

def apply_custom_proxy_groups_to_text(text: str, groups: list[dict]) -> str:
    previous_custom_names = custom_group_names_in_text(text)
    text = strip_custom_proxy_group_block(text)
    text = remove_custom_names_from_main_selectors(text, previous_custom_names)
    valid_groups = valid_custom_proxy_groups_for_text(text, groups)
    if not valid_groups:
        return text

    text = add_custom_names_to_main_selectors(text, [group["name"] for group in valid_groups])
    block = "\n".join(
        [CUSTOM_GROUP_BLOCK_START]
        + [custom_proxy_group_line(group) for group in valid_groups]
        + [CUSTOM_GROUP_BLOCK_END]
    )
    marker = "\nrules:"
    if marker not in text:
        raise ValueError("配置缺少 rules 段，无法插入自定义策略组")
    return text.replace(marker, f"\n{block}{marker}", 1)

def apply_custom_proxy_groups_file() -> bool:
    ensure_generated_config_exists()
    if not GENERATED_CONFIG_FILE.exists():
        raise ValueError("generated.yaml 不存在")
    current = GENERATED_CONFIG_FILE.read_text(encoding="utf-8")
    updated = apply_custom_proxy_groups_to_text(current, load_custom_proxy_groups())
    if updated == current:
        return False
    GENERATED_CONFIG_FILE.write_text(updated, encoding="utf-8")
    return True


def load_flow_cache() -> dict[str, dict]:
    data = load_json_file(SUBSTORE_FLOW_CACHE_FILE)
    return data if isinstance(data, dict) else {}


def save_flow_cache(cache: dict[str, dict]) -> None:
    SUBSTORE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SUBSTORE_FLOW_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_rendered_config_cache_key(env: dict[str, str], source_url: str) -> str:
    source_name = (env.get("SUBSTORE_SOURCE_NAME") or "").strip()
    if source_name:
        source_kind = (env.get("SUBSTORE_SOURCE_KIND") or "sub").strip() or "sub"
        return f"substore:{source_kind}:{source_name}"
    return f"remote:{source_url.strip()}"


def get_rendered_config_cache_file(cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return RENDERED_CONFIG_CACHE_DIR / f"{digest}.yaml"


def yaml_sequence_item_count(text: str, key: str) -> int:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not re.match(rf"^{re.escape(key)}:\s*$", line):
            continue
        base_indent = len(line) - len(line.lstrip())
        count = 0
        for child in lines[index + 1 :]:
            if not child.strip() or child.lstrip().startswith("#"):
                continue
            indent = len(child) - len(child.lstrip())
            if indent <= base_indent:
                break
            if child.lstrip().startswith("- "):
                count += 1
        return count
    return -1


def yaml_mapping_has_entries(text: str, key: str) -> bool:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not re.match(rf"^{re.escape(key)}:\s*$", line):
            continue
        base_indent = len(line) - len(line.lstrip())
        for child in lines[index + 1 :]:
            if not child.strip() or child.lstrip().startswith("#"):
                continue
            return len(child) - len(child.lstrip()) > base_indent
        return False
    return False


def validate_rendered_config_snapshot(content: bytes) -> None:
    text = content.decode("utf-8")
    proxy_count = yaml_sequence_item_count(text, "proxies")
    has_proxy_providers = yaml_mapping_has_entries(text, "proxy-providers")
    group_count = yaml_sequence_item_count(text, "proxy-groups")
    rule_count = yaml_sequence_item_count(text, "rules")
    if proxy_count <= 0 and not has_proxy_providers:
        raise ValueError("配置快照没有代理节点或代理提供器")
    if group_count <= 0:
        raise ValueError("配置快照缺少策略组")
    if rule_count <= 0:
        raise ValueError("配置快照缺少规则")


def load_rendered_config_cache(cache_key: str) -> bytes | None:
    cache_file = get_rendered_config_cache_file(cache_key)
    if not cache_file.exists():
        return None
    content = cache_file.read_bytes()
    try:
        validate_rendered_config_snapshot(content)
    except Exception as exc:  # noqa: BLE001
        log(f"忽略无效配置快照 key={cache_key} error={exc}")
        return None
    return content


def save_rendered_config_cache(cache_key: str, content: bytes) -> None:
    validate_rendered_config_snapshot(content)
    RENDERED_CONFIG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    get_rendered_config_cache_file(cache_key).write_bytes(content)


def delete_rendered_config_cache(cache_key: str) -> None:
    get_rendered_config_cache_file(cache_key).unlink(missing_ok=True)


def load_source_rendered_config(kind: str, name: str, source_url: str = "") -> tuple[str, bytes] | None:
    cache_keys = [f"substore:{kind}:{name}"]
    if source_url:
        cache_keys.append(f"remote:{source_url}")
    cache_keys.sort(
        key=lambda cache_key: get_rendered_config_cache_file(cache_key).stat().st_mtime
        if get_rendered_config_cache_file(cache_key).exists()
        else 0,
        reverse=True,
    )
    for cache_key in cache_keys:
        content = load_rendered_config_cache(cache_key)
        if content is not None:
            return cache_key, content
    return None


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


def extract_subscription_display_name(headers: Mapping[str, str]) -> str | None:
    content_disposition = headers.get("content-disposition", "")
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

    profile_title = headers.get("profile-title", "").strip()
    if profile_title:
        return urllib.parse.unquote(profile_title)
    return None


def inspect_subscription_display_name(source_url: str) -> str | None:
    try:
        with requests.get(
            source_url,
            headers=build_subscription_request_headers(),
            timeout=20,
        ) as response:
            response.raise_for_status()
            return extract_subscription_display_name(response.headers)
    except Exception:
        return None


def derive_source_name(source_url: str) -> str:
    parsed = urllib.parse.urlparse(source_url)
    host = (parsed.hostname or "auto-subscription").removeprefix("www.")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", host).strip("-")
    return safe or "auto-subscription"


def list_substore_subs(base_url: str) -> list[dict]:
    payload = json.loads(http_request(f"{base_url}/api/subs").decode("utf-8"))
    return payload.get("data") or []


def build_remote_source(name: str, source_url: str, display_name: str | None = None) -> dict[str, object]:
    resolved_display_name = display_name or inspect_subscription_display_name(source_url) or derive_source_display_name(source_url)
    return {
        "name": name,
        "displayName": resolved_display_name,
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
        "display-name": resolved_display_name,
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


def ensure_auto_remote_source(
    source_url: str,
    env: dict[str, str],
    display_name: str | None = None,
) -> dict[str, str]:
    base_url = env.get("SUBSTORE_BASE_URL", DEFAULT_SUBSTORE_BASE_URL).rstrip("/")
    resolved_display_name = display_name or inspect_subscription_display_name(source_url) or derive_source_display_name(source_url)
    for item in list_substore_subs(base_url):
        if (item.get("url") or "").strip() == source_url:
            source_name = (item.get("name") or "").strip()
            current_display_name = (
                item.get("displayName") or item.get("display-name") or derive_source_display_name(source_url)
            ).strip()
            if current_display_name != resolved_display_name:
                recreate_substore_source(
                    base_url,
                    build_remote_source(source_name, source_url, resolved_display_name),
                )
                current_display_name = resolved_display_name
            return {"name": source_name, "displayName": current_display_name}

    existing_names = {(item.get("name") or "").strip() for item in list_substore_subs(base_url) if (item.get("name") or "").strip()}
    source_name = choose_source_name(source_url, existing_names)
    source = build_remote_source(source_name, source_url, resolved_display_name)
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


_SUBSCRIPTION_REQUEST_PROFILES = (
    (
        "clash.meta",
        {
            "User-Agent": "clash.meta",
            "Accept": "*/*",
        },
    ),
    (
        "browser",
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        },
    ),
)


def build_subscription_request_headers(profile: str = "clash.meta") -> dict[str, str]:
    for profile_name, headers in _SUBSCRIPTION_REQUEST_PROFILES:
        if profile_name == profile:
            return dict(headers)
    raise ValueError(f"未知订阅请求配置：{profile}")


_SUBSCRIPTION_BODY_PREFIXES = (
    b"hysteria2://",
    b"hysteria://",
    b"vless://",
    b"vmess://",
    b"ss://",
    b"ssr://",
    b"trojan://",
    b"tuic://",
    b"wireguard://",
)
_SUBSCRIPTION_YAML_PATTERN = re.compile(
    rb"(?m)^(?:mixed-port|port|socks-port|redir-port|tproxy-port|mode|proxies|proxy-providers|proxy-groups|rules)\s*:"
)


def _looks_like_subscription_data(body: bytes) -> bool:
    sample = body[:4096].lstrip()
    if sample.startswith(_SUBSCRIPTION_BODY_PREFIXES):
        return True
    if _SUBSCRIPTION_YAML_PATTERN.search(sample):
        return True
    try:
        decoded = base64.b64decode(sample, validate=True)
        return bool(decoded.strip())
    except Exception:
        return False


def validate_subscription_response(body: bytes, headers: dict[str, str]) -> None:
    if not body.strip():
        raise ValueError("订阅返回空内容")

    clean = body.lstrip()
    if _looks_like_subscription_data(clean):
        return

    sample = clean[:2048].lower()
    if sample.startswith((b"<!doctype html", b"<html")):
        server = str(headers.get("server") or "").strip().lower()
        reason = "订阅返回 HTML 页面"
        if server == "cloudflare" or headers.get("cf-ray") or headers.get("cf-mitigated"):
            reason += "，可能被 Cloudflare 防护页拦截"
        raise ValueError(reason)

    content_type = str(headers.get("content-type") or "").lower()
    if "text/html" in content_type:
        server = str(headers.get("server") or "").strip().lower()
        reason = "订阅返回 HTML 页面"
        if server == "cloudflare" or headers.get("cf-ray") or headers.get("cf-mitigated"):
            reason += "，可能被 Cloudflare 防护页拦截"
        raise ValueError(reason)


def fetch_subscription_once(
    url: str,
    *,
    timeout: int,
    request_headers: dict[str, str] | None = None,
    proxy_url: str | None = None,
) -> tuple[bytes, dict[str, str]]:
    proxies = {}
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}
    with requests.Session() as session:
        session.headers.update(request_headers or build_subscription_request_headers())
        if not proxy_url:
            session.trust_env = False
        response = session.get(url, timeout=timeout, proxies=proxies or None)
        body = response.content
        headers = {key.lower(): value for key, value in response.headers.items()}
        response.raise_for_status()
    validate_subscription_response(body, headers)
    return body, headers


def format_subscription_errors(errors: list[tuple[str, Exception]]) -> str:
    return "；".join(f"{transport}: {exc}" for transport, exc in errors)


def fetch_subscription_payload(
    url: str,
    *,
    timeout: int = 60,
    substore_name: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[bytes, dict[str, str], dict[str, object]]:
    stack_env = env or load_stack_env()
    source_host = urllib.parse.urlparse(url).hostname or "unknown"
    transports = [
        ("直连", None),
        ("mihomo 代理", build_mihomo_proxy_url(stack_env)),
    ]
    errors: list[tuple[str, Exception]] = []

    for transport, proxy_url in transports:
        for client, request_headers in _SUBSCRIPTION_REQUEST_PROFILES:
            attempt = f"{transport}/{client}"
            started = time.monotonic()
            log(f"订阅拉取开始 host={source_host} transport={transport} client={client}")
            try:
                body, headers = fetch_subscription_once(
                    url,
                    timeout=timeout,
                    request_headers=dict(request_headers),
                    proxy_url=proxy_url,
                )
                elapsed_ms = round((time.monotonic() - started) * 1000)
                log(
                    f"订阅拉取完成 host={source_host} transport={transport} client={client} "
                    f"elapsed_ms={elapsed_ms} bytes={len(body)}"
                )
                if proxy_url:
                    log("直连订阅不可用，已通过 mihomo 代理拉取订阅")
                return body, headers, {
                    "used_cached": False,
                    "transport": transport,
                    "client": client,
                }
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = round((time.monotonic() - started) * 1000)
                log(
                    f"订阅拉取失败 host={source_host} transport={transport} client={client} "
                    f"elapsed_ms={elapsed_ms} error={redact_sensitive(exc)}"
                )
                errors.append((attempt, exc))

    cached_payload = find_cached_subscription_resource(substore_name or "")
    if cached_payload is None:
        raise ValueError(format_subscription_errors(errors))
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


def resolve_subscription_fetch_url(env: dict[str, str]) -> str:
    source_name = env.get("SUBSTORE_SOURCE_NAME", "").strip()
    source_kind = env.get("SUBSTORE_SOURCE_KIND", "sub").strip() or "sub"
    if source_name and source_kind == "sub":
        source = next(
            (item for item in get_substore_items("sub") if (item.get("name") or "").strip() == source_name),
            None,
        )
        source_url = ((source or {}).get("url") or "").strip()
        if source_url:
            return source_url
    return resolve_source_url(env)


def describe_source_transport(env: dict[str, str]) -> str:
    source_name = env.get("SUBSTORE_SOURCE_NAME", "").strip()
    if not source_name:
        return "独立订阅链接"
    source_kind = env.get("SUBSTORE_SOURCE_KIND", "sub").strip() or "sub"
    if source_kind == "collection":
        return "组合订阅"
    return "单条订阅"


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
    text = re.sub(r"^external-ui:\s*.*\n?", "", text, count=1, flags=re.MULTILINE)
    text = replace_or_append_line(
        text,
        r"^mixed-port:\s*.*$",
        f"mixed-port: {mixed_port}",
        anchor=f"secret: '{controller_secret}'",
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
        text = text.replace(f"secret: '{controller_secret}'", f"secret: '{controller_secret}'\n{geox_block}", 1)

    if not text.endswith("\n"):
        text += "\n"
    return text


def render_subscription_config(body: bytes, env: dict[str, str]) -> bytes:
    raw_config = body.decode("utf-8")
    patched_text = apply_custom_proxy_groups_to_text(
        patch_config(raw_config, env),
        load_custom_proxy_groups(),
    )
    rendered = patched_text.encode("utf-8")
    validate_rendered_config_snapshot(rendered)
    return rendered


def write_if_changed(path: Path, content: bytes) -> bool:
    if path.exists() and path.read_bytes() == content:
        return False
    path.write_bytes(content)
    return True


def ensure_rule_data_file(path: Path, url: str, label: str) -> bool:
    if path.exists() and path.stat().st_size > 0:
        size = path.stat().st_size
        detail = f"复用已有文件，{size} bytes"
        set_sync_stage_detail(detail)
        log(f"规则数据 {label}: {detail}")
        return False

    set_sync_stage_detail("本地文件缺失，正在下载")
    body = http_request(url, timeout=60)
    changed = write_if_changed(path, body)
    detail = f"下载完成，{len(body)} bytes"
    set_sync_stage_detail(detail)
    log(f"规则数据 {label}: {detail}")
    return changed


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


def sync_once(
    *,
    trigger: str = "manual",
    subscription_payload: tuple[str, bytes, dict[str, str], dict[str, object]] | None = None,
    rendered_config_payload: tuple[str, bytes] | None = None,
) -> dict[str, object]:
    if subscription_payload is not None and rendered_config_payload is not None:
        raise ValueError("订阅响应和本地配置不能同时传入")
    sync_id = f"{int(time.time() * 1000):x}-{threading.get_ident()}"
    prior_elapsed_ms = 0
    if subscription_payload is not None:
        prior_elapsed_ms = int(subscription_payload[3].get("prepare_elapsed_ms") or 0)
    operation_label = get_sync_operation_label(trigger)
    wait_started = time.monotonic()
    if SYNC_LOCK.locked():
        log(f"同步 {sync_id} 等待已有任务完成 trigger={trigger}")

    with SYNC_LOCK:
        wait_ms = round((time.monotonic() - wait_started) * 1000)
        started = time.monotonic()
        source_url = ""
        set_state(
            last_status="running",
            last_error=None,
            sync_id=sync_id,
            sync_trigger=trigger,
            operation_label=operation_label,
            sync_started_at=time.time(),
            sync_elapsed_ms=None,
            stage_history=[],
            stage_labels=(
                [{"code": code, "label": label} for code, label in ACTIVE_UPDATE_STAGES]
                if trigger == "api-update-active"
                else []
            ),
        )
        log(f"同步 {sync_id} 开始 trigger={trigger} wait_ms={wait_ms}")

        try:
            with sync_stage(sync_id, 1, "prepare", get_sync_stage_label(trigger, 1, "读取同步配置")):
                env = load_stack_env()
                source_url = resolve_source_url(env)
                fetch_url = resolve_subscription_fetch_url(env)
                rendered_cache_key = build_rendered_config_cache_key(env, source_url)
                secret = env.get("CONTROLLER_SECRET", "123456").strip() or "123456"
                set_state(last_source_url=fetch_url)
                apply_custom_proxy_groups_file()

            input_stage_label = "读取本地配置" if rendered_config_payload is not None else "下载订阅"
            with sync_stage(
                sync_id,
                2,
                "subscription",
                get_sync_stage_label(trigger, 2, input_stage_label),
            ) as stage_metrics:
                if rendered_config_payload is not None:
                    rendered_cache_source, rendered_config = rendered_config_payload
                    subscription_body = b""
                    subscription_headers = {}
                    subscription_meta = {}
                    set_sync_stage_detail(f"本地快照 {rendered_cache_source}，{len(rendered_config)} bytes")
                elif subscription_payload is not None:
                    prepared_url, subscription_body, subscription_headers, subscription_meta = subscription_payload
                    configured_remote_url = env.get("SUBSCRIPTION_URL", "").strip()
                    if prepared_url not in {fetch_url, configured_remote_url}:
                        raise ValueError("导入订阅与当前配置来源不一致")
                    subscription_meta = {**subscription_meta, "provided": True}
                    fetch_elapsed_ms = int(subscription_meta.get("fetch_elapsed_ms") or 0)
                    if fetch_elapsed_ms > 0:
                        stage_metrics["elapsed_ms"] = fetch_elapsed_ms
                    set_sync_stage_detail(f"本次 HTTP 响应，{len(subscription_body)} bytes")
                else:
                    subscription_body, subscription_headers, subscription_meta = fetch_subscription_payload(
                        fetch_url,
                        substore_name=(env.get("SUBSTORE_SOURCE_NAME") or "").strip() or None,
                    )
                    set_sync_stage_detail(
                        f"{subscription_meta.get('transport') or '本地缓存'}"
                        f"/{subscription_meta.get('client') or 'cache'}，{len(subscription_body)} bytes"
                    )
            subscription_elapsed_ms = int(stage_metrics.get("elapsed_ms") or 0)

            with sync_stage(sync_id, 3, "render", get_sync_stage_label(trigger, 3, "处理订阅配置")):
                used_cached_rendered_config = False
                used_local_rendered_config = rendered_config_payload is not None
                if used_local_rendered_config:
                    patched_config = apply_custom_proxy_groups_to_text(
                        rendered_config.decode("utf-8"),
                        load_custom_proxy_groups(),
                    ).encode("utf-8")
                else:
                    if subscription_meta.get("used_cached"):
                        rendered_cache = load_rendered_config_cache(rendered_cache_key)
                        if rendered_cache is not None:
                            patched_config = apply_custom_proxy_groups_to_text(
                                rendered_cache.decode("utf-8"),
                                load_custom_proxy_groups(),
                            ).encode("utf-8")
                            used_cached_rendered_config = True
                            log("订阅回退时已优先使用本地完整配置缓存，并重新清理自定义策略组节点引用")
                        else:
                            patched_config = render_subscription_config(subscription_body, env)
                    else:
                        patched_config = render_subscription_config(subscription_body, env)
                validate_rendered_config_snapshot(patched_config)
                set_sync_stage_detail(f"生成配置 {len(patched_config)} bytes")

            with sync_stage(sync_id, 4, "write-config", get_sync_stage_label(trigger, 4, "写入运行配置")):
                ensure_generated_config_exists()
                config_changed = write_if_changed(GENERATED_CONFIG_FILE, patched_config)
                set_sync_stage_detail("配置已更新" if config_changed else "配置内容未变化")

            with sync_stage(sync_id, 5, "geoip", get_sync_stage_label(trigger, 5, "检查 GeoIP 数据")):
                geoip_changed = ensure_rule_data_file(GEOIP_FILE, GEOIP_URL, "GeoIP")

            with sync_stage(sync_id, 6, "mmdb", get_sync_stage_label(trigger, 6, "检查 MMDB 数据")):
                mmdb_changed = ensure_rule_data_file(MMDB_FILE, MMDB_URL, "MMDB")

            with sync_stage(sync_id, 7, "geosite", get_sync_stage_label(trigger, 7, "检查 GeoSite 数据")):
                geosite_changed = ensure_rule_data_file(GEOSITE_FILE, GEOSITE_URL, "GeoSite")

            with sync_stage(sync_id, 8, "cache", get_sync_stage_label(trigger, 8, "保存配置快照")):
                if used_local_rendered_config or not subscription_meta.get("used_cached") or used_cached_rendered_config:
                    save_rendered_config_cache(rendered_cache_key, patched_config)
                    if not used_local_rendered_config and not subscription_meta.get("used_cached"):
                        remote_cache_key = f"remote:{fetch_url}"
                        if remote_cache_key != rendered_cache_key:
                            save_rendered_config_cache(remote_cache_key, patched_config)
                    set_sync_stage_detail("本地配置快照已保存")
                else:
                    set_sync_stage_detail("当前使用回退缓存，无需覆盖")

            used_cached_subscription = bool(subscription_meta.get("used_cached"))
            changed = any((config_changed, geoip_changed, mmdb_changed, geosite_changed))
            is_local_switch = used_local_rendered_config and trigger == "api-switch-local"
            is_active_update = trigger == "api-update-active"
            with sync_stage(sync_id, 9, "reload", get_sync_stage_label(trigger, 9, "应用 Mihomo 配置")):
                if changed or is_active_update:
                    reload_mihomo(secret)
                    if is_local_switch:
                        message = "已切换到本地配置并通知 mihomo 热重载"
                    elif is_active_update:
                        message = "订阅已更新并通知 mihomo 热重载"
                    else:
                        message = "配置已更新并通知 mihomo 热重载"
                    set_sync_stage_detail(
                        "Mihomo 热重载完成" if changed else "配置内容未变化，Mihomo 热重载完成"
                    )
                else:
                    if is_local_switch:
                        message = "已切换到本地配置，内容未变化"
                    else:
                        message = "配置未变化，跳过重载"
                    set_sync_stage_detail("配置未变化，无需重载")

            if used_cached_rendered_config:
                message = f"源站不可用，已使用本地完整配置缓存；{message}"
            elif used_cached_subscription:
                message = f"源站不可用，已使用本地缓存配置；{message}"

            with sync_stage(sync_id, 10, "metadata", get_sync_stage_label(trigger, 10, "更新订阅状态")):
                active_name = (env.get("SUBSTORE_SOURCE_NAME") or "").strip()
                if is_local_switch:
                    set_sync_stage_detail("本地配置切换完成")
                elif is_active_update:
                    set_sync_stage_detail("当前订阅更新完成")
                elif active_name:
                    refresh_live_flow(active_name)
                    set_sync_stage_detail("订阅状态已更新")
                else:
                    mirror_source = find_substore_sub_by_url(fetch_url)
                    direct_flow = extract_subscription_flow(subscription_headers)
                    mirror_name = ((mirror_source or {}).get("name") or "").strip()
                    if mirror_name and direct_flow:
                        cache_flow_result(mirror_name, direct_flow)
                    set_sync_stage_detail("订阅状态已更新")

            timestamp = datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            processing_elapsed_ms = round((time.monotonic() - started) * 1000)
            elapsed_ms = prior_elapsed_ms + processing_elapsed_ms
            set_state(
                last_sync_at=timestamp,
                last_status="ok",
                last_error=None,
                last_source_url=fetch_url,
                sync_elapsed_ms=elapsed_ms,
                current_stage="complete",
                current_stage_label=f"{operation_label}完成",
                current_stage_detail=message,
                current_stage_index=SYNC_STAGE_TOTAL,
                current_stage_total=SYNC_STAGE_TOTAL,
                current_stage_started_at=None,
                current_stage_elapsed_ms=elapsed_ms,
            )
            log(f"同步 {sync_id} 完成 total_ms={elapsed_ms} message={message}")
            return {
                "message": message,
                "last_sync_at": timestamp,
                "source_url": source_url,
                "used_cached_subscription": used_cached_subscription,
                "used_cached_rendered_config": used_cached_rendered_config,
                "used_local_rendered_config": used_local_rendered_config,
                "sync_elapsed_ms": elapsed_ms,
                "processing_elapsed_ms": processing_elapsed_ms,
                "fetch_elapsed_ms": subscription_elapsed_ms,
                "bytes": len(subscription_body),
                "transport": subscription_meta.get("transport"),
                "client": subscription_meta.get("client"),
            }
        except Exception as exc:
            elapsed_ms = prior_elapsed_ms + round((time.monotonic() - started) * 1000)
            error = redact_sensitive(exc)
            set_state(last_status="error", last_error=error, sync_elapsed_ms=elapsed_ms)
            log(f"同步 {sync_id} 失败 total_ms={elapsed_ms} error={error}")
            raise


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


def find_substore_source(kind: str, name: str) -> dict[str, str] | None:
    sources = fetch_substore_sources()
    items = sources["collections"] if kind == "collection" else sources["subs"]
    return next((item for item in items if item.get("name") == name), None)


def update_inactive_source_snapshot(
    *,
    kind: str,
    name: str,
    source_url: str,
    original_url: str,
    env: dict[str, str],
) -> dict[str, object]:
    sync_id = f"{int(time.time() * 1000):x}-{threading.get_ident()}"
    wait_started = time.monotonic()
    if SYNC_LOCK.locked():
        log(f"订阅更新 {sync_id} 等待已有任务完成 name={name}")

    with SYNC_LOCK:
        wait_ms = round((time.monotonic() - wait_started) * 1000)
        started = time.monotonic()
        set_state(
            last_status="running",
            last_error=None,
            last_source_url=source_url,
            sync_id=sync_id,
            sync_trigger="api-update-inactive",
            operation_label="刷新订阅快照",
            sync_started_at=time.time(),
            sync_elapsed_ms=None,
            stage_history=[],
            stage_labels=[{"code": code, "label": label} for code, label in UPDATE_SNAPSHOT_STAGES],
        )
        log(f"订阅更新 {sync_id} 开始 name={name} wait_ms={wait_ms}")

        try:
            with sync_stage(sync_id, 1, *UPDATE_SNAPSHOT_STAGES[0]):
                primary_cache_key = f"substore:{kind}:{name}"
                set_sync_stage_detail(f"{name} · {'组合订阅' if kind == 'collection' else '单条订阅'}")

            with sync_stage(sync_id, 2, *UPDATE_SNAPSHOT_STAGES[1]) as stage_metrics:
                body, headers, meta = fetch_subscription_payload(source_url, timeout=60, env=env)
                set_sync_stage_detail(
                    f"{meta.get('transport') or '本地缓存'}/{meta.get('client') or 'cache'}，{len(body)} bytes"
                )
            fetch_elapsed_ms = int(stage_metrics.get("elapsed_ms") or 0)

            with sync_stage(sync_id, 3, *UPDATE_SNAPSHOT_STAGES[2]):
                rendered = render_subscription_config(body, env)
                set_sync_stage_detail(f"生成完整配置 {len(rendered)} bytes")

            with sync_stage(sync_id, 4, *UPDATE_SNAPSHOT_STAGES[3]):
                save_rendered_config_cache(primary_cache_key, rendered)
                set_sync_stage_detail("列表项完整快照已保存")

            with sync_stage(sync_id, 5, *UPDATE_SNAPSHOT_STAGES[4]):
                if original_url:
                    save_rendered_config_cache(f"remote:{original_url}", rendered)
                    set_sync_stage_detail("原始链接完整快照已保存")
                else:
                    set_sync_stage_detail("组合订阅没有独立链接快照")

            with sync_stage(sync_id, 6, *UPDATE_SNAPSHOT_STAGES[5]):
                direct_flow = extract_subscription_flow(headers)
                if kind == "sub" and direct_flow:
                    cache_flow_result(name, direct_flow)
                    set_sync_stage_detail("流量信息已更新")
                else:
                    set_sync_stage_detail("订阅响应未提供流量信息")

            with sync_stage(sync_id, 7, *UPDATE_SNAPSHOT_STAGES[6]):
                current_env = load_stack_env()
                current_name = current_env.get("SUBSTORE_SOURCE_NAME", "").strip()
                set_sync_stage_detail(f"当前来源仍为 {current_name or '独立订阅链接'}")

            with sync_stage(sync_id, 8, *UPDATE_SNAPSHOT_STAGES[7]):
                set_sync_stage_detail("运行配置保持不变")

            with sync_stage(sync_id, 9, *UPDATE_SNAPSHOT_STAGES[8]):
                set_sync_stage_detail("非当前订阅无需应用到 Mihomo")

            message = "订阅快照已更新，当前配置未切换"
            with sync_stage(sync_id, 10, *UPDATE_SNAPSHOT_STAGES[9]):
                set_sync_stage_detail(message)

            timestamp = datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            elapsed_ms = round((time.monotonic() - started) * 1000)
            set_state(
                last_sync_at=timestamp,
                last_status="ok",
                last_error=None,
                sync_elapsed_ms=elapsed_ms,
                current_stage="complete",
                current_stage_label="刷新订阅快照完成",
                current_stage_detail=message,
                current_stage_index=SYNC_STAGE_TOTAL,
                current_stage_total=SYNC_STAGE_TOTAL,
                current_stage_started_at=None,
                current_stage_elapsed_ms=elapsed_ms,
            )
            log(f"订阅更新 {sync_id} 完成 name={name} total_ms={elapsed_ms}")
            return {
                "kind": kind,
                "name": name,
                "applied": False,
                "fetch_elapsed_ms": fetch_elapsed_ms,
                "bytes": len(body),
                "transport": meta.get("transport"),
                "client": meta.get("client"),
                "message": message,
                "sync": {
                    "sync_elapsed_ms": elapsed_ms,
                    "fetch_elapsed_ms": fetch_elapsed_ms,
                },
            }
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            error = redact_sensitive(exc)
            set_state(last_status="error", last_error=error, sync_elapsed_ms=elapsed_ms)
            log(f"订阅更新 {sync_id} 失败 name={name} total_ms={elapsed_ms} error={error}")
            raise


def update_source_snapshot(payload: dict[str, str], *, track_progress: bool = True) -> dict[str, object]:
    kind = (payload.get("kind") or "sub").strip()
    name = (payload.get("name") or "").strip()
    if kind not in {"sub", "collection"}:
        raise ValueError("kind 只能是 sub 或 collection")
    if not name:
        raise ValueError("name 不能为空")

    source = find_substore_source(kind, name)
    if source is None:
        raise ValueError(f"订阅来源不存在：{name}")

    env = load_stack_env()
    source_url = (source.get("url") or "").strip()
    if not source_url:
        candidate_env = dict(env)
        candidate_env.update(
            {
                "SUBSTORE_SOURCE_KIND": kind,
                "SUBSTORE_SOURCE_NAME": name,
            }
        )
        source_url = resolve_source_url(candidate_env)

    original_url = (source.get("url") or "").strip()
    if not track_progress:
        started = time.monotonic()
        body, headers, meta = fetch_subscription_payload(source_url, timeout=60, env=env)
        fetch_elapsed_ms = round((time.monotonic() - started) * 1000)
        rendered = render_subscription_config(body, env)
        save_rendered_config_cache(f"substore:{kind}:{name}", rendered)
        if original_url:
            save_rendered_config_cache(f"remote:{original_url}", rendered)
        direct_flow = extract_subscription_flow(headers)
        if kind == "sub" and direct_flow:
            cache_flow_result(name, direct_flow)
        return {
            "kind": kind,
            "name": name,
            "applied": False,
            "fetch_elapsed_ms": fetch_elapsed_ms,
            "bytes": len(body),
            "transport": meta.get("transport"),
            "client": meta.get("client"),
            "message": "订阅快照已准备",
            "sync": None,
        }

    active_name = env.get("SUBSTORE_SOURCE_NAME", "").strip()
    active_kind = env.get("SUBSTORE_SOURCE_KIND", "sub").strip() or "sub"
    active_remote_url = env.get("SUBSCRIPTION_URL", "").strip()
    is_active = (active_name == name and active_kind == kind) or (
        not active_name and bool(original_url) and active_remote_url == original_url
    )
    if is_active:
        sync_result = sync_once(
            trigger="api-update-active",
        )
        return {
            "kind": kind,
            "name": name,
            "applied": True,
            "fetch_elapsed_ms": sync_result.get("fetch_elapsed_ms"),
            "bytes": sync_result.get("bytes"),
            "transport": sync_result.get("transport"),
            "client": sync_result.get("client"),
            "message": "订阅已更新并应用",
            "sync": sync_result,
        }

    return update_inactive_source_snapshot(
        kind=kind,
        name=name,
        source_url=source_url,
        original_url=original_url,
        env=env,
    )


def switch_source(payload: dict[str, str]) -> dict[str, object]:
    kind = (payload.get("kind") or "sub").strip()
    name = (payload.get("name") or "").strip()
    if kind not in {"sub", "collection"}:
        raise ValueError("kind 只能是 sub 或 collection")
    if not name:
        raise ValueError("name 不能为空")

    source = find_substore_source(kind, name)
    if source is None:
        raise ValueError(f"订阅来源不存在：{name}")
    source_url = (source.get("url") or "").strip()
    rendered_config = load_source_rendered_config(kind, name, source_url)

    if rendered_config is None:
        update_source_snapshot({"kind": kind, "name": name}, track_progress=False)
        rendered_config = load_source_rendered_config(kind, name, source_url)
    if rendered_config is None:
        raise ValueError(f"订阅 {name} 没有可用的完整配置快照")

    source_result = update_source({"mode": "substore", "kind": kind, "name": name})
    sync_result = sync_once(
        trigger="api-switch-local",
        rendered_config_payload=rendered_config,
    )
    return {
        "source": source_result,
        "sync": sync_result,
        "used_local_rendered_config": True,
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
            raise ValueError(f"远程订阅不可用，未启用：{exc}") from exc
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


def prepare_source_url(
    payload: dict[str, str],
) -> tuple[dict[str, object], tuple[str, bytes, dict[str, str], dict[str, object]]]:
    source_url = (payload.get("url") or "").strip()
    if not source_url:
        raise ValueError("订阅链接不能为空")

    operation_id = f"{int(time.time() * 1000):x}-{threading.get_ident()}"
    source_host = urllib.parse.urlparse(source_url).hostname or "unknown"
    operation_started = time.monotonic()
    log(f"来源导入 {operation_id} 开始 host={source_host}")
    env = load_stack_env()
    try:
        stage_started = time.monotonic()
        subscription_body, subscription_headers, subscription_meta = fetch_subscription_payload(
            source_url,
            timeout=30,
            env=env,
        )
        fetch_elapsed_ms = round((time.monotonic() - stage_started) * 1000)
        subscription_meta = {**subscription_meta, "fetch_elapsed_ms": fetch_elapsed_ms}
        display_name = extract_subscription_display_name(subscription_headers) or derive_source_display_name(source_url)
        log(
            f"来源导入 {operation_id} 验证订阅完成 elapsed_ms={fetch_elapsed_ms} "
            f"bytes={len(subscription_body)} transport={subscription_meta.get('transport')} "
            f"client={subscription_meta.get('client')}"
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"远程订阅不可用，当前配置保持不变：{exc}") from exc

    auto_source: dict[str, str] | None = None
    try:
        stage_started = time.monotonic()
        auto_source = ensure_auto_remote_source(source_url, env, display_name)
        log(
            f"来源导入 {operation_id} 更新 Sub-Store 镜像完成 elapsed_ms="
            f"{round((time.monotonic() - stage_started) * 1000)}"
        )
    except Exception as exc:  # noqa: BLE001
        log(f"创建 Sub-Store 镜像来源失败，已忽略：{exc}")

    active_source_name = ((auto_source or {}).get("name") or "").strip()
    save_stack_env(
        {
            "SUBSCRIPTION_URL": source_url,
            "SUBSTORE_SOURCE_KIND": "sub" if active_source_name else "",
            "SUBSTORE_SOURCE_NAME": active_source_name,
        }
    )
    current_env = load_stack_env()
    prepare_elapsed_ms = round((time.monotonic() - operation_started) * 1000)
    subscription_meta = {**subscription_meta, "prepare_elapsed_ms": prepare_elapsed_ms}
    log(
        f"来源导入 {operation_id} 完成 host={source_host} total_ms="
        f"{prepare_elapsed_ms}"
    )
    result = {
        "mode": "substore" if active_source_name else "remote",
        "kind": "sub" if active_source_name else "",
        "name": active_source_name,
        "display_name": (auto_source or {}).get("displayName") or display_name,
        "created": (auto_source or {}).get("created") == "true",
        "source_url": resolve_source_url(current_env),
    }
    prepared_subscription = (source_url, subscription_body, subscription_headers, subscription_meta)
    return result, prepared_subscription


def update_source_url(payload: dict[str, str]) -> dict[str, object]:
    result, _ = prepare_source_url(payload)
    return result


def update_source_url_and_sync(payload: dict[str, str]) -> dict[str, object]:
    source_result, prepared_subscription = prepare_source_url(payload)
    sync_result = sync_once(
        trigger="api-import",
        subscription_payload=prepared_subscription,
    )
    return {
        "source": source_result,
        "sync": sync_result,
    }


def remove_source(payload: dict[str, str]) -> dict[str, str]:
    kind = (payload.get("kind") or "sub").strip()
    name = (payload.get("name") or "").strip()
    if kind not in {"sub", "collection"}:
        raise ValueError("kind 只能是 sub 或 collection")
    if not name:
        raise ValueError("name 不能为空")
    source = find_substore_source(kind, name)
    result = delete_substore_source(kind, name)
    delete_rendered_config_cache(f"substore:{kind}:{name}")
    source_url = ((source or {}).get("url") or "").strip()
    if source_url:
        delete_rendered_config_cache(f"remote:{source_url}")
    return result

def get_custom_proxy_groups_payload() -> dict:
    return {"groups": load_custom_proxy_groups()}

def apply_custom_proxy_groups_and_reload() -> dict:
    env = load_stack_env()
    secret = env.get("CONTROLLER_SECRET", "123456").strip() or "123456"
    changed = apply_custom_proxy_groups_file()
    reload_mihomo(secret)
    return {"changed": changed, "groups": load_custom_proxy_groups()}

def save_custom_proxy_group(payload: dict) -> dict:
    ensure_generated_config_exists()
    current_text = GENERATED_CONFIG_FILE.read_text(encoding="utf-8") if GENERATED_CONFIG_FILE.exists() else ""
    groups = load_custom_proxy_groups()
    existing_custom_names = {str(group.get("name") or "").strip() for group in groups}
    group = validate_custom_proxy_group(
        payload,
        existing_custom_names=existing_custom_names,
        native_names=native_proxy_group_names(current_text),
    )
    next_groups = [item for item in groups if item.get("name") != group["name"]]
    next_groups.append(group)
    save_custom_proxy_groups(next_groups)
    return apply_custom_proxy_groups_and_reload()

def delete_custom_proxy_group(payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("策略组名称不能为空")
    groups = load_custom_proxy_groups()
    next_groups = [item for item in groups if item.get("name") != name]
    if len(next_groups) == len(groups):
        raise ValueError(f"自定义策略组不存在：{name}")
    save_custom_proxy_groups(next_groups)
    return apply_custom_proxy_groups_and_reload()


class SyncHandler(BaseHTTPRequestHandler):
    server_version = "MihomoSync/1.0"

    def _begin_request(self) -> None:
        self._request_started = time.monotonic()
        self._request_id = f"{int(time.time() * 1000):x}-{threading.get_ident()}"
        if self.command == "POST":
            path = urllib.parse.urlparse(self.path).path
            log(f"API {self._request_id} 开始 method={self.command} path={path}")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        disconnected = False
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            disconnected = True
        if self.command == "POST" or status >= 400:
            elapsed_ms = round((time.monotonic() - getattr(self, "_request_started", time.monotonic())) * 1000)
            request_id = getattr(self, "_request_id", "unknown")
            path = urllib.parse.urlparse(self.path).path
            log(
                f"API {request_id} 结束 method={self.command} path={path} status={status} "
                f"elapsed_ms={elapsed_ms} client_disconnected={str(disconnected).lower()}"
            )

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self) -> None:  # noqa: N802
        self._begin_request()
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

        if self.path == "/custom-proxy-groups":
            self._send_json(200, {"status": "success", "data": get_custom_proxy_groups_payload()})
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
        self._begin_request()
        try:
            if self.path == "/sync":
                result = sync_once(trigger="api")
                self._send_json(200, {"status": "success", "data": result})
                return

            if self.path == "/source":
                payload = self._read_json()
                result = update_source(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            if self.path == "/source-switch":
                payload = self._read_json()
                result = switch_source(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            if self.path == "/source-update":
                payload = self._read_json()
                result = update_source_snapshot(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            if self.path == "/source-url":
                payload = self._read_json()
                result = update_source_url(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            if self.path == "/source-url-apply":
                payload = self._read_json()
                result = update_source_url_and_sync(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            if self.path == "/source-delete":
                payload = self._read_json()
                result = remove_source(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            if self.path == "/custom-proxy-groups":
                payload = self._read_json()
                result = save_custom_proxy_group(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            if self.path == "/custom-proxy-groups-delete":
                payload = self._read_json()
                result = delete_custom_proxy_group(payload)
                self._send_json(200, {"status": "success", "data": result})
                return

            self._send_json(404, {"status": "error", "message": "Not Found"})
        except ValueError as exc:
            error = redact_sensitive(exc)
            set_state(last_status="error", last_error=error)
            self._send_json(400, {"status": "error", "message": error})
        except Exception as exc:  # noqa: BLE001
            error = redact_sensitive(exc)
            set_state(last_status="error", last_error=error)
            self._send_json(500, {"status": "error", "message": error})

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def loop_sync() -> None:
    while True:
        try:
            sync_once(trigger="scheduled")
        except Exception as exc:  # noqa: BLE001
            error = redact_sensitive(exc)
            set_state(last_status="error", last_error=error)
            log(f"同步失败: {error}")

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
