import json
import os
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from scripts.auto_sync import (
    DEFAULT_PING0_CACHE_TTL_SECONDS,
    Ping0BrowserBusy,
    Ping0CaptchaBlocked,
    parse_ping0_home_result,
    parse_ping0_result,
    ping0_cache_clear,
    ping0_cache_lookup,
    ping0_cache_store,
    probe_ip_quality_fallback,
    probe_ping0_direct,
    probe_ping0_via_proxy,
    probe_ping0_with_browser,
)
from scripts.ping0_browser import Ping0Browser, final_match_target, selection_plan

RESULT_PAGE = """
<script>
window.ip = '203.10.98.186'; window.loc = `日本 东京都 东京`; window.rdns = '';
</script>
<div class="line line-asn">
  <div class="name"><span>ASN</span></div>
  <div class="content">AS2497</div>
</div>
<div class="line line-risk">
  <div class="content"><div class="riskitem riskcurrent"><span class="value">16%</span><span class="lab"> 纯净</span></div></div>
</div>
<div class="line line-nativeip">
  <div class="name">原生 IP</div>
  <div class="content"><span class="label orange">原生 IP</span></div>
</div>
"""

CAPTCHA_PAGE = '<div class="cf-turnstile">请完成验证</div>'


class SelectionPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.proxies = {
            "GLOBAL": {"type": "Selector", "now": "一分机场", "all": ["DIRECT", "一分机场"]},
            "一分机场": {
                "type": "Selector",
                "now": "美国故障转移",
                "all": ["美国故障转移", "自动选择", "🇯🇵日本专线-0.1倍率"],
            },
            "美国故障转移": {"type": "Fallback", "now": "🇯🇵日本专线-0.1倍率", "all": ["🇯🇵日本专线-0.1倍率"]},
            "🇯🇵日本专线-0.1倍率": {"type": "Shadowsocks", "all": []},
        }
        self.rules = [{"type": "Match", "proxy": "一分机场"}]

    def test_uses_final_match_group_in_rule_mode(self) -> None:
        self.assertEqual(
            selection_plan(self.proxies, self.rules, "🇯🇵日本专线-0.1倍率", mode="rule"),
            [("一分机场", "🇯🇵日本专线-0.1倍率")],
        )

    def test_walks_nested_selectors_in_global_mode(self) -> None:
        self.assertEqual(
            selection_plan(self.proxies, self.rules, "🇯🇵日本专线-0.1倍率", mode="global"),
            [("GLOBAL", "一分机场"), ("一分机场", "🇯🇵日本专线-0.1倍率")],
        )

    def test_returns_empty_plan_for_unknown_node(self) -> None:
        self.assertEqual(selection_plan(self.proxies, self.rules, "不存在的节点", mode="rule"), [])

    def test_reads_final_match_target(self) -> None:
        self.assertEqual(final_match_target(self.rules), "一分机场")
        self.assertIsNone(final_match_target([]))


class Ping0ResultFallbackTest(unittest.TestCase):
    def test_falls_back_to_native_label_for_ip_type(self) -> None:
        body = """
        <div class="line line-risk">
          <div class="content"><div class="riskitem riskcurrent"><span class="value">0%</span><span class="lab"> 极度纯净</span></div></div>
        </div>
        <div class="line line-nativeip">
          <div class="name">原生 IP</div>
          <div class="content"><span class="label orange">广播 IP</span></div>
        </div>
        """.encode("utf-8")

        result = parse_ping0_result(body, "203.10.98.186")

        self.assertEqual(result["risk"], 0)
        self.assertEqual(result["ipType"], "广播 IP")
        self.assertFalse(result["native"])


class Ping0HomeResultTest(unittest.TestCase):
    """首页按出口 IP 渲染真实数据；指定 IP 查询页对代理出口只返回空壳。"""

    HOME_PAGE = """
    <script>
    window.ip = '2605:8340:0:5c::3' window.loc = `美国 亚利桑那州 凤凰城` window.rdns = ''
    </script>
    <div class="line line-risk">
      <div class="name"><span>风控值</span></div>
      <div class="content"><div class="riskbar">
        <div class="riskitem riskcurrent" title="25-40 中性"><span class="value">31%</span><span class="lab"> 中性</span></div>
      </div></div>
    </div>
    <div class="line asn">
      <div class="name"><span>ASN</span></div>
      <div class="content">AS14315</div>
    </div>
    <div class="line asnname">
      <div class="name"><span>ASN 所有者</span></div>
      <div class="content">IDC 1GSERVERS, LLC</div>
    </div>
    <div class="line line-iptype">
      <div class="name"><span>IP 类型</span></div>
      <div class="content">IDC机房 IP <a href="#">为什么双ISP还会显示"IDC机房IP"?</a></div>
    </div>
    <div class="line line-nativeip">
      <div class="name"><span>原生 IP</span></div>
      <div class="content"><span class="label">原生 IP</span></div>
    </div>
    <div class="line line-usecount">
      <div class="name"><span>共享人数</span></div>
      <div class="content">1000 - 10000 (高危)</div>
    </div>
    """.encode("utf-8")

    EMPTY_PAGE = """
    <script>window.ip = '' window.loc = `无法对该域名进行解析`</script>
    <div class="line line-risk">
      <div class="content"><div class="riskitem riskcurrent" title="0-15 极度纯净">
        <span class="value">0%</span><span class="lab"> 极度纯净</span></div></div>
    </div>
    """.encode("utf-8")

    def test_reads_real_risk_not_template_default(self) -> None:
        result = parse_ping0_home_result(self.HOME_PAGE)

        self.assertEqual(result["risk"], 31)
        self.assertEqual(result["riskLabel"], "中性")
        self.assertEqual(result["ip"], "2605:8340:0:5c::3")

    def test_reads_detail_fields_for_hover(self) -> None:
        result = parse_ping0_home_result(self.HOME_PAGE)

        self.assertEqual(result["location"], "美国 亚利桑那州 凤凰城")
        self.assertEqual(result["asn"], "AS14315")
        self.assertEqual(result["asnName"], "IDC 1GSERVERS, LLC")
        self.assertEqual(result["ipType"], "IDC机房 IP")
        self.assertTrue(result["native"])
        self.assertEqual(result["shared"], "1000 - 10000 (高危)")

    def test_rejects_empty_page_instead_of_reporting_zero_risk(self) -> None:
        with self.assertRaises(ValueError):
            parse_ping0_home_result(self.EMPTY_PAGE)


class Ping0FallbackSourceTest(unittest.TestCase):
    """ping0 被 Cloudflare 挡住时改用备用数据源，而不是让人去点验证码。"""

    IP_API_PAYLOAD = json.dumps(
        {
            "status": "success",
            "query": "142.202.242.178",
            "country": "United States",
            "regionName": "Arizona",
            "city": "Phoenix",
            "as": "AS14315 1GSERVERS, LLC",
            "org": "1GSERVERS, LLC",
            "hosting": True,
            "proxy": False,
        }
    ).encode("utf-8")

    def _probe(self, payload: bytes, ip: str = "142.202.242.178"):
        with mock.patch("scripts.auto_sync._http_get_via_mihomo_port", return_value=payload):
            return probe_ip_quality_fallback(ip)

    def test_marks_hosting_ip_as_degraded_without_risk(self) -> None:
        result = self._probe(self.IP_API_PAYLOAD)
        self.assertTrue(result["degraded"])
        self.assertTrue(result["hosting"])
        self.assertFalse(result["native"])
        self.assertEqual(result["ipType"], "机房/数据中心 IP")
        self.assertEqual(result["asn"], "AS14315")
        self.assertIn("Phoenix", result["location"])
        # 没有风控值，前端靠 degraded 区分；放个假的 risk 反而会被当成真实结果
        self.assertNotIn("risk", result)

    def test_residential_ip_is_native(self) -> None:
        payload = json.dumps({"status": "success", "query": "1.2.3.4", "hosting": False, "proxy": False}).encode()
        result = self._probe(payload, "1.2.3.4")
        self.assertTrue(result["native"])
        self.assertEqual(result["ipType"], "住宅/移动 IP")

    def test_rejects_failure_payload(self) -> None:
        payload = json.dumps({"status": "fail", "message": "invalid query"}).encode()
        with self.assertRaises(ValueError):
            self._probe(payload)

    def test_rejects_empty_ip(self) -> None:
        with self.assertRaises(ValueError):
            probe_ip_quality_fallback("")


class Ping0DirectFirstTest(unittest.TestCase):
    """直连抓取优先：它不带浏览器指纹，实测比浏览器更容易拿到数据，也快得多。"""

    def setUp(self) -> None:
        self.patches = [
            mock.patch("scripts.auto_sync.ping0_cache_store"),
            mock.patch("scripts.auto_sync.ping0_cache_lookup", return_value=None),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()

    def test_direct_hit_never_starts_browser(self) -> None:
        with mock.patch(
            "scripts.auto_sync.probe_ping0_direct", return_value={"ip": "1.2.3.4", "risk": 31}
        ) as direct, mock.patch("scripts.auto_sync.probe_ping0_with_browser") as browser:
            result = probe_ping0_via_proxy("节点", fresh=True)
        direct.assert_called_once()
        browser.assert_not_called()
        self.assertEqual(result["risk"], 31)

    def test_browser_used_when_direct_blocked(self) -> None:
        with mock.patch(
            "scripts.auto_sync.probe_ping0_direct",
            side_effect=Ping0CaptchaBlocked("1.2.3.4"),
        ), mock.patch(
            "scripts.auto_sync.probe_ping0_with_browser", return_value={"ip": "1.2.3.4", "risk": 42}
        ) as browser:
            result = probe_ping0_via_proxy("节点", fresh=True)
        browser.assert_called_once()
        self.assertEqual(result["risk"], 42)

    def test_degrades_when_both_blocked(self) -> None:
        fallback = {"ip": "1.2.3.4", "degraded": True, "ipType": "机房/数据中心 IP"}
        with mock.patch(
            "scripts.auto_sync.probe_ping0_direct",
            side_effect=Ping0CaptchaBlocked("1.2.3.4"),
        ), mock.patch(
            "scripts.auto_sync.probe_ping0_with_browser", side_effect=Ping0CaptchaBlocked("1.2.3.4")
        ), mock.patch(
            "scripts.auto_sync.probe_ip_quality_fallback", return_value=fallback
        ) as source:
            result = probe_ping0_via_proxy("节点", fresh=True)
        source.assert_called_once()
        self.assertTrue(result["degraded"])
        self.assertEqual(result["ipType"], "机房/数据中心 IP")


class Ping0BrowserBusyTest(unittest.TestCase):
    """浏览器正被上一次检测占着时必须明确报 busy。

    不能混进「服务不可用」里去回退直连抓取：那会临时把出口策略组切走，
    把正在进行的检测一起搞乱。
    """

    def test_raises_busy_on_busy_status(self) -> None:
        body = {"status": "busy", "message": "上一次检测还没结束"}
        with mock.patch("scripts.auto_sync.ping0_browser_json", return_value=body):
            with self.assertRaises(Ping0BrowserBusy):
                probe_ping0_with_browser("http://127.0.0.1:3021", "A")

    def test_reads_busy_payload_from_http_409(self) -> None:
        error = urllib.error.HTTPError("http://127.0.0.1:3021/check", 409, "Conflict", {}, None)
        error.read = lambda: json.dumps({"status": "busy", "message": "占用中"}).encode("utf-8")
        with mock.patch("scripts.auto_sync.http_request", side_effect=error):
            with self.assertRaises(Ping0BrowserBusy):
                probe_ping0_with_browser("http://127.0.0.1:3021", "A")


class FakePage:
    """前几次轮询返回验证码页，置位 solved 后返回真实结构的结果页。"""

    def __init__(self) -> None:
        self.solved = False
        self.closed = False

    def content(self) -> str:
        return RESULT_PAGE if self.solved else CAPTCHA_PAGE

    def evaluate(self, script: str, *args) -> str:
        # 就绪判定会读 window.ip：空字符串代表页面还没拿到出口数据
        return "203.10.98.186" if "window.ip" in script and self.solved else ""

    def close(self) -> None:
        self.closed = True


class Ping0ResultCacheTest(unittest.TestCase):
    """同一个出口 IP 的检测结果应当复用，避免重复开浏览器、重复触发验证码。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_file = Path(self.tmp.name) / "cache.json"
        self.old_path = os.environ.get("PING0_CACHE_PATH")
        self.old_ttl = os.environ.get("PING0_CACHE_TTL_SECONDS")
        os.environ["PING0_CACHE_PATH"] = str(self.cache_file)
        os.environ.pop("PING0_CACHE_TTL_SECONDS", None)
        self.result = {"ip": "203.10.98.186", "risk": 42, "riskLabel": "轻微风险", "native": False}

    def tearDown(self) -> None:
        for key, value in (("PING0_CACHE_PATH", self.old_path), ("PING0_CACHE_TTL_SECONDS", self.old_ttl)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_lookup_hit_marks_cached(self) -> None:
        ping0_cache_store(self.result)
        cached = ping0_cache_lookup("203.10.98.186")
        self.assertIsNotNone(cached)
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["risk"], 42)
        self.assertEqual(cached["ip"], "203.10.98.186")

    def test_alias_ip_indexes_same_result(self) -> None:
        # 探测走的是 ipv4.ping0.cc，首页渲染出来的可能是 v6，两个都要能命中
        ping0_cache_store(self.result, alias_ip="2605:8340::3")
        self.assertEqual(ping0_cache_lookup("2605:8340::3")["risk"], 42)
        self.assertEqual(ping0_cache_lookup("203.10.98.186")["risk"], 42)

    def test_expired_entry_is_ignored(self) -> None:
        ping0_cache_store(self.result)
        data = json.loads(self.cache_file.read_text(encoding="utf-8"))
        for entry in data["entries"].values():
            entry["ts"] -= DEFAULT_PING0_CACHE_TTL_SECONDS + 60
        self.cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertIsNone(ping0_cache_lookup("203.10.98.186"))

    def test_ttl_zero_disables_cache(self) -> None:
        os.environ["PING0_CACHE_TTL_SECONDS"] = "0"
        ping0_cache_store(self.result)
        self.assertIsNone(ping0_cache_lookup("203.10.98.186"))

    def test_unknown_ip_misses(self) -> None:
        ping0_cache_store(self.result)
        self.assertIsNone(ping0_cache_lookup("1.2.3.4"))

    def test_clear_removes_entries(self) -> None:
        ping0_cache_store(self.result)
        self.assertGreater(ping0_cache_clear(), 0)
        self.assertIsNone(ping0_cache_lookup("203.10.98.186"))

    def test_result_without_ip_is_not_cached(self) -> None:
        ping0_cache_store({"risk": 10})
        self.assertFalse(self.cache_file.exists())
        self.assertIsNone(ping0_cache_lookup(""))

CAPTCHA_PAGE = '<!doctype html><div id="captcha-element" class="cf-turnstile"></div>'


class Ping0DirectRetryTest(unittest.TestCase):
    """被 Cloudflare 挡住时自动冷却重试，重试成功就不该降级。"""

    def setUp(self) -> None:
        self.env = mock.patch.dict(
            os.environ,
            {"PING0_AUTO_RETRY": "1", "PING0_RETRY_COOLDOWN_SECONDS": "0", "PING0_MIN_INTERVAL_SECONDS": "0"},
        )
        self.env.start()
        self.patches = [
            mock.patch("scripts.auto_sync.route_through_node"),
            mock.patch("scripts.auto_sync._ping0_fetch_exit_ip", return_value="203.10.98.186"),
            mock.patch("scripts.auto_sync.time.sleep"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        self.env.stop()

    def test_retries_after_captcha_and_returns_real_risk(self) -> None:
        with mock.patch(
            "scripts.auto_sync.http_get_via_mihomo_proxy",
            side_effect=[CAPTCHA_PAGE.encode("utf-8"), RESULT_PAGE.encode("utf-8")],
        ) as fetch:
            result = probe_ping0_direct("节点")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["risk"], 16)

    def test_gives_up_after_retries(self) -> None:
        with mock.patch(
            "scripts.auto_sync.http_get_via_mihomo_proxy", return_value=CAPTCHA_PAGE.encode("utf-8")
        ):
            with self.assertRaises(Ping0CaptchaBlocked):
                probe_ping0_direct("节点")

    def test_plain_ip_response_is_treated_as_blocked(self) -> None:
        with mock.patch(
            "scripts.auto_sync.http_get_via_mihomo_proxy", return_value=b"203.10.98.186\n"
        ):
            with self.assertRaises(Ping0CaptchaBlocked) as raised:
                probe_ping0_direct("节点")
        self.assertEqual(raised.exception.ip, "203.10.98.186")


class Ping0CacheReuseTest(unittest.TestCase):
    """缓存按出口 IP 索引，命中就是那个出口的结果，不该再带含糊的 verified 标记。"""

    def setUp(self) -> None:
        self.patches = [
            mock.patch("scripts.auto_sync.route_through_node"),
            mock.patch("scripts.auto_sync._ping0_fetch_exit_ip", return_value="203.10.98.186"),
            mock.patch("scripts.auto_sync.ping0_cache_store"),
            mock.patch(
                "scripts.auto_sync.ping0_cache_lookup",
                return_value={"ip": "203.10.98.186", "risk": 16, "cached": True, "cachedAge": 120},
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()

    def test_cached_hit_carries_no_verified_flag(self) -> None:
        result = probe_ping0_via_proxy("节点")
        self.assertEqual(result["risk"], 16)
        self.assertNotIn("verified", result)


if __name__ == "__main__":
    unittest.main()
