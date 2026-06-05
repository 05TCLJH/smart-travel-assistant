"""将 destination_knowledge 中所有 hotspot 种子补全到 curated_visit_profiles.json。"""
from __future__ import annotations

import json
from pathlib import Path

from backend.knowledge.destination_catalog import (
    _load_catalog,
    _load_curated_visit_seeds,
    get_curated_profile,
    iter_all_hotspot_names,
)
from backend.knowledge.guide_visit_estimate import guide_profile_for_knowledge

ROOT = Path(__file__).resolve().parents[1]
CURATED_PATH = ROOT / "data" / "curated_visit_profiles.json"


def main() -> None:
    catalog = _load_catalog()
    curated = _load_curated_visit_seeds()
    added = 0
    updated = 0

    seeds: set[str] = set()
    for dest, profile in catalog.items():
        for name in iter_all_hotspot_names(profile):
            if name:
                seeds.add(name)

    for seed in sorted(seeds):
        dest_key = next(
            (d for d in catalog if seed in iter_all_hotspot_names(catalog[d])),
            "",
        )
        region_type = "city"
        if dest_key:
            p = get_curated_profile(dest_key)
            if p:
                region_type = str(p.get("region_type", "city") or "city")

        guide = guide_profile_for_knowledge(seed, region_type=region_type)
        entry = {
            "typical_visit_hours": guide["typical_visit_hours"],
            "activity_tier": guide["activity_tier"],
        }

        if seed not in curated:
            curated[seed] = entry
            added += 1
        else:
            old = curated[seed]
            try:
                old_h = float(old.get("typical_visit_hours", 0) or 0)
                new_h = float(entry["typical_visit_hours"])
                if abs(old_h - new_h) >= 2.0:
                    curated[seed] = entry
                    updated += 1
            except (TypeError, ValueError):
                pass

    payload = {"_comment": "名景点与全库热点种子；运行时优先于纯规则兜底", **curated}
    CURATED_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"unique_knowledge_seeds={len(seeds)}")
    print(f"curated_total={len(curated)}")
    print(f"added={added} updated={updated}")


if __name__ == "__main__":
    main()
