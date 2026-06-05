#!/usr/bin/env python3
"""从 destination_knowledge.json 移除 visit_profiles / visit_profiles_meta。

游览时长改由运行时根据 hotspots + guide_visit_estimate 动态计算。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.paths import PROJECT_ROOT

KNOWLEDGE_PATH = PROJECT_ROOT / "data" / "destination_knowledge.json"


def main() -> None:
    raw = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("invalid catalog")
    stripped_vp = 0
    stripped_meta = 0
    for profile in raw.values():
        if not isinstance(profile, dict):
            continue
        if "visit_profiles" in profile:
            del profile["visit_profiles"]
            stripped_vp += 1
        if "visit_profiles_meta" in profile:
            del profile["visit_profiles_meta"]
            stripped_meta += 1
    KNOWLEDGE_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"stripped visit_profiles from {stripped_vp} destinations, meta from {stripped_meta}")


if __name__ == "__main__":
    main()
