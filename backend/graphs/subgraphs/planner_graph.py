"""带约束循环推理的规划子图。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.planner.agent import decide_planner_action, execute_planner_action, finalize_plan, planner_next_step
from backend.schemas.graph_state import TripGraphState


def build_planner_subgraph(runtime):
    graph = StateGraph(TripGraphState)
    graph.add_node("planner_reason", lambda state: decide_planner_action(state, runtime))
    graph.add_node("planner_tool", lambda state: execute_planner_action(state, runtime))
    graph.add_node("planner_finalize", lambda state: finalize_plan(state, runtime))

    graph.add_edge(START, "planner_reason")
    graph.add_conditional_edges(
        "planner_reason",
        planner_next_step,
        {
            "expand_candidates": "planner_tool",
            "trim_budget": "planner_tool",
            "finalize": "planner_finalize",
        },
    )
    graph.add_edge("planner_tool", "planner_reason")
    graph.add_edge("planner_finalize", END)
    return graph.compile()
