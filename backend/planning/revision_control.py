"""用于识别修订进展并阻止空转重规划循环的工具。"""

from __future__ import annotations

from typing import Any


def candidate_name_set(candidate_pois: list[dict[str, Any]] | None) -> set[str]:
    return {
        str(poi.get("name", "")).strip()
        for poi in (candidate_pois or [])
        if str(poi.get("name", "")).strip()
    }


def candidate_pool_signature(candidate_pois: list[dict[str, Any]] | None) -> str:
    names = sorted(candidate_name_set(candidate_pois))
    return f"{len(names)}|" + "|".join(names[:24])


def candidate_pool_delta(
    before: list[dict[str, Any]] | None,
    after: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    before_names = candidate_name_set(before)
    after_names = candidate_name_set(after)
    added = sorted(after_names - before_names)
    removed = sorted(before_names - after_names)
    return {
        "before_count": len(before_names),
        "after_count": len(after_names),
        "added_count": len(added),
        "removed_count": len(removed),
        "added_names": added[:8],
        "removed_names": removed[:8],
        "changed": bool(added or removed or len(before_names) != len(after_names)),
    }


def plan_signature(plan: dict[str, Any] | None) -> str:
    itinerary = list((plan or {}).get("itinerary", []) or [])
    day_signatures: list[str] = []
    for day in itinerary:
        points = ",".join(str(name).strip() for name in (day.get("route_points", []) or []) if str(name).strip())
        load = int(day.get("activity_load_used") or 0)
        day_signatures.append(f"{day.get('day', '?')}:{points}:{load}")
    total_cost = round(float((plan or {}).get("estimated_total_cost", 0) or 0), 0)
    return f"{len(itinerary)}|{int(total_cost)}|" + "||".join(day_signatures)


def issue_code_signature(review_feedback: dict[str, Any] | None) -> str:
    codes = sorted(
        {
            str(code).strip()
            for code in ((review_feedback or {}).get("issue_codes", []) or [])
            if str(code).strip()
        }
    )
    return "|".join(codes)


def record_candidate_revision(
    revision_state: dict[str, Any] | None,
    action: str,
    before: list[dict[str, Any]] | None,
    after: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(revision_state or {})
    delta = candidate_pool_delta(before, after)
    updates = {
        "last_action": action,
        "last_candidate_signature": candidate_pool_signature(after),
        "last_action_changed": bool(delta["changed"]),
        "last_action_delta": delta,
        "stagnant_actions": 0 if delta["changed"] else int(current.get("stagnant_actions", 0)) + 1,
    }
    if action == "expand_candidates":
        updates["expansion_exhausted"] = not delta["changed"]
    elif action == "trim_budget":
        updates["budget_trim_exhausted"] = not delta["changed"]
    current.update(updates)
    return current, delta


def record_review_cycle(
    revision_state: dict[str, Any] | None,
    review_feedback: dict[str, Any] | None,
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    current = dict(revision_state or {})
    review_signature = issue_code_signature(review_feedback)
    current_plan_signature = plan_signature(plan)
    repeated = bool(review_signature) and (
        review_signature == str(current.get("last_review_signature", "")).strip()
        and current_plan_signature == str(current.get("last_plan_signature", "")).strip()
    )
    current.update(
        {
            "last_review_signature": review_signature,
            "last_plan_signature": current_plan_signature,
            "stagnant_reviews": int(current.get("stagnant_reviews", 0)) + 1 if repeated else 0,
        }
    )
    return current
