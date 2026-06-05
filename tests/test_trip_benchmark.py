"""行程基准统计测试。

验证时间线记录器、结果聚合与基准摘要函数的结构稳定性。
"""

from __future__ import annotations

from backend.diagnostics.trip_benchmark import TimelineRecorder, aggregate_case_runs, summarize_result, summarize_segments


def test_timeline_recorder_builds_segments():
    recorder = TimelineRecorder(started_at=100.0)
    recorder.observe({"step_id": "research.geocode", "stage": "research", "label": "地理编码", "status": "running", "message": "start"})
    recorder.observe({"step_id": "research.geocode", "stage": "research", "label": "地理编码", "status": "done", "message": "done"})
    recorder.finalize()

    assert len(recorder.segments) == 1
    segment = recorder.segments[0]
    assert segment.step_id == "research.geocode"
    assert segment.status == "done"
    assert segment.duration_s >= 0


def test_summarize_segments_groups_by_step_and_stage():
    recorder = TimelineRecorder(started_at=200.0)
    recorder.observe({"step_id": "planner.think", "stage": "planner", "label": "规划推理", "status": "running"})
    recorder.observe({"step_id": "planner.think", "stage": "planner", "label": "规划推理", "status": "done"})
    recorder.observe({"step_id": "planner.finalize", "stage": "planner", "label": "生成行程草案", "status": "running"})
    recorder.observe({"step_id": "planner.finalize", "stage": "planner", "label": "生成行程草案", "status": "done"})
    recorder.finalize()

    summary = summarize_segments(recorder.segments)
    assert "planner.think" in summary["by_step"]
    assert "planner" in summary["by_stage"]
    assert summary["by_stage"]["planner"]["step_count"] == 2


def test_aggregate_case_runs_summarizes_elapsed_and_steps():
    runs = [
        {
            "success": True,
            "elapsed_s": 10.0,
            "step_summary": {"by_step": {"research.poi_search": {"total_duration_s": 4.0}}},
        },
        {
            "success": True,
            "elapsed_s": 14.0,
            "step_summary": {"by_step": {"research.poi_search": {"total_duration_s": 6.0}}},
        },
    ]
    summary = aggregate_case_runs(runs)

    assert summary["success_count"] == 2
    assert summary["avg_elapsed_s"] == 12.0
    assert summary["slowest_steps"][0]["step_id"] == "research.poi_search"


def test_summarize_result_extracts_plan_shape():
    result = {
        "planning_attempts": 1,
        "map_data": {"pois": [{"name": "A"}, {"name": "B"}]},
        "reflection": {"issues": ["x"]},
        "plan": {
            "candidate_count": 6,
            "estimated_total_cost": 1800,
            "itinerary": [
                {"route_points": ["A", "B"]},
                {"route_points": ["C"]},
            ],
        },
    }
    summary = summarize_result(result)

    assert summary["planning_attempts"] == 1
    assert summary["candidate_count"] == 6
    assert summary["map_poi_count"] == 2
    assert summary["day_route_counts"] == [2, 1]
