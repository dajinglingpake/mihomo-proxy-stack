import unittest

from scripts import auto_sync
from scripts.auto_sync import normalize_runtime_config, parse_ping0_result, probe_ping0_ip_page


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
