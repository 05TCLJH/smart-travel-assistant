"""专卖店与括号分店类景点过滤测试。"""

from __future__ import annotations

import unittest

from backend.planning.poi_retrieval.classifiers import is_low_value_shopping_branch, is_usable_raw_poi


class ClassifiersRetailTests(unittest.TestCase):
    def test_blocks_specialty_store_branch(self) -> None:
        row = {"name": "长城雪茄(宽窄巷子店)", "type": "购物服务;专卖店;专营店"}
        self.assertFalse(is_usable_raw_poi(row))

    def test_shopping_branch_detection(self) -> None:
        self.assertTrue(is_low_value_shopping_branch("某品牌", "购物服务;专卖店;专营店"))

    def test_allows_landmark_street_names(self) -> None:
        row = {"name": "宽窄巷子景区", "type": "风景名胜;风景名胜;风景名胜"}
        self.assertTrue(is_usable_raw_poi(row))


if __name__ == "__main__":
    unittest.main()
