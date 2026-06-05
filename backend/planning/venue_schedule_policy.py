"""时间轴运营约束：闭馆/停止入馆、排队缓冲、景点角色（观景/博物馆优先上午）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.planning.venue_archetype import VenueArchetype, resolve_venue_archetype
from backend.planning.venue_visit_resolver import enrich_visit_fields, resolve_poi_visit_metrics
from backend.planning.visit_duration import TIER_LABELS

DAY_OPEN = 9 * 60
LUNCH_START = 12 * 60
LUNCH_END = 13 * 60 + 30
MealStrategy = Literal["flexible_break", "inside_simple_meal", "avoid_exit_reentry"]

# 闭馆与停止入馆时间（分钟，自零点起）默认值，可按场馆形态扩展
@dataclass(frozen=True)
class VenueOps:
    queue_buffer_min: int = 0
    last_entry_min: int | None = None  # 停止入馆
    close_min: int | None = None
    prefer_start_before_min: int | None = None  # 建议最晚开始时间
    meal_strategy: MealStrategy = "flexible_break"
    meal_note: str = ""
    note: str = ""


def _ops_for_archetype(spec: VenueArchetype, name: str) -> VenueOps:
    text = str(name or "")
    if spec.archetype in {"museum_major", "palace_museum"}:
        queue = 50 if _has_major_national_museum(text) else 25
        visit_min = int(round(spec.visit_hours * 60))
        last_entry = 16 * 60
        prefer_start = max(9 * 60, last_entry - queue - visit_min)
        return VenueOps(
            queue_buffer_min=queue,
            last_entry_min=last_entry,
            close_min=17 * 60,
            prefer_start_before_min=prefer_start,
            meal_strategy="avoid_exit_reentry",
            meal_note="馆内游览尽量一次完成；建议在入馆前或离馆后安排正餐，避免中途离场重新安检/排队",
            note="大型博物馆建议上午入馆并预留排队；16:00 停止入馆，17:00 闭馆",
        )
    if spec.archetype == "memorial_hall":
        return VenueOps(
            queue_buffer_min=20,
            last_entry_min=16 * 60 + 30,
            close_min=17 * 60 + 30,
            prefer_start_before_min=14 * 60,
            meal_strategy="avoid_exit_reentry",
            meal_note="纪念馆/寺院类建议连贯参观，午餐放在入馆前后更稳妥",
            note="纪念馆下午场需留意停止入馆时间",
        )
    if spec.pairing_role == "viewpoint_after_palace":
        return VenueOps(
            prefer_start_before_min=17 * 60 + 30,
            note="宜放在故宫出口后登景山观景，约 1～1.5 小时",
        )
    return VenueOps(
        meal_strategy=_meal_strategy_for_archetype(spec, text),
        meal_note=_meal_note_for_archetype(spec, text),
    )


def _has_major_national_museum(text: str) -> bool:
    return any(k in text for k in ("国家博物馆", "中国博物馆", "故宫博物院"))


def _meal_strategy_for_archetype(spec: VenueArchetype, name: str) -> MealStrategy:
    arch = spec.archetype
    if arch in {"museum_major", "palace_museum", "memorial_hall", "heritage_site", "temple_garden"}:
        return "avoid_exit_reentry"
    if arch in {"scenic_full_day", "theme_park"}:
        return "inside_simple_meal"
    if arch == "scenic_half_day":
        if any(token in name for token in ("古城", "古镇", "古街", "步行街", "街区", "廊道", "滨江", "海滨")):
            return "flexible_break"
        return "inside_simple_meal"
    return "flexible_break"


def _meal_note_for_archetype(spec: VenueArchetype, name: str) -> str:
    strategy = _meal_strategy_for_archetype(spec, name)
    if strategy == "avoid_exit_reentry":
        return "若门票/安检流程较严，尽量不要为了午餐中途离场"
    if strategy == "inside_simple_meal":
        return "午间更适合景区内简餐或自带补给，避免专门出园找饭再折返"
    if any(token in name for token in ("古城", "古镇", "街区", "步行街", "廊道")):
        return "周边通常有餐饮点，可在不破坏节奏的前提下安排午餐"
    return ""


def prepare_day_pois(day_pois: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按运营约束重排当日景点并写入有效游览时长（含排队缓冲）。"""
    if not day_pois:
        return []

    enriched: list[dict[str, Any]] = []
    for poi in day_pois:
        item = dict(poi)
        name = str(item.get("name", ""))
        spec = resolve_venue_archetype(name)
        ops = _ops_for_archetype(spec, name)
        metrics = resolve_poi_visit_metrics(item)
        item = enrich_visit_fields(item, metrics)
        item["queue_buffer_min"] = ops.queue_buffer_min
        item["activity_tier_label"] = item.get("activity_tier_label") or TIER_LABELS.get(
            str(item.get("activity_tier", spec.tier)), spec.tier
        )
        item["pairing_role"] = spec.pairing_role
        item["venue_ops_note"] = ops.note
        item["meal_strategy"] = ops.meal_strategy
        item["meal_note"] = ops.meal_note
        item["_prefer_start_before"] = ops.prefer_start_before_min
        item["_last_entry"] = ops.last_entry_min
        enriched.append(item)

    morning: list[dict[str, Any]] = []
    viewpoint: list[dict[str, Any]] = []
    flexible: list[dict[str, Any]] = []

    for poi in enriched:
        role = str(poi.get("pairing_role", ""))
        arch = str(poi.get("venue_archetype", ""))
        if role == "viewpoint_after_palace":
            viewpoint.append(poi)
        elif arch in {"museum_major", "palace_museum", "memorial_hall"} or role == "morning_priority":
            morning.append(poi)
        elif arch in {"scenic_full_day", "theme_park"}:
            morning.append(poi)
        else:
            flexible.append(poi)

    ordered = [*morning, *flexible, *viewpoint]
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for poi in ordered:
        key = str(poi.get("name", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(poi)
    for poi in enriched:
        if str(poi.get("name", "")) not in seen:
            result.append(poi)
    return result


def effective_visit_minutes(poi: dict[str, Any]) -> int:
    hours = float(poi.get("visit_hours_display", poi.get("visit_hours", 2)) or 2)
    return max(45, int(round(hours * 60)))


def schedule_note_for_poi(poi: dict[str, Any]) -> str:
    parts: list[str] = []
    note = str(poi.get("venue_ops_note", "")).strip()
    if note:
        parts.append(note)
    meal_note = str(poi.get("meal_note", "")).strip()
    if meal_note:
        parts.append(meal_note)
    if poi.get("queue_buffer_min"):
        parts.append(f"建议预留约 {poi['queue_buffer_min']} 分钟排队入馆")
    return "；".join(parts)
