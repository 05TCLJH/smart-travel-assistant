"""生成任务进度步骤注册表，维护宏观阶段与微观步骤标识。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProgressStepDef:
    step_id: str
    stage: str
    label: str
    order: int
    default_message: str = ""


# 阶段名与前端执行流节点保持一致，步骤标识统一使用“阶段.动作”的格式。
STEP_DEFINITIONS: tuple[ProgressStepDef, ...] = (
    ProgressStepDef("intent.parse", "intent", "解析出行需求", 10, "解析目的地、天数、预算与画像"),
    ProgressStepDef("intent.policy", "intent", "生成路由策略", 20, "确定每日 POI 上限、活动负荷预算与路线风格"),
    ProgressStepDef("research.weather", "research", "获取天气", 30, "查询目的地天气预报"),
    ProgressStepDef("research.geocode", "research", "地理编码", 40, "解析目的地中心坐标与行政区"),
    ProgressStepDef("research.poi_search", "research", "检索候选景点", 50, "按策略调用高德检索 POI"),
    ProgressStepDef("research.poi_normalize", "research", "归一化与过滤", 60, "坐标校正、行政范围与质量过滤"),
    ProgressStepDef(
        "research.poi_activity_load",
        "research",
        "标注活动负荷",
        62,
        "写入 visit_profiles 游览时长与 activity_load（知识库优先）",
    ),
    ProgressStepDef("research.poi_cluster", "research", "景区簇去重", 65, "合并同一景区多个高德 POI（入口/停车场/子景点）"),
    ProgressStepDef("research.poi_guard", "research", "候选合规检查", 70, "校验候选与目的地/天气/画像约束"),
    ProgressStepDef("research.summary", "research", "调研小结", 80, "汇总候选池与天气结论"),
    ProgressStepDef("food.search", "food", "检索特色美食", 10, "匹配当地餐饮推荐"),
    ProgressStepDef("planner.think", "planner", "规划推理", 10, "分析候选并决定下一步"),
    ProgressStepDef("planner.expand", "planner", "扩展候选", 20, "检索词扩展以补足候选"),
    ProgressStepDef("planner.trim", "planner", "收缩候选", 30, "按预算、天气与贴合度筛选"),
    ProgressStepDef("planner.cluster_layout", "planner", "按负荷装箱排期", 35, "按 daily_activity_load_budget 分配各天景点"),
    ProgressStepDef("planner.finalize", "planner", "生成行程草案", 40, "编排每日主题、时间轴与活动强度"),
    ProgressStepDef("transport.plan", "transport", "住行建议", 10, "补充交通与住宿建议"),
    ProgressStepDef("budget.review", "budget", "预算审阅", 10, "检查预算与可执行性"),
    ProgressStepDef("supervisor.review", "supervisor", "总审阅", 10, "评估方案是否通过"),
    ProgressStepDef("supervisor.reroute", "supervisor", "回流优化", 20, "未通过时回到调研或规划"),
    ProgressStepDef("supervisor.finalize", "supervisor", "整理输出", 30, "合并为最终旅行方案"),
    ProgressStepDef("system.complete", "supervisor", "任务完成", 99, "旅行方案生成完成"),
    ProgressStepDef("system.error", "supervisor", "任务失败", 99, "生成失败"),
    ProgressStepDef("system.cancelled", "supervisor", "已终止", 99, "生成已由用户终止"),
)

_STEP_BY_ID = {item.step_id: item for item in STEP_DEFINITIONS}


def get_step(step_id: str) -> ProgressStepDef | None:
    return _STEP_BY_ID.get(str(step_id or "").strip())


def list_steps_public() -> list[dict[str, Any]]:
    return [
        {
            "step_id": item.step_id,
            "stage": item.stage,
            "label": item.label,
            "order": item.order,
            "default_message": item.default_message,
        }
        for item in STEP_DEFINITIONS
    ]


def build_progress_event(
    message: str,
    *,
    stage: str | None = None,
    step_id: str | None = None,
    status: str = "running",
) -> dict[str, Any]:
    """构造统一进度事件（SSE / 任务存储）。"""
    text = str(message or "").strip()
    meta = get_step(step_id) if step_id else None
    resolved_stage = stage or (meta.stage if meta else None)
    resolved_step = step_id if step_id else None
    if not text and meta:
        text = meta.default_message
    return {
        "message": text,
        "stage": resolved_stage,
        "step_id": resolved_step,
        "status": str(status or "running").strip().lower(),
        "label": meta.label if meta else None,
    }
