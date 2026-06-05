"""接口密钥格式规范测试。"""

from __future__ import annotations

import unittest

from backend.core.api_key_specs import (
    BAILIAN_KEY_SPEC,
    AMAP_KEY_SPEC,
    classify_service_failure,
    validate_api_key,
    validate_runtime_key_updates,
)


class ApiKeySpecsTests(unittest.TestCase):
    def test_amap_valid(self) -> None:
        self.assertIsNone(validate_api_key(AMAP_KEY_SPEC, "0e0de684f80293f32263b9faa6976491"))

    def test_amap_rejects_short(self) -> None:
        issue = validate_api_key(AMAP_KEY_SPEC, "abc")
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "invalid_format")
        self.assertEqual(issue.message, "高德地图 Key 格式不正确，请检查是否包含空格、引号或复制不完整。")

    def test_bailian_valid(self) -> None:
        self.assertIsNone(validate_api_key(BAILIAN_KEY_SPEC, "sk-4e6a45572798496dae2c4cc88e6e72f5"))

    def test_bailian_rejects_without_sk(self) -> None:
        issue = validate_api_key(BAILIAN_KEY_SPEC, "sk-4e6a45572798496dae2c4cc88e6e72f")  # 31 位十六进制字符
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "invalid_format")
        self.assertEqual(issue.message, "DashScope API Key 格式不正确，请检查是否以 sk- 开头，以及后续字符长度和内容是否正确。")

    def test_amap_rejects_quoted_value(self) -> None:
        issue = validate_api_key(AMAP_KEY_SPEC, '"0e0de684f80293f32263b9faa6976491"')
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "invalid_format")

    def test_runtime_updates_partial(self) -> None:
        issues = validate_runtime_key_updates(amap_api_key="not-a-valid-key")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].field, "amap_api_key")

    def test_classify_amap_quota(self) -> None:
        info = classify_service_failure("高德 MCP 调用失败：日调用量已超限")
        self.assertEqual(info["code"], "amap_quota")

    def test_classify_bailian_auth(self) -> None:
        info = classify_service_failure("DashScope API key invalid")
        self.assertEqual(info["code"], "bailian_key_invalid")

    def test_classify_unknown_as_unverifiable(self) -> None:
        info = classify_service_failure("something unexpected happened")
        self.assertEqual(info["code"], "unknown")
        self.assertIn("无法验证可用性", info["title"])
        self.assertIn("无法验证可用性", info["message"])


if __name__ == "__main__":
    unittest.main()
