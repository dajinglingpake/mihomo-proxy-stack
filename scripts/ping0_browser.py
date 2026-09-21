#!/usr/bin/env python3
"""Ping0 浏览器检测服务。

用 Playwright 驱动一个真实 Chromium，让它经 Mihomo 的指定节点出网访问 ping0.cc，
从而拿到该节点的 IP 风控/纯净度结果。

关于验证码的说明：
本服务不会破解、识别或绕过任何验证码。ping0.cc 在部分出口 IP 上会弹出 Cloudflare
Turnstile 验证，这时由真实浏览器自己把校验跑完——托管挑战在跑完 JS 后通常直接放行，
等不到放行就刷新一次，还不行就返回 captcha 交给上层换数据源。全程不需要人参与。

接口：
    GET  /health                     服务状态
    POST /check                      发起检测，body: {"proxy": 节点名, ...}
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.auto_sync import (  # noqa: E402  (需要仓库根目录在 sys.path)
    PING0_HOME_URL,
    PING0_IP_URL,
    Ping0CaptchaBlocked,
    load_stack_env,
    parse_ping0_home_result,
)

DEFAULT_WORKER_PORT = 3021
DEFAULT_RESULT_TIMEOUT_SECONDS = 45
DEFAULT_PROFILE_DIR = BASE_DIR / ".ping0-profile"
DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = "7890"
# 指纹要自洽：容器里跑的是 Linux 上的 Chromium，伪装成 Windows 反而会在字体、
# 屏幕、WebGL 这些细节上和 UA 对不上，比老老实实用 Linux UA 更容易被判成机器人。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# 验证码页面特征
CAPTCHA_MARKERS = ("cf-turnstile", "captcha-element", "challenges.cloudflare.com", "turnstile")
# 结果页特征：光有 riskcurrent 不够——空结果页里也带着模板默认的 0%，
# 必须同时确认服务端注入的 window.ip 有值，才说明真的拿到了这个出口的数据。
RESULT_MARKERS = ("riskcurrent",)
POLL_INTERVAL_SECONDS = 1.5
# Cloudflare 的托管挑战在真实浏览器里通常自己跑完就放行，只是要几秒到十几秒。
# 给足这段时间，卡住超过一半就刷新一次——刷新后经常直接拿到数据。
CAPTCHA_GRACE_SECONDS = 25
CAPTCHA_RELOAD_AFTER_SECONDS = 10
CHROMIUM_ARGS = (
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--lang=zh-CN",
)
# 抹掉 Playwright 留下的自动化痕迹：Cloudflare 主要看 navigator.webdriver，
# 带着它连挑战都不给你过，直接判成机器人。
STEALTH_SCRIPT = """
(() => {
  const define = (object, name, value) => {
    try {
      Object.defineProperty(object, name, { get: () => value, configurable: true });
    } catch (error) {}
  };
  define(navigator, "webdriver", undefined);
  define(navigator, "languages", ["zh-CN", "zh", "en-US", "en"]);
  define(navigator, "platform", "%PLATFORM%");
  define(navigator, "hardwareConcurrency", 8);
  define(navigator, "deviceMemory", 8);
  define(navigator, "maxTouchPoints", 0);
  define(navigator, "plugins", { length: 5 });
  if (!window.chrome) {
    window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };
  }
  const permissions = navigator.permissions;
  if (permissions && permissions.query) {
    const original = permissions.query.bind(permissions);
    permissions.query = (parameters) =>
      parameters && parameters.name === "notifications"
        ? Promise.resolve({ state: Notification.permission })
        : original(parameters);
  }
  const proto = window.WebGLRenderingContext && window.WebGLRenderingContext.prototype;
  if (proto && proto.getParameter) {
    const original = proto.getParameter;
    proto.getParameter = function (parameter) {
      if (parameter === 37445) return "Intel Inc.";
      if (parameter === 37446) return "Intel Iris OpenGL Engine";
      return original.call(this, parameter);
    };
  }
})();
"""


def log(message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def stealth_script(user_agent: str) -> str:
    """按 UA 配套 platform：两者对不上比不伪装还显眼。"""
    platform = "Win32" if "Windows" in user_agent else "Linux x86_64"
    return STEALTH_SCRIPT.replace("%PLATFORM%", platform)


class Ping0BrowserError(RuntimeError):
    """检测失败，可重试。"""


class Ping0BrowserBusy(RuntimeError):
    """已有挂起会话占用浏览器。"""


class Mihomo:
    def __init__(self) -> None:
        env = load_stack_env()
        controller_addr = env.get("CONTROLLER_ADDR", "0.0.0.0:19090").strip() or "0.0.0.0:19090"
        self.secret = env.get("CONTROLLER_SECRET", "123456").strip() or "123456"
        host, _, port = controller_addr.rpartition(":")
        if not host or host in {"0.0.0.0", "*", "::"}:
            host = DEFAULT_PROXY_HOST
        self.base_url = f"http://{host}:{port or '19090'}"
        self.proxy_host = env.get("MIHOMO_PROXY_HOST", DEFAULT_PROXY_HOST).strip() or DEFAULT_PROXY_HOST
        self.proxy_port = env.get("MIHOMO_MIXED_PORT", DEFAULT_PROXY_PORT).strip() or DEFAULT_PROXY_PORT

    @property
    def proxy_server(self) -> str:
        return f"http://{self.proxy_host}:{self.proxy_port}"

    def request(self, path: str, method: str = "GET", payload: dict | None = None) -> object:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.secret}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise Ping0BrowserError(f"Mihomo 控制接口返回 HTTP {exc.code}") from exc
        except OSError as exc:
            raise Ping0BrowserError(f"无法连接 Mihomo 控制接口：{exc}") from exc
        return json.loads(raw) if raw.strip() else None

    def proxies(self) -> dict[str, object]:
        payload = self.request("/proxies")
        if not isinstance(payload, dict):
            raise Ping0BrowserError("Mihomo 节点列表格式无效")
        proxies = payload.get("proxies")
        return proxies if isinstance(proxies, dict) else {}

    def rules(self) -> list[dict]:
        payload = self.request("/rules")
        if not isinstance(payload, dict):
            return []
        rules = payload.get("rules")
        return [item for item in rules if isinstance(item, dict)] if isinstance(rules, list) else []

    def mode(self) -> str:
        payload = self.request("/configs")
        return str((payload or {}).get("mode") or "").strip().lower() if isinstance(payload, dict) else ""

    def select(self, group: str, target: str) -> None:
        self.request(f"/proxies/{urllib.parse.quote(group, safe='')}", "PUT", {"name": target})


def final_match_target(rules: list[dict]) -> str | None:
    """最终兜底规则（MATCH）指向的策略组。"""
    for rule in reversed(rules):
        if str(rule.get("type", "")).lower() == "match" and rule.get("proxy"):
            return str(rule["proxy"])
    return None


def is_selector(item: object) -> bool:
    return isinstance(item, dict) and str(item.get("type", "")).lower() == "selector"


def selection_plan(
    proxies: dict[str, object],
    rules: list[dict],
    node: str,
    mode: str = "",
    max_depth: int = 4,
) -> list[tuple[str, str]]:
    """计算「让流量经过 node」需要执行的切换动作。

    返回 [(策略组, 目标成员), ...]，按顺序执行即可。找不到可达路径时返回空列表。
    """
    roots: list[str] = []
    if mode == "global":
        roots.append("GLOBAL")
    match_target = final_match_target(rules)
    if match_target:
        roots.append(match_target)
    roots.append("GLOBAL")

    seen: set[str] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        plan = _walk_plan(proxies, root, node, [], 0, max_depth)
        if plan:
            return plan
    return []


def _walk_plan(
    proxies: dict[str, object],
    group: str,
    node: str,
    acc: list[tuple[str, str]],
    depth: int,
    max_depth: int,
) -> list[tuple[str, str]]:
    item = proxies.get(group)
    if not is_selector(item):
        return []
    members = [str(name) for name in (item.get("all") or [])]
    if node in members:
        return acc + [(group, node)]
    if depth >= max_depth:
        return []
    for member in members:
        if member in [step[0] for step in acc]:
            continue
        if is_selector(proxies.get(member)):
            plan = _walk_plan(proxies, member, node, acc + [(group, member)], depth + 1, max_depth)
            if plan:
                return plan
    return []


# --------------------------------------------------------------------------- #
# 浏览器会话
# --------------------------------------------------------------------------- #


@dataclass
class Ping0Browser:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pw = None
        self._context = None
        self._mihomo = None
        self._last_check_at: float = 0.0
        self._last_check_at: float = 0.0

    def busy(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return True
        self._lock.release()
        return False

    # -- 基础设置 ---------------------------------------------------------- #

    def profile_dir(self) -> Path:
        configured = os.environ.get("PING0_PROFILE_DIR", "").strip()
        return Path(configured) if configured else DEFAULT_PROFILE_DIR

    def headless(self) -> bool:
        value = os.environ.get("PING0_HEADLESS", "0").strip().lower()
        return value in {"1", "true", "yes"}

    def user_agent(self) -> str:
        return os.environ.get("PING0_USER_AGENT", "").strip() or DEFAULT_USER_AGENT

    def min_interval(self) -> float:
        """两次检测之间的最小间隔，避免密集请求把出口打成高风险。"""
        raw = str(load_stack_env().get("PING0_MIN_INTERVAL_SECONDS", "") or "").strip() or "2"
        try:
            return max(float(raw), 0.0)
        except ValueError:
            return 2.0

    def auto_retry(self) -> int:
        """被 Cloudflare 挡住后自动重试的次数（每次之间会冷却）。"""
        raw = str(load_stack_env().get("PING0_AUTO_RETRY", "") or "").strip() or "1"
        try:
            return max(int(raw), 0)
        except ValueError:
            return 1

    def retry_cooldown(self) -> int:
        raw = str(load_stack_env().get("PING0_RETRY_COOLDOWN_SECONDS", "") or "").strip() or "20"
        try:
            return max(int(raw), 0)
        except ValueError:
            return 20

    def _throttle(self) -> None:
        gap = self.min_interval()
        wait = gap - (time.time() - self._last_check_at)
        if gap > 0 and wait > 0:
            log(f"节流：等待 {wait:.1f} 秒再发下一次检测")
            time.sleep(wait)
        self._last_check_at = time.time()

    def _safe_text_exit_ip(self) -> str:
        try:
            return self._text_exit_ip()
        except Ping0BrowserError as exc:
            log(f"读取出口 IP 失败：{exc}")
            return ""

    def mihomo(self) -> Mihomo:
        if self._mihomo is None:
            self._mihomo = Mihomo()
        return self._mihomo

    def display(self) -> str:
        return os.environ.get("DISPLAY", "").strip() or ":99"

    def _discard_broken_profile(self) -> None:
        """清掉上次被强杀残留的锁与损坏的 prefs，避免 Chromium 起不来。"""
        profile_dir = self.profile_dir()
        if not profile_dir.exists():
            return
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "Local State"):
            try:
                (profile_dir / name).unlink()
            except OSError:
                pass

    def _launch(self, retry: bool = True):
        try:
            return self._launch_once()
        except Exception as exc:  # noqa: BLE001  (profile 损坏时启动会直接失败)
            if not retry:
                raise
            log(f"Chromium 启动失败，清理 profile 后重试：{exc}")
            self._discard_broken_profile()
            return self._launch_once()

    def _launch_once(self):
        from playwright.sync_api import sync_playwright

        profile_dir = self.profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)
        if self._pw is None:
            self._pw = sync_playwright().start()
        if self.headless():
            log("警告：PING0_HEADLESS=1，无头模式几乎必然被 Cloudflare 判定为机器人，建议设为 0")
        log(f"启动 Chromium（headless={self.headless()}，profile={profile_dir}）")
        launch_kwargs = {
            "user_data_dir": str(profile_dir),
            "headless": self.headless(),
            "chromium_sandbox": False,
        }
        if self.headless():
            # headless=True 默认去找 chromium-headless-shell，镜像构建时那包经常下载失败；
            # 显式指定 channel 就走完整 Chromium 的 new headless，不依赖单独的 shell 包。
            launch_kwargs["channel"] = "chromium"
        context = self._pw.chromium.launch_persistent_context(
            **launch_kwargs,
            proxy={"server": self.mihomo().proxy_server},
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=self.user_agent(),
            args=list(CHROMIUM_ARGS),
        )
        context.set_default_timeout(30_000)
        try:
            context.add_init_script(stealth_script(self.user_agent()))
        except Exception as exc:  # noqa: BLE001  (注入失败不该让整个检测挂掉)
            log(f"注入反自动化脚本失败：{exc}")
        return context

    def _close_context(self) -> None:
        """关闭浏览器上下文但保留 Playwright 实例。

        Chromium 的 socket 池按上下文复用 keep-alive 隧道，切换 mihomo 节点后
        必须丢弃旧上下文，否则新请求仍走旧隧道、出口 IP 不会变。
        """
        if self._context is not None:
            try:
                self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None

    def _close(self) -> None:
        self._close_context()
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None

    # -- 检测流程 ---------------------------------------------------------- #

    def check(
        self,
        node: str,
        result_timeout: int = DEFAULT_RESULT_TIMEOUT_SECONDS,
    ) -> dict[str, object]:
        if not node.strip():
            raise Ping0BrowserError("节点名称不能为空")
        if not self._lock.acquire(blocking=False):
            raise Ping0BrowserBusy("上一次检测还没结束，请稍后重试")
        try:
            return self._check_locked(node, result_timeout)
        finally:
            # 不再有后台等待，检测返回时锁一定要还回去，否则之后每次都报 busy
            self._lock.release()

    def _check_locked(self, node: str, result_timeout: int) -> dict[str, object]:
        mihomo = self.mihomo()
        proxies = mihomo.proxies()
        if node not in proxies:
            raise Ping0BrowserError(f"节点「{node}」不存在")
        plan = selection_plan(proxies, mihomo.rules(), node, mihomo.mode())
        if not plan:
            raise Ping0BrowserError(f"找不到让「{node}」承载检测流量的策略组")

        self._throttle()
        self._close_context()
        self._context = self._launch()
        page = self._context.new_page()
        restored: list[tuple[str, str]] = []
        try:
            baseline_ip = self._safe_text_exit_ip()
            # 丢弃旧上下文，否则 Chromium 复用 keep-alive 隧道，出口仍是切换前的节点
            self._close_context()
            for group, target in plan:
                current = proxies.get(group)
                original = str((current or {}).get("now") or "")
                restored.append((group, original))
                if original != target:
                    mihomo.select(group, target)
            time.sleep(0.4)
            # 切换必须真的生效，否则测的还是默认线路。只比出口 IP 不可靠——默认
            # 出口恰好就是目标节点时两者相同，会被误判成「切不动」；回读策略组
            # 的 now 才能确定。切不动就重试，重试不过直接报错，绝不给含糊的结果。
            for attempt in range(3):
                pending = [
                    (group, target)
                    for group, target in plan
                    if str((mihomo.proxies().get(group) or {}).get("now") or "") != target
                ]
                if not pending:
                    break
                if attempt == 2:
                    detail = "、".join(
                        f"{g} 期望 {t}，实际 {(mihomo.proxies().get(g) or {}).get('now') or '空'}"
                        for g, t in plan
                    )
                    raise Ping0BrowserError(f"切换出口失败：{detail}")
                for group, target in pending:
                    mihomo.select(group, target)
                time.sleep(0.6)
            # 切换后的出口也走文本接口：便宜，不额外触发验证码
            exit_ip = self._safe_text_exit_ip() or baseline_ip
            log(f"检测 {node}：出口 IP {exit_ip}（切换前 {baseline_ip}）")

            lookup_url = PING0_HOME_URL
            attempts = self.auto_retry() + 1
            for attempt in range(attempts):
                self._context = self._launch()
                page = self._context.new_page()
                # 首页会按当前出口渲染数据，切换节点后直接读它，不再查指定 IP
                self._open_home(page)
                state = self._wait_for_result(page, time.time() + max(result_timeout, 1))
                page_ip = str(state.get("ip") or "") or self._page_ip(page)
                if page_ip:
                    exit_ip = page_ip
                if state["ready"]:
                    result = self._build_result(state["html"], exit_ip, lookup_url)
                    log(f"检测完成 {node}：风控 {result.get('risk')}")
                    return result
                if attempt + 1 >= attempts:
                    break
                cooldown = self.retry_cooldown()
                log(f"{node} 被 Cloudflare 挡住，冷却 {cooldown} 秒后重试")
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
                self._close()
                time.sleep(cooldown)
                self._context = self._launch()
                page = self._context.new_page()

            log(f"{node} 持续被 Cloudflare 挡住（出口 {exit_ip}）")
            raise Ping0CaptchaBlocked(exit_ip, lookup_url)
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
            self._restore(restored)
            self._close()

    def _restore(self, restored: list[tuple[str, str]]) -> None:
        for group, original in reversed(restored):
            if not original:
                continue
            try:
                self.mihomo().select(group, original)
            except Ping0BrowserError as exc:
                log(f"恢复策略组「{group}」失败：{exc}")

    def _open_home(self, page) -> None:
        page.goto(PING0_HOME_URL, wait_until="domcontentloaded")

    def _page_ip(self, page) -> str:
        """读取首页里服务端注入的出口 IP。"""
        try:
            return str(page.evaluate("() => window.ip || ''") or "").strip()
        except Exception:  # noqa: BLE001  (页面可能正在跳转)
            return ""

    def _has_captcha(self, page) -> bool:
        try:
            html = page.content()
        except Exception:  # noqa: BLE001  (页面可能正在跳转)
            return False
        return any(marker in html for marker in CAPTCHA_MARKERS)

    def _text_exit_ip(self) -> str:
        """走 mihomo 混合端口读 ipv4.ping0.cc（纯文本，不触发验证码）。

        每次检测都多开一次首页，等于把触发 Cloudflare 挑战的机会翻倍；
        基线出口只为判断「切换有没有生效」，用这个文本接口就够了。
        """
        proxy = self.mihomo().proxy_server
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
        try:
            raw = opener.open(PING0_IP_URL, timeout=15).read()
        except Exception as exc:  # noqa: BLE001
            raise Ping0BrowserError(f"读取出口 IP 失败：{exc}") from exc
        text = raw.decode("utf-8", errors="replace").strip().splitlines()
        ip = text[0].strip() if text else ""
        try:
            ipaddress.ip_address(ip)
        except ValueError as exc:
            raise Ping0BrowserError(f"出口 IP 接口返回了无效内容：{ip[:40]!r}") from exc
        return ip

    def _exit_ip(self, page, required: bool = True) -> str:
        """切换节点前的基线出口 IP。

        优先走文本接口，拿不到时才退回首页；基线只用来判断「出口是否真的变了」。
        """
        try:
            return self._text_exit_ip()
        except Ping0BrowserError as exc:
            log(f"文本接口读出口 IP 失败，改用首页：{exc}")
        if not required:
            return ""
        self._open_home(page)
        for _ in range(10):
            ip = self._page_ip(page)
            if ip:
                return ip
            if self._has_captcha(page):
                break
            time.sleep(0.5)
        if required:
            raise Ping0BrowserError("ping0.cc 首页没有返回出口 IP")
        return ""

    def _wait_for_result(self, page, deadline: float) -> dict[str, object]:
        """轮询首页，直到服务端注入了真实数据。

        空结果页同样带着 riskcurrent（模板默认 0%），所以必须同时确认 window.ip
        有值，否则会把「没拿到数据」误当成「风控 0」。
        Cloudflare 的托管挑战在真实浏览器里多数会自己跑完，等得住就能拿到数据；
        等不到再刷新一次，仍挡着才返回 captcha 让上层换数据源。
        """
        captcha_since: float | None = None
        reloaded = False
        while True:
            try:
                html = page.content()
            except Exception:  # noqa: BLE001  (页面可能正在跳转)
                html = ""
            exit_ip = self._page_ip(page)
            has_captcha = any(marker in html for marker in CAPTCHA_MARKERS)
            has_result = bool(exit_ip) and all(marker in html for marker in RESULT_MARKERS)
            if has_result and not has_captcha:
                return {"ready": True, "html": html, "ip": exit_ip}
            if has_captcha:
                captcha_since = captcha_since or time.time()
                waited = time.time() - captcha_since
                # 托管挑战在真实浏览器里一般自己跑完就放行，只要等得住。
                # 卡够久还没动静就刷新一次：cf_clearance 写进 cookie 之后重新
                # 请求首页，多数情况直接就是结果页了。
                if not reloaded and waited >= CAPTCHA_RELOAD_AFTER_SECONDS:
                    reloaded = True
                    log("Cloudflare 挑战仍在，刷新页面重试")
                    try:
                        page.reload(wait_until="domcontentloaded")
                    except Exception:  # noqa: BLE001  (刷新失败就继续等原页面)
                        pass
                    captcha_since = time.time()
                    continue
                if waited >= CAPTCHA_GRACE_SECONDS:
                    return {"ready": False, "captcha": True, "html": html, "ip": exit_ip}
            else:
                captcha_since = None
            if time.time() >= deadline:
                return {"ready": False, "captcha": has_captcha, "html": html, "ip": exit_ip}
            time.sleep(POLL_INTERVAL_SECONDS)

    def _build_result(self, html: str, ip: str, url: str) -> dict[str, object]:
        try:
            result = parse_ping0_home_result(html.encode("utf-8"))
        except ValueError as exc:
            raise Ping0BrowserError(str(exc)) from exc
        result = dict(result)
        result.setdefault("ip", ip)
        result.setdefault("url", url)
        return result


class Ping0Handler(BaseHTTPRequestHandler):
    browser: Ping0Browser = None  # type: ignore[assignment]

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("请求体不是合法 JSON") from exc
        return payload if isinstance(payload, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/health":
            self._send_json(
                200,
                {
                    "status": "success",
                    "data": {
                        "ok": True,
                        "busy": self.browser.busy(),
                        "headless": self.browser.headless(),
                    },
                },
            )
            return
    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/check":
            self._send_json(404, {"status": "error", "message": "Not Found"})
            return
        try:
            payload = self._read_json()
            node = str(payload.get("proxy") or "").strip()
            result_timeout = int(payload.get("wait") or DEFAULT_RESULT_TIMEOUT_SECONDS)
            data = self.browser.check(node, result_timeout)
        except ValueError as exc:
            self._send_json(400, {"status": "error", "message": str(exc)})
            return
        except Ping0BrowserBusy as exc:
            self._send_json(409, {"status": "busy", "message": str(exc)})
            return
        except Ping0CaptchaBlocked as exc:
            self._send_json(
                200,
                {
                    "status": "captcha",
                    "message": str(exc),
                    "data": {"captcha": True, "ip": exc.ip, "url": exc.url},
                },
            )
            return
        except Ping0BrowserError as exc:
            self._send_json(502, {"status": "error", "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"status": "error", "message": f"浏览器检测失败：{exc}"})
            return
        self._send_json(200, {"status": "success", "data": data})


def serve(port: int) -> int:
    handler = type("BoundPing0Handler", (Ping0Handler,), {"browser": Ping0Browser()})
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    log(f"Ping0 浏览器服务已监听 {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.shutdown()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ping0 浏览器检测服务")
    parser.add_argument("--serve", action="store_true", help="启动 HTTP 服务")
    parser.add_argument("--port", type=int, default=DEFAULT_WORKER_PORT, help="监听端口")
    parser.add_argument("--check", metavar="节点名", help="直接检测单个节点并输出 JSON")
    parser.add_argument("--wait", type=int, default=DEFAULT_RESULT_TIMEOUT_SECONDS, help="等待结果秒数")
    args = parser.parse_args()

    if args.check:
        browser = Ping0Browser()
        try:
            result = browser.check(args.check, args.wait)
        except Ping0CaptchaBlocked as exc:
            print(json.dumps({"status": "captcha", "ip": exc.ip, "url": exc.url}, ensure_ascii=False))
            return 3
        except (Ping0BrowserError, Ping0BrowserBusy) as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps({"status": "success", "data": result}, ensure_ascii=False))
        return 0

    if not args.serve:
        parser.print_help()
        return 1
    return serve(args.port)


if __name__ == "__main__":
    raise SystemExit(main())
