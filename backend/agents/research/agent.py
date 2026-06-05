"""负责收集天气与景点事实信息的调研代理。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from backend.agents.summary_text import summarize_research_observation
from backend.schemas.graph_state import TripGraphState
from backend.tools.grounding_tools import guard_candidate_pois


def run_research_agent(state: TripGraphState, runtime) -> dict:
    request_payload = state["trip_request"]
    persona = state["persona"]

    dest = request_payload["destination"]
    dates = state["dates"]
    runtime.emit_step("research.weather", "running", f"查询 {dest} 天气预报")
    runtime.append_context_progress(state["session_id"], f"Research Agent：收集 {dest} 的天气与景点事实...")

    def fetch_weather():
        weather = runtime.research_tools.build_weather(dest, dates)
        runtime.emit_step("research.weather", "done", f"天气评级：{weather.get('rating', '未知')}")
        return weather

    def fetch_map():
        return runtime.research_tools.build_map_data(dest, persona, emit_step=runtime.emit_step)

    with ThreadPoolExecutor(max_workers=2) as executor:
        fut_weather = executor.submit(fetch_weather)
        fut_map = executor.submit(fetch_map)
        weather = fut_weather.result()
        map_data = fut_map.result()
    runtime.check_cancelled()

    raw_pois = list(map_data.get("pois", []) or [])
    runtime.emit_step("research.poi_guard", "running", f"校验 {len(raw_pois)} 个候选与约束")
    candidate_pois, candidate_guard = guard_candidate_pois(raw_pois, request_payload, persona, weather)
    runtime.emit_step("research.poi_guard", "done", f"合规候选 {len(candidate_pois)} 个")
    map_data["pois"] = candidate_pois

    observation = summarize_research_observation(candidate_pois, weather, candidate_guard, persona)
    runtime.emit_step("research.summary", "done", observation)
    research_brief = {
        "destination": request_payload["destination"],
        "resolved_name": map_data.get("resolved_name", request_payload["destination"]),
        "weather_rating": weather.get("rating", "未知"),
        "candidate_count": len(candidate_pois),
        "candidate_guard": candidate_guard,
        "search_query": map_data.get("search_query", f"{request_payload['destination']} 景点"),
        "llm_observation": observation,
        "grounding_rules": [
            "规划阶段只能使用 candidate_pois 中的地点",
            "若候选数量不足，必须重新检索，不允许模型自行虚构景点",
            "若景点与用户偏好、预算或天气显著冲突，应优先过滤或降权",
        ],
    }
    runtime.publish_context(
        state["session_id"],
        weather=weather,
        map_data=map_data,
        candidate_pois=candidate_pois,
        candidate_guard=candidate_guard,
        research_brief=research_brief,
    )

    return {
        "weather": weather,
        "map_data": map_data,
        "candidate_pois": candidate_pois,
        "candidate_guard": candidate_guard,
        "research_brief": research_brief,
        "agent_trace": list(state.get("agent_trace", []))
        + [
            {
                "agent": "research_agent",
                "action": "collect_destination_facts",
                "thought": observation,
                "observation": f"候选景点 {len(candidate_pois)} 个，天气评级 {weather.get('rating', '未知')}，已完成约束过滤",
            }
        ],
    }
