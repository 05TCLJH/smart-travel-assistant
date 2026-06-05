#!/usr/bin/env python3
"""把各目的地 hotspots 种子同步进 curated_visit_profiles.json（仅补缺，不覆盖已有）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.paths import PROJECT_ROOT
from backend.knowledge.destination_catalog import _load_catalog, iter_all_hotspot_names
from backend.knowledge.guide_visit_estimate import guide_profile_for_knowledge
from backend.knowledge.visit_profiles import hotspot_entry_name

CURATED_PATH = PROJECT_ROOT / "data" / "curated_visit_profiles.json"
KNOWLEDGE_PATH = PROJECT_ROOT / "data" / "destination_knowledge.json"


def main() -> None:
    curated: dict = {}
    if CURATED_PATH.exists():
        raw = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            curated = {k: v for k, v in raw.items() if not str(k).startswith("_")}

    _load_catalog.cache_clear()
    catalog = _load_catalog()
    added = 0
    for dest, profile in catalog.items():
        if not isinstance(profile, dict):
            continue
        region = str(profile.get("region_type", "city") or "city")
        for name in iter_all_hotspot_names(profile):
            if name in curated:
                continue
            gp = guide_profile_for_knowledge(name, region_type=region)
            curated[name] = {
                "typical_visit_hours": gp["typical_visit_hours"],
                "activity_tier": gp["activity_tier"],
            }
            added += 1

    out = {"_comment": "名景点与全库热点种子；运行时优先于纯规则兜底"}
    out.update(dict(sorted(curated.items(), key=lambda x: x[0])))
    CURATED_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"curated_visit_profiles: total={len(curated)} newly_added={added}")


if __name__ == "__main__":
    main()
