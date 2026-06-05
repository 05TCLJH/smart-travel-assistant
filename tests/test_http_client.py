"""网络客户端错误文案与重试判定测试。"""

from __future__ import annotations

import unittest

from backend.core.http_client import _is_retriable, format_http_error


class HttpClientTests(unittest.TestCase):
    def test_ssl_eof_is_retriable(self) -> None:
        exc = OSError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")
        self.assertTrue(_is_retriable(exc))

    def test_friendly_ssl_eof_message(self) -> None:
        msg = format_http_error(
            OSError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"),
            service="DashScope 视觉模型",
        )
        self.assertIn("DashScope", msg)
        self.assertIn("4MB", msg)

    def test_non_retriable_http_status(self) -> None:
        self.assertFalse(_is_retriable(ValueError("bad json")))


if __name__ == "__main__":
    unittest.main()
