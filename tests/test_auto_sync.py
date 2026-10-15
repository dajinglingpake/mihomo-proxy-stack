import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import auto_sync
from scripts.auto_sync import normalize_runtime_config, parse_ping0_result, probe_ping0_ip_page


class DeviceAccessInfoTest(unittest.TestCase):
    def test_discovers_lan_address_and_configured_proxy_port(self) -> None:
        with patch.object(auto_sync.socket, "socket") as factory, patch.object(
            auto_sync, "load_stack_env", return_value={"MIHOMO_MIXED_PORT": "17890", "CONTROLLER_SECRET": "private"}
        ):
            probe = factory.return_value.__enter__.return_value
            probe.getsockname.return_value = ("192.168.1.2", 40000)
            self.assertEqual(auto_sync.get_device_access_info(), {
                "suggestedHost": "192.168.1.2",
                "proxyPort": "17890",
                "pacPath": "/manage-api/proxy.pac",
            })
            probe.send.assert_not_called()
            probe.sendto.assert_not_called()

    def test_missing_route_still_allows_manual_address_entry(self) -> None:
        with patch.object(auto_sync.socket, "socket", side_effect=OSError("No route")), patch.object(
            auto_sync, "load_stack_env", return_value={}
        ):
            info = auto_sync.get_device_access_info()
            self.assertEqual(info["suggestedHost"], "")
            self.assertEqual(info["proxyPort"], "7890")

    def test_does_not_suggest_loopback_address_to_phone(self) -> None:
        with patch.object(auto_sync.socket, "socket") as factory, patch.object(auto_sync, "load_stack_env", return_value={}):
            factory.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 40000)
            self.assertEqual(auto_sync.get_device_access_info()["suggestedHost"], "")


class DirectRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.rules_file = Path(directory.name) / "direct-rules.list"
        self.rules_file.write_text("DOMAIN-SUFFIX,fqnovel.com\n", encoding="utf-8")
        patcher = patch.object(auto_sync, "DIRECT_RULES_FILE", self.rules_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_direct_rules_precede_subscription_rules_and_preserve_other_sections(self) -> None:
        for indent in ("", "  ", "    "):
            with self.subTest(indent=indent):
                original_rules = f"{indent}- DOMAIN-SUFFIX,fqnovel.com,Proxy\n{indent}- MATCH,Proxy\n"
                text = "mode: rule\nrules: # subscription\n" + original_rules + "profile:\n  store-selected: true\n"
                result = auto_sync.apply_direct_rules_to_text(text)
                self.assertIn(f"{indent}- DOMAIN-SUFFIX,fqnovel.com,DIRECT\n", result)
                self.assertLess(result.index("fqnovel.com,DIRECT"), result.index("fqnovel.com,Proxy"))
                self.assertTrue(result.startswith("mode: rule\nrules: # subscription\n"))
                self.assertTrue(result.endswith(original_rules + "profile:\n  store-selected: true\n"))

    def test_cached_snapshot_replaces_old_rules_without_duplicates(self) -> None:
        text = "rules:\n  - MATCH,Proxy\n"
        first = auto_sync.apply_direct_rules_to_text(text)
        self.assertEqual(auto_sync.apply_direct_rules_to_text(first), first)
        self.rules_file.write_text("DOMAIN-SUFFIX,hongguoduanju.com\n", encoding="utf-8")
        updated = auto_sync.apply_direct_rules_to_text(first)
        self.assertNotIn("fqnovel.com", updated)
        self.assertEqual(updated.count("hongguoduanju.com,DIRECT"), 1)
        self.rules_file.write_text("# disabled\n", encoding="utf-8")
        self.assertEqual(auto_sync.apply_direct_rules_to_text(updated), text)

    def test_empty_rules_list_is_expanded(self) -> None:
        result = auto_sync.apply_direct_rules_to_text("rules: []\nprofile:\n  store-selected: true\n")
        self.assertNotIn("[]", result)
        self.assertIn("  - DOMAIN-SUFFIX,fqnovel.com,DIRECT\n", result)
        self.assertTrue(result.endswith("profile:\n  store-selected: true\n"))

    def test_subscription_patch_includes_direct_rules(self) -> None:
        result = auto_sync.patch_config("mode: rule\nrules:\n  - MATCH,Proxy\n", {})
        self.assertIn("mode: rule\n", result)
        self.assertLess(result.index("fqnovel.com,DIRECT"), result.index("MATCH,Proxy"))

    def test_invalid_rule_is_rejected_before_applying_config(self) -> None:
        self.rules_file.write_text("MATCH,Proxy\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid direct rule"):
            auto_sync.apply_direct_rules_to_text("rules:\n  - MATCH,Proxy\n")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required to evaluate PAC JavaScript")
    def test_pac_routes_listed_domains_without_proxying_from_the_phone(self) -> None:
        self.rules_file.write_text("DOMAIN-SUFFIX,fqnovel.com\nDOMAIN,p3-novel.byteimg.com\n", encoding="utf-8")
        pac = auto_sync.build_proxy_pac("192.168.1.2", "7890")
        checks = {
            "fqnovel.com": "DIRECT",
            "api5-normal-lf.fqnovel.com": "DIRECT",
            "API5-NORMAL-LF.FQNOVEL.COM.": "DIRECT",
            "p3-novel.byteimg.com": "DIRECT",
            "192.168.1.2": "DIRECT",
            "google.com": "PROXY 192.168.1.2:7890",
            "fakefqnovel.com": "PROXY 192.168.1.2:7890",
            "fqnovel.com.example.org": "PROXY 192.168.1.2:7890",
            "other.byteimg.com": "PROXY 192.168.1.2:7890",
            "other.p3-novel.byteimg.com": "PROXY 192.168.1.2:7890",
        }
        script = (
            "const vm = require('node:vm'); const assert = require('node:assert/strict');\n"
            "const context = vm.createContext({isPlainHostName: h => !h.includes('.'), "
            "dnsDomainIs: (h, d) => h.endsWith(d)});\n"
            f"vm.runInContext({json.dumps(pac)}, context);\n"
            f"for (const [host, expected] of Object.entries({json.dumps(checks)})) {{\n"
            "  assert.equal(context.FindProxyForURL('https://' + host + '/', host), expected, host);\n"
            "}\n"
        )
        result = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pac_rejects_invalid_proxy_addresses(self) -> None:
        for host, port in (("", "7890"), ("host; DIRECT", "7890"), ("proxy.local", "0"), ("proxy.local", "65536")):
            with self.subTest(host=host, port=port), self.assertRaises(ValueError):
                auto_sync.build_proxy_pac(host, port)


class NormalizeRuntimeConfigTest(unittest.TestCase):
    def test_ignores_subscription_display_value_changes(self) -> None:
        before = """proxies:
    - { name: '剩余流量：923.45 GB', server: example.com, port: 443 }
proxy-groups:
    - { name: selector, type: select, proxies: ['剩余流量：923.45 GB', 套餐到期：长期有效] }
""".encode()
        after = """proxies:
    - { name: '剩余流量：923.44 GB', server: example.com, port: 443 }
proxy-groups:
    - { name: selector, type: select, proxies: ['剩余流量：923.44 GB', 套餐到期：2026-09-01] }
""".encode()

        self.assertEqual(normalize_runtime_config(before), normalize_runtime_config(after))

    def test_preserves_runtime_node_changes(self) -> None:
        before = """proxies:
    - { name: '剩余流量：923.45 GB', server: old.example.com, port: 443 }
""".encode()
        after = """proxies:
    - { name: '剩余流量：923.44 GB', server: new.example.com, port: 443 }
""".encode()

        self.assertNotEqual(normalize_runtime_config(before), normalize_runtime_config(after))


class Ping0ResultTest(unittest.TestCase):
    def test_parses_risk_and_ip_labels(self) -> None:
        body = """
        <div class="line line-iptype">
          <div class="name">IP &#31867;&#22411;</div>
          <div class="content"><span class="label orange">IDC&#26426;&#25151; IP</span></div>
        </div>
        <div class="line line-risk">
          <div class="content"><div class="riskitem riskcurrent"><span class="value">16%</span><span class="lab"> &#32431;&#20928;</span></div></div>
        </div>
        <div class="line line-nativeip">
          <div class="name">&#21407;&#29983; IP</div>
          <div class="content"><span class="label"> &#21407;&#29983; IP</span></div>
        </div>
        """.encode("utf-8")

        result = parse_ping0_result(body, "1.2.3.4")

        self.assertEqual(result["ip"], "1.2.3.4")
        self.assertEqual(result["risk"], 16)
        self.assertEqual(result["riskLabel"], "纯净")
        self.assertEqual(result["ipType"], "IDC机房 IP")
        self.assertTrue(result["native"])

    def test_rejects_captcha_page(self) -> None:
        with self.assertRaisesRegex(ValueError, "需要验证码"):
            parse_ping0_result(b'<div id="captcha-element"></div>', "1.2.3.4")




class Ping0IpPageLookupTest(unittest.TestCase):
    """目标出口被挡时借别的线路查 ping0 的「指定 IP」结果页。

    这个 URL 一旦在末尾多写一条斜杠，ping0 会直接打回 Cloudflare 挑战页
    （1357 字节的空壳），页面看起来「能打开」却永远读不到风控值。
    """

    def _stub(self, page: bytes):
        requested = {}

        def fake_get(url: str, timeout: int = 20) -> bytes:
            requested["url"] = url
            return page

        self.addCleanup(setattr, auto_sync, "_http_get_via_mihomo_port", auto_sync._http_get_via_mihomo_port)
        self.addCleanup(setattr, auto_sync, "_ping0_throttle", auto_sync._ping0_throttle)
        auto_sync._http_get_via_mihomo_port = fake_get
        auto_sync._ping0_throttle = lambda: None
        return requested

    IP_PAGE = """
    <script>window.ip = '1.2.3.4' window.loc = `美国 亚利桑那州 凤凰城`</script>
    <div class="line line-risk">
      <div class="name"><span>风控值</span></div>
      <div class="content"><div class="riskbar">
        <div class="riskitem riskcurrent" title="25-40 中性"><span class="value">31%</span><span class="lab"> 中性</span></div>
      </div></div>
    </div>
    """.encode("utf-8")

    def test_requests_url_without_trailing_slash(self) -> None:
        requested = self._stub(self.IP_PAGE)

        result = probe_ping0_ip_page("1.2.3.4")

        self.assertEqual(requested["url"], "https://ping0.cc/ip/1.2.3.4")
        self.assertEqual(result["url"], "https://ping0.cc/ip/1.2.3.4")
        self.assertEqual(result["risk"], 31)

    def test_rejects_page_rendered_for_another_ip(self) -> None:
        self._stub(self.IP_PAGE)

        with self.assertRaisesRegex(ValueError, "不是要查的"):
            probe_ping0_ip_page("9.9.9.9")

    def test_requires_ip(self) -> None:
        with self.assertRaisesRegex(ValueError, "没有出口 IP"):
            probe_ping0_ip_page("")
