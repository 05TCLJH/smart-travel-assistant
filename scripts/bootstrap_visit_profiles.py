#!/usr/bin/env python3
"""已废弃：visit_profiles 不再写入 destination_knowledge.json。

请使用：
  python scripts/strip_visit_profiles_from_knowledge.py   # 清理 JSON 中的旧时长字段
时长由运行时 visit_profiles_for_destination() 根据 hotspots 动态生成。
"""

from __future__ import annotations

import sys

if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
