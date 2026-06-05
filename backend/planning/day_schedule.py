"""单日时间轴：按游览模式编排，避免「馆内游览中途插入午餐」等不合理断点。"""

from __future__ import annotations

import math
from typing import Any

from backend.planning.visit_duration import ScheduleMode, infer_schedule_mode
from backend.planning.venue_schedule_policy import MealStrategy

DAY_START_MIN = 9 * 60
EARLY_DAY_START_MIN = 8 * 60 + 30
LUNCH_START_MIN = 12 * 60
LUNCH_END_MIN = 13 * 60 + 30
DINNER_MIN = 18 * 60 + 30
TRANSIT_MIN = 30
MIDDAY_BREAK_MIN = 60
POST_VISIT_MEAL_MIN = 45


def _minutes_to_hhmm(total_minutes: int) -> str:
    total_minutes = max(0, min(total_minutes, 23 * 60 + 59))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _parse_lnglat(raw: str) -> tuple[float, float] | None:
    text = str(raw or "").strip()
    if "," not in text:
        return None
    try:
        lng, lat = text.split(",", 1)
        return float(lng), float(lat)
    except ValueError:
        return None


def _distance_km(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
    if not a or not b:
        return 0.0
    lng1, lat1 = a
    lng2, lat2 = b
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1 - h)))


def _estimate_transit_minutes(previous: dict[str, Any], current: dict[str, Any]) -> int:
    """按坐标给日程留通勤缓冲；没有坐标时回退到默认 30 分钟。"""
    prev_point = _parse_lnglat(str(previous.get("location", "")).strip())
    curr_point = _parse_lnglat(str(current.get("location", "")).strip())
    distance = _distance_km(prev_point, curr_point)
    if distance <= 0:
        return TRANSIT_MIN
    if distance <= 0.8:
        return 12
    if distance <= 3:
        return 20
    if distance <= 8:
        return 30
    if distance <= 20:
        return int(round(distance / 22 * 60 + 15))
    return min(180, int(round(distance / 38 * 60 + 25)))


def _append_transit(
    timeline: list[dict[str, str]],
    cursor: int,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> int:
    transit_min = _estimate_transit_minutes(previous, current)
    current_name = str(current.get("name", "下一站")).strip() or "下一站"
    timeline.append(
        _activity_at(
            cursor,
            f"前往 {current_name}（预留约 {transit_min} 分钟通勤，实际以地图路况为准）",
            current_name,
        )
    )
    return cursor + transit_min


def _visit_duration_minutes(poi: dict[str, Any]) -> int:
    hours = float(poi.get("visit_hours_display", poi.get("visit_hours", 2.0)) or 2.0)
    tier = str(poi.get("activity_tier", "standard") or "standard")
    if hours < 1.5 and tier in {"standard", "extended", "half_day"}:
        hours = max(hours, 2.0 if tier == "standard" else 2.5)
    minutes = int(round(hours * 60))
    mode = str(poi.get("schedule_mode") or infer_schedule_mode(poi))
    if mode == "contiguous_gate":
        return max(90, min(minutes, 4 * 60))
    if mode == "full_day_outdoor":
        return max(120, min(minutes, 9 * 60))
    if tier == "light":
        return max(60, min(minutes, 2 * 60))
    return max(75, min(minutes, 4 * 60))


def _activity_at(time_min: int, activity: str, place: str = "") -> dict[str, str]:
    return {
        "time": _minutes_to_hhmm(time_min),
        "activity": activity,
        "place": place,
    }


def _lunch_activity(mode_hint: str = "", *, time_min: int = LUNCH_START_MIN) -> dict[str, str]:
    if mode_hint == "contiguous_gate":
        return _activity_at(time_min, "午餐（放在景区/馆外，避免中途离场再次检票）")
    if mode_hint == "inside_simple_meal":
        return _activity_at(time_min, "景区内简餐或自带补给（不中途出园）")
    if mode_hint == "before_entry":
        return _activity_at(time_min, "先用午餐再入园，避免游览中途为吃饭退出重进")
    if mode_hint == "after_visit":
        return _activity_at(time_min, "出景区后午餐与休整")
    return _activity_at(time_min, "午餐与短暂休息")


def _append_visit(
    timeline: list[dict[str, str]],
    poi: dict[str, Any],
    start_min: int,
    duration_min: int,
    *,
    schedule_note: str = "",
) -> int:
    tier_label = poi.get("activity_tier_label", "常规")
    hours = round(duration_min / 60, 1)
    suffix = f"；{schedule_note}" if schedule_note else ""
    timeline.append(
        {
            "time": _minutes_to_hhmm(start_min),
            "activity": f"游览 {poi['name']}（{tier_label}，约 {hours} 小时{suffix}）",
            "place": poi["name"],
        }
    )
    return start_min + duration_min


def _crosses_lunch(start_min: int, duration_min: int) -> bool:
    return start_min < LUNCH_END_MIN and start_min + duration_min > LUNCH_START_MIN


def _dynamic_meal_schedule_note(
    poi: dict[str, Any],
    visit_start: int,
    duration_min: int,
    mode: str,
) -> str:
    del mode
    meal_note = str(poi.get("meal_note", "")).strip()
    if not meal_note:
        return ""
    if _crosses_lunch(visit_start, duration_min):
        return meal_note
    meal_strategy = str(poi.get("meal_strategy") or "flexible_break")
    if meal_strategy == "avoid_exit_reentry" and LUNCH_START_MIN - 30 <= visit_start <= LUNCH_END_MIN:
        return meal_note
    return ""


def _compose_schedule_note(*parts: str) -> str:
    return "；".join(part for part in parts if part)


def _midday_break_plan(
    start_min: int,
    duration_min: int,
    mode: str,
    meal_strategy: MealStrategy,
) -> tuple[int, int, str, str] | None:
    """午间策略分三档：自由中断、景区内补给、避免离场重进。"""
    if meal_strategy == "avoid_exit_reentry":
        return None
    if mode == "contiguous_gate":
        return None
    if not _crosses_lunch(start_min, duration_min):
        return None
    if meal_strategy == "inside_simple_meal":
        return LUNCH_START_MIN, MIDDAY_BREAK_MIN, "inside_simple_meal", "继续园内游览"
    return LUNCH_START_MIN, MIDDAY_BREAK_MIN, "", "继续游览"


def _append_midday_break(
    timeline: list[dict[str, str]],
    poi: dict[str, Any],
    lunch_at: int,
    break_min: int,
    *,
    lunch_hint: str = "",
    resume_text: str = "",
) -> int:
    scenic_name = str(poi.get("name", "景点")).strip() or "景点"
    timeline.append(_lunch_activity(lunch_hint, time_min=lunch_at))
    resume_at = lunch_at + break_min
    action = resume_text or "继续游览"
    timeline.append(_activity_at(resume_at, f"{action} {scenic_name} 或周边步行观景", scenic_name))
    return resume_at


def _append_pre_entry_supply(timeline: list[dict[str, str]], poi: dict[str, Any], visit_start: int) -> None:
    scenic_name = str(poi.get("name", "景点")).strip() or "景点"
    supply_at = max(EARLY_DAY_START_MIN, visit_start - 30)
    timeline.append(
        _activity_at(
            supply_at,
            f"入园前补给（{scenic_name} 中途不建议离场，先吃简餐/备水更稳妥）",
            scenic_name,
        )
    )


def _append_post_visit_meal(timeline: list[dict[str, str]], cursor: int) -> int:
    meal_at = max(cursor, LUNCH_END_MIN)
    timeline.append(_lunch_activity("after_visit", time_min=meal_at))
    return meal_at + POST_VISIT_MEAL_MIN


def _morning_start_for_contiguous(duration_min: int, queue_min: int = 0) -> int:
    """若馆内游览时段能在午餐前结束，优先 8:30/9:00 开场（排队计入入馆前，不占用午餐窗口）。"""
    del queue_min  # 排队在入馆前完成，不与 12:00 午餐窗口争用
    for start in (EARLY_DAY_START_MIN, DAY_START_MIN):
        if start + duration_min <= LUNCH_START_MIN:
            return start
    return DAY_START_MIN


def _prepend_morning_gap_activities(
    timeline: list[dict[str, str]],
    poi: dict[str, Any],
    *,
    visit_starts_at: int,
) -> None:
    """单次入馆被整体挪到下午时，上午用到达/休整填充，而不是留空。"""
    name = str(poi.get("name", "景点"))
    timeline.append(
        {
            "time": _minutes_to_hhmm(DAY_START_MIN),
            "activity": f"前往 {name}（交通、安检/取票，建议提前预约）",
            "place": name,
        }
    )
    if visit_starts_at >= LUNCH_END_MIN - 30:
        timeline.append(
            {
                "time": _minutes_to_hhmm(DAY_START_MIN + 45),
                "activity": "上午可在馆外或周边简要步行、休整，为下午入馆游览预留体力",
                "place": "",
            }
        )


def _ensure_lunch_placed(
    cursor: int,
    timeline: list[dict[str, str]],
    lunch_state: dict[str, bool],
    mode: str,
) -> int:
    """游览结束在午餐窗口附近时补插午餐，避免「只有游览、没有午餐」。"""
    if lunch_state["placed"]:
        return cursor
    if LUNCH_START_MIN <= cursor <= LUNCH_END_MIN + 90:
        timeline.append(_lunch_activity("contiguous_gate" if mode == "contiguous_gate" else ""))
        lunch_state["placed"] = True
        return max(cursor, LUNCH_END_MIN)
    return cursor


def _prepare_restricted_midday_entry(
    poi: dict[str, Any],
    visit_start: int,
    duration_min: int,
    timeline: list[dict[str, str]],
    lunch_state: dict[str, bool],
) -> tuple[int, bool]:
    """不建议离场重进的景点：要么上午一口气游完后再吃，要么先吃午餐再入园。"""
    if not _crosses_lunch(visit_start, duration_min):
        return visit_start, False
    if visit_start <= 10 * 60 + 15:
        _append_pre_entry_supply(timeline, poi, visit_start)
        return visit_start, True
    if not lunch_state["placed"]:
        timeline.append(_lunch_activity("before_entry", time_min=max(visit_start, LUNCH_START_MIN)))
        lunch_state["placed"] = True
    return max(visit_start, LUNCH_END_MIN), False


def _resolve_museum_start(
    cursor: int,
    poi: dict[str, Any],
    duration_min: int,
) -> tuple[int, str]:
    """大型馆：保证「排队+游览」在停止入馆前完成，否则整体前移并提示。"""
    last_entry = poi.get("_last_entry")
    if last_entry is None:
        return cursor, str(poi.get("venue_ops_note", "")).strip()
    queue = int(poi.get("queue_buffer_min", 0) or 0)
    need_by = int(last_entry) - queue - duration_min
    note = str(poi.get("venue_ops_note", "")).strip()
    if cursor <= need_by:
        return cursor, note
    if need_by >= DAY_START_MIN:
        moved = max(DAY_START_MIN, need_by)
        extra = "已按停止入馆时间前移开场"
        return moved, _compose_schedule_note(note, extra)
    warn = "下午开场可能赶不上停止入馆，建议改上午或缩短馆内路线"
    return cursor, _compose_schedule_note(note, warn)


def _schedule_block(
    cursor: int,
    duration_min: int,
    mode: ScheduleMode,
    timeline: list[dict[str, str]],
    lunch_state: dict[str, bool],
) -> int:
    """为单个景点块安排开始时间；若会与午餐窗口重叠则整体前移或后移（单次入馆不中断）。"""
    lunch_start, lunch_end = LUNCH_START_MIN, LUNCH_END_MIN
    end_if_now = cursor + duration_min

    crosses_lunch = cursor < lunch_end and end_if_now > lunch_start

    if crosses_lunch:
        if mode == "contiguous_gate":
            if cursor < lunch_start and not lunch_state["placed"]:
                timeline.append(_lunch_activity("contiguous_gate" if mode == "contiguous_gate" else ""))
                lunch_state["placed"] = True
            cursor = lunch_end

    if lunch_start <= cursor < lunch_end:
        if not lunch_state["placed"]:
            timeline.append(_lunch_activity("contiguous_gate" if mode == "contiguous_gate" else ""))
            lunch_state["placed"] = True
        cursor = lunch_end

    return cursor


def build_activity_timeline(day_pois: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not day_pois:
        return [{"time": "10:30", "activity": "自由活动或围绕住宿点轻松漫游", "place": ""}]

    from backend.planning.venue_schedule_policy import prepare_day_pois

    day_pois = prepare_day_pois(day_pois)

    from backend.planning.activity_load import is_full_day_poi

    if len(day_pois) == 1 and is_full_day_poi(day_pois[0]):
        name = day_pois[0]["name"]
        meal_strategy = str(day_pois[0].get("meal_strategy", "inside_simple_meal"))
        midday_line = (
            _lunch_activity("inside_simple_meal", time_min=12 * 60 + 30)
            if meal_strategy != "avoid_exit_reentry"
            else _activity_at(8 * 60 + 15, f"入园前补给（{name} 游览跨度长，尽量别为吃饭中途离场）", name)
        )
        exit_meal = (
            _lunch_activity("after_visit", time_min=16 * 60 + 15)
            if meal_strategy == "avoid_exit_reentry"
            else None
        )
        return sorted(
            [
                {"time": "08:00", "activity": f"出发前往 {name}", "place": name},
                {"time": "08:30", "activity": f"全天游览 {name}", "place": name},
                midday_line,
                *( [exit_meal] if exit_meal else [] ),
                {"time": "17:30", "activity": "下山/离场，晚餐与休息", "place": ""},
            ],
            key=lambda item: item["time"],
        )

    timeline: list[dict[str, str]] = []
    lunch_state = {"placed": False}
    cursor = DAY_START_MIN

    for index, poi in enumerate(day_pois):
        if index > 0:
            cursor = _append_transit(timeline, cursor, day_pois[index - 1], poi)
        mode = str(poi.get("schedule_mode") or infer_schedule_mode(poi))
        meal_strategy = str(poi.get("meal_strategy") or "flexible_break")
        duration_min = _visit_duration_minutes(poi)
        queue_min = int(poi.get("queue_buffer_min", 0) or 0) if mode == "contiguous_gate" else 0
        if mode == "contiguous_gate":
            if index == 0:
                cursor = _morning_start_for_contiguous(duration_min, queue_min)
            cursor, base_schedule_note = _resolve_museum_start(cursor, poi, duration_min)
        else:
            base_schedule_note = str(poi.get("venue_ops_note", "")).strip()
        cursor = _schedule_block(cursor, duration_min, mode, timeline, lunch_state)  # type: ignore[arg-type]
        if (
            index == 0
            and mode == "contiguous_gate"
            and cursor >= LUNCH_END_MIN
            and not any("游览" in item.get("activity", "") for item in timeline)
        ):
            _prepend_morning_gap_activities(timeline, poi, visit_starts_at=cursor)
        visit_start = cursor
        needs_post_visit_meal = False
        if meal_strategy == "avoid_exit_reentry":
            visit_start, needs_post_visit_meal = _prepare_restricted_midday_entry(
                poi,
                visit_start,
                duration_min,
                timeline,
                lunch_state,
            )
        midday_break = _midday_break_plan(visit_start, duration_min, mode, meal_strategy)  # type: ignore[arg-type]
        schedule_note = _compose_schedule_note(
            base_schedule_note,
            _dynamic_meal_schedule_note(poi, visit_start, duration_min, mode),
        )
        cursor = _append_visit(timeline, poi, visit_start, duration_min, schedule_note=schedule_note)
        if midday_break and not lunch_state["placed"]:
            lunch_at, break_min, lunch_hint, resume_text = midday_break
            resume_at = _append_midday_break(
                timeline,
                poi,
                lunch_at,
                break_min,
                lunch_hint=lunch_hint,
                resume_text=resume_text,
            )
            lunch_state["placed"] = True
            cursor += max(0, resume_at - lunch_at)
        if needs_post_visit_meal and not lunch_state["placed"]:
            cursor = _append_post_visit_meal(timeline, cursor)
            lunch_state["placed"] = True
        cursor = _ensure_lunch_placed(cursor, timeline, lunch_state, mode)

    if not lunch_state["placed"] and cursor > LUNCH_START_MIN + 45:
        timeline.append(_lunch_activity())
        lunch_state["placed"] = True

    if not any("晚餐" in item.get("activity", "") for item in timeline):
        dinner_at = max(cursor + 30, DINNER_MIN)
        timeline.append(
            {
                "time": _minutes_to_hhmm(dinner_at),
                "activity": "晚餐与自由返程，可按体力灵活调整",
                "place": "",
            }
        )

    return sorted(timeline, key=lambda item: item["time"])
