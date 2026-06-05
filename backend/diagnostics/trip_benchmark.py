"""行程生成耗时与结果摘要的基准辅助工具。"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from time import perf_counter
from typing import Any


DEFAULT_BENCHMARK_CASES: list[dict[str, Any]] = [
    {
        "name": "qingdao_cultural_3d",
        "trip_request": {
            "destination": "青岛",
            "start_date": "2026-06-01",
            "days": 3,
            "budget": 3500,
        },
        "persona": {
            "travel_style": "文化历史",
            "stamina": "适中",
            "transport_preference": "地铁/公交优先",
        },
    },
    {
        "name": "beijing_classic_4d",
        "trip_request": {
            "destination": "北京",
            "start_date": "2026-06-08",
            "days": 4,
            "budget": 5200,
        },
        "persona": {
            "travel_style": "经典热门",
            "stamina": "适中",
            "transport_preference": "地铁/公交优先",
        },
    },
    {
        "name": "yili_adventure_4d",
        "trip_request": {
            "destination": "伊犁",
            "start_date": "2026-06-15",
            "days": 4,
            "budget": 5600,
        },
        "persona": {
            "travel_style": "户外探险",
            "stamina": "充沛",
            "transport_preference": "打车/网约车优先",
        },
    },
]


@dataclass
class StepSegment:
    step_id: str
    stage: str
    label: str
    status: str
    start_offset_s: float
    end_offset_s: float
    duration_s: float
    message: str = ""


@dataclass
class TimelineRecorder:
    started_at: float = field(default_factory=perf_counter)
    _open_steps: dict[str, tuple[float, dict[str, Any]]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    segments: list[StepSegment] = field(default_factory=list)

    def observe(self, event: dict[str, Any]) -> None:
        now = perf_counter()
        payload = dict(event or {})
        step_id = str(payload.get("step_id", "") or "").strip()
        status = str(payload.get("status", "running") or "running").strip().lower()
        payload["_offset_s"] = round(now - self.started_at, 4)
        self.events.append(payload)

        if not step_id:
            return

        if status == "running":
            self._open_steps[step_id] = (now, payload)
            return

        opened = self._open_steps.pop(step_id, None)
        if not opened:
            return
        start_at, start_event = opened
        self.segments.append(
            StepSegment(
                step_id=step_id,
                stage=str(payload.get("stage") or start_event.get("stage") or ""),
                label=str(payload.get("label") or start_event.get("label") or step_id),
                status=status,
                start_offset_s=round(start_at - self.started_at, 4),
                end_offset_s=round(now - self.started_at, 4),
                duration_s=round(now - start_at, 4),
                message=str(payload.get("message", "") or ""),
            )
        )

    def finalize(self) -> None:
        now = perf_counter()
        for step_id, (start_at, start_event) in list(self._open_steps.items()):
            self.segments.append(
                StepSegment(
                    step_id=step_id,
                    stage=str(start_event.get("stage") or ""),
                    label=str(start_event.get("label") or step_id),
                    status="unfinished",
                    start_offset_s=round(start_at - self.started_at, 4),
                    end_offset_s=round(now - self.started_at, 4),
                    duration_s=round(now - start_at, 4),
                    message=str(start_event.get("message", "") or ""),
                )
            )
        self._open_steps.clear()


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    plan = dict(result.get("plan") or {})
    itinerary = list(plan.get("itinerary", []) or [])
    reflection = dict(result.get("reflection") or {})
    return {
        "planning_attempts": int(result.get("planning_attempts", 0) or 0),
        "candidate_count": int(plan.get("candidate_count", 0) or 0),
        "map_poi_count": len((result.get("map_data") or {}).get("pois", []) or []),
        "issues": list(reflection.get("issues", []) or []),
        "day_route_counts": [len(day.get("route_points", []) or []) for day in itinerary],
        "day_route_points": [list(day.get("route_points", []) or []) for day in itinerary],
        "estimated_total_cost": plan.get("estimated_total_cost"),
    }


def summarize_segments(segments: list[StepSegment]) -> dict[str, Any]:
    by_step: dict[str, list[StepSegment]] = {}
    by_stage: dict[str, list[StepSegment]] = {}

    for segment in segments:
        by_step.setdefault(segment.step_id, []).append(segment)
        by_stage.setdefault(segment.stage or "unknown", []).append(segment)

    step_summary = {
        step_id: {
            "label": rows[0].label,
            "count": len(rows),
            "total_duration_s": round(sum(item.duration_s for item in rows), 4),
            "avg_duration_s": round(mean(item.duration_s for item in rows), 4),
            "max_duration_s": round(max(item.duration_s for item in rows), 4),
            "statuses": sorted({item.status for item in rows}),
        }
        for step_id, rows in sorted(
            by_step.items(),
            key=lambda item: sum(row.duration_s for row in item[1]),
            reverse=True,
        )
    }

    stage_summary = {}
    for stage, rows in by_stage.items():
        first_start = min(item.start_offset_s for item in rows)
        last_end = max(item.end_offset_s for item in rows)
        stage_summary[stage] = {
            "step_count": len(rows),
            "total_duration_s": round(sum(item.duration_s for item in rows), 4),
            "span_duration_s": round(last_end - first_start, 4),
            "top_steps": [
                {
                    "step_id": item.step_id,
                    "label": item.label,
                    "duration_s": item.duration_s,
                }
                for item in sorted(rows, key=lambda row: row.duration_s, reverse=True)[:5]
            ],
        }

    return {
        "by_step": step_summary,
        "by_stage": stage_summary,
    }


def aggregate_case_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [run for run in runs if run.get("success")]
    total_times = [float(run.get("elapsed_s", 0.0) or 0.0) for run in successful]
    step_rollup: dict[str, list[float]] = {}

    for run in successful:
        for step_id, row in ((run.get("step_summary") or {}).get("by_step") or {}).items():
            step_rollup.setdefault(step_id, []).append(float(row.get("total_duration_s", 0.0) or 0.0))

    slowest_steps = [
        {
            "step_id": step_id,
            "avg_duration_s": round(mean(values), 4),
            "max_duration_s": round(max(values), 4),
            "sample_count": len(values),
        }
        for step_id, values in sorted(step_rollup.items(), key=lambda item: mean(item[1]), reverse=True)[:10]
    ]

    return {
        "run_count": len(runs),
        "success_count": len(successful),
        "failure_count": len(runs) - len(successful),
        "avg_elapsed_s": round(mean(total_times), 4) if total_times else None,
        "min_elapsed_s": round(min(total_times), 4) if total_times else None,
        "max_elapsed_s": round(max(total_times), 4) if total_times else None,
        "slowest_steps": slowest_steps,
    }
