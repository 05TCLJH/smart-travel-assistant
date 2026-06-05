"""核对 destination_knowledge 热点是否在 curated_visit_profiles 中有游玩时长。"""
from __future__ import annotations

import json
from pathlib import Path

from backend.knowledge.destination_catalog import (
    _load_catalog,
    _load_curated_visit_seeds,
    iter_all_hotspot_names,
)
ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "_hotspot_coverage_report.json"


def main() -> None:
    catalog = _load_catalog()
    curated = _load_curated_visit_seeds()

    seed_by_dest: dict[str, list[str]] = {}
    all_seeds: list[str] = []
    for dest, profile in catalog.items():
        names = iter_all_hotspot_names(profile)
        seed_by_dest[dest] = names
        all_seeds.extend(names)

    unique_seeds = sorted(set(all_seeds))
    in_curated = [s for s in unique_seeds if s in curated]
    missing_curated = [s for s in unique_seeds if s not in curated]

    invalid_curated: list[dict] = []
    for seed in in_curated:
        raw = curated[seed]
        h = raw.get("typical_visit_hours")
        t = raw.get("activity_tier")
        if h is None or not t:
            invalid_curated.append({"seed": seed, "issue": "missing hours or tier"})

    report = {
        "destinations": len(catalog),
        "unique_hotspot_seeds": len(unique_seeds),
        "in_curated_json": len(in_curated),
        "missing_from_curated_json": len(missing_curated),
        "invalid_curated_entries": len(invalid_curated),
        "coverage_curated_pct": round(100 * len(in_curated) / max(1, len(unique_seeds)), 1),
        "full_coverage": len(missing_curated) == 0 and len(invalid_curated) == 0,
        "missing_seeds": missing_curated[:50],
        "invalid_curated": invalid_curated,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== 热点游玩时长覆盖核对 ===")
    print(f"目的地条目: {report['destinations']}")
    print(f"唯一热点种子: {report['unique_hotspot_seeds']}")
    print(f"已在 curated_visit_profiles.json: {report['in_curated_json']} ({report['coverage_curated_pct']}%)")
    print(f"未在 curated: {report['missing_from_curated_json']}")
    print(f"在 curated 但字段不完整: {report['invalid_curated_entries']}")
    print(f"知识库热点已全部覆盖: {'是' if report['full_coverage'] else '否'}")
    print(f"报告已写入: {REPORT}")


if __name__ == "__main__":
    main()
