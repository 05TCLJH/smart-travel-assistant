"""MCP prompt builders for grounded travel planning."""

from __future__ import annotations

from typing import Any


def _section_writing_rules() -> list[str]:
    return [
        "每个板块都必须结合用户实际信息和当前生成方案，不能输出通用模板句。",
        "优先引用 destination、days、budget、travel_style、weather、candidate_pois、plan.itinerary、transport_plan 这些具体字段。",
        "每个板块至少要落到一个明确事实，比如某天的 POI、某个天气判断、某个预算项或某个住宿/交通安排。",
        "如果信息不足，直接说明缺口并给出补救方式，不要用空话填充。",
        "避免出现“建议提前规划、注意合理安排、以实际情况为准”这类泛化句式，除非后面紧跟具体原因。",
    ]


def build_plan_prompt_payload(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "instruction": "请只基于当前资源中的候选 POI 和用户画像生成旅行行程，不得虚构新地点。",
        "output_goal": "写出一版能直接落地的行程说明，每个板块都要带着这位用户的实际条件和当前方案细节。",
        "writing_rules": _section_writing_rules(),
        "section_requirements": {
            "方案总览": "用目的地、天数、预算、风格、天气和候选景点的真实情况解释这版方案为什么这样排。",
            "每日行程": "按天写清楚每一天围绕哪些 POI、节奏强弱和动线逻辑，尽量点名已经选中的景点。",
            "预算说明": "把预算结构和当前方案的成本压力、门票/住宿/交通倾向说清楚，和用户预算对上。",
            "交通与住宿": "结合交通偏好、住宿锚点和动线，说明为什么这样住、怎么走更顺。",
            "提醒事项": "只写和这次天气、预约、排队、体力、夜间返回等有关的提醒。",
        },
        "session_id": context["session_id"],
        "trip_request": context["trip_request"],
        "persona": context["persona"],
        "weather": context["weather"],
        "map_data": context["map_data"],
        "research_brief": context["research_brief"],
        "candidate_pois": context["candidate_pois"],
        "candidate_guard": context["candidate_guard"],
        "plan": context["plan"],
        "transport_plan": context["transport_plan"],
        "lodging_recommendations": context["lodging_recommendations"],
        "food_recommendations": context["food_recommendations"],
        "review_feedback": context["review_feedback"],
    }


def build_audit_prompt_payload(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "instruction": "检查当前行程是否只使用 grounded 的 POI，并评估每个板块是否和用户实际信息、当前方案细节真正对应。",
        "output_goal": "指出哪些板块写得太空、哪些地方没有落到真实数据，并给出如何改成更贴合当前用户的建议。",
        "writing_rules": [
            "审查时必须对照 trip_request、persona、weather、plan、transport_plan、candidate_guard 逐项核对。",
            "如果某个板块只是泛化描述，没有引用具体 POI、天数、预算或动线，就判定为不够 grounded。",
            "如果板块内容与用户偏好、预算或天气存在冲突，要明确指出冲突点。",
            "输出要偏审查结论，不要写成旅游推荐文案。",
        ],
        "audit_targets": {
            "方案总览": "是否引用了用户真实约束和 plan 的实际结构。",
            "每日行程": "是否逐日对应 plan.itinerary，是否存在空泛模板。",
            "预算说明": "是否对应 budget 和 cost_breakdown。",
            "交通与住宿": "是否对应 transport_plan、daily_stays 和 lodgings。",
            "提醒事项": "是否来源于 weather、review_feedback 或实际行程风险。",
        },
        "session_id": context["session_id"],
        "trip_request": context["trip_request"],
        "persona": context["persona"],
        "weather": context["weather"],
        "plan": context["plan"],
        "transport_plan": context["transport_plan"],
        "lodging_recommendations": context["lodging_recommendations"],
        "food_recommendations": context["food_recommendations"],
        "review_feedback": context["review_feedback"],
        "candidate_guard": context["candidate_guard"],
    }


def build_prompt_messages(name: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    if name == "plan-travel-itinerary":
        return [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": build_plan_prompt_payload(context),
                },
            }
        ]
    if name == "audit-grounding":
        return [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": build_audit_prompt_payload(context),
                },
            }
        ]
    return []
