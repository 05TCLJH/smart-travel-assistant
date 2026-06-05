"""进度目录测试。

验证进度事件构建与公开步骤目录输出是否保持稳定。
"""

from backend.runtime.progress_catalog import build_progress_event, get_step, list_steps_public


def test_build_progress_event_resolves_meta():
    event = build_progress_event("完成", step_id="research.geocode", status="done")
    assert event["stage"] == "research"
    assert event["step_id"] == "research.geocode"
    assert event["status"] == "done"
    assert event["label"] == "地理编码"


def test_catalog_lists_all_steps():
    steps = list_steps_public()
    assert len(steps) >= 17
    assert get_step("research.poi_cluster") is not None
    assert get_step("planner.cluster_layout") is not None
    assert get_step("planner.finalize") is not None
