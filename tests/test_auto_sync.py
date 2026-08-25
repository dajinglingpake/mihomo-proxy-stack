import unittest

from scripts.auto_sync import normalize_runtime_config


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


if __name__ == "__main__":
    unittest.main()
