"""请求级 Key 上下文测试。"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.core.runtime_context import runtime_keys_scope
from backend.core.settings import amap_key, bailian_key
from backend.mcp.amap_client import AmapMcpClient


class RuntimeContextTests(unittest.TestCase):
    def test_runtime_scope_overrides_env_keys_temporarily(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AMAP_API_KEY": "env-amap-key",
                "ALIYUN_BAILIAN_API_KEY": "env-bailian-key",
            },
            clear=True,
        ):
            self.assertEqual(amap_key(), "env-amap-key")
            self.assertEqual(bailian_key(), "env-bailian-key")
            with runtime_keys_scope(amap_api_key="req-amap-key", bailian_api_key="req-bailian-key"):
                self.assertEqual(amap_key(), "req-amap-key")
                self.assertEqual(bailian_key(), "req-bailian-key")
            self.assertEqual(amap_key(), "env-amap-key")
            self.assertEqual(bailian_key(), "env-bailian-key")

    def test_amap_client_server_url_uses_request_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = AmapMcpClient()
            self.assertFalse(client.enabled)
            with runtime_keys_scope(amap_api_key="0123456789abcdef0123456789abcdef"):
                self.assertTrue(client.enabled)
                self.assertIn("key=0123456789abcdef0123456789abcdef", client.server_url)


if __name__ == "__main__":
    unittest.main()
