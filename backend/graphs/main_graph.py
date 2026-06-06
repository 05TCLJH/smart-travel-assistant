"""旅行规划的顶层图编排。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from langgraph.graph import END, START, StateGraph

from backend.agents.budget.agent import run_budget_reviewer_agent
from backend.agents.food.agent import run_food_agent
from backend.agents.intent.agent import run_intent_agent
from backend.agents.supervisor.agent import compose_final_result, decide_supervisor_route, supervisor_next_step
from backend.agents.transport.agent import run_transport_lodging_agent
from backend.core.thread_context import submit_with_context
from backend.graphs.subgraphs.planner_graph import build_planner_subgraph
from backend.graphs.subgraphs.research_graph import build_research_subgraph
from backend.schemas.graph_state import TripGraphState


def _invoke_subgraph(graph, state: TripGraphState) -> dict:
    return graph.invoke(state)


def _merge_parallel_updates(research_updates: dict, food_updates: dict, *, base_trace_len: int) -> dict:
    merged = dict(research_updates)
    merged["food_recommendations"] = food_updates.get("food_recommendations", [])
    research_trace = list(merged.get("agent_trace", []))
    food_trace = list(food_updates.get("agent_trace", []))[base_trace_len:]
    merged["agent_trace"] = research_trace + food_trace
    return merged


def build_trip_graph(runtime):
    research_graph = build_research_subgraph(runtime)
    planner_graph = build_planner_subgraph(runtime)

    def post_intent_parallel(state: TripGraphState) -> dict:
        snap = deepcopy(dict(state))
        base_trace_len = len(snap.get("agent_trace", []))

        def run_research() -> dict:
            return _invoke_subgraph(research_graph, deepcopy(snap))

        def run_food() -> dict:
            return run_food_agent(deepcopy(snap), runtime)

        with ThreadPoolExecutor(max_workers=2) as executor:
            research_future = submit_with_context(executor, run_research)
            food_future = submit_with_context(executor, run_food)
            research_updates = research_future.result()
            food_updates = food_future.result()

        runtime.check_cancelled()
        return _merge_parallel_updates(research_updates, food_updates, base_trace_len=base_trace_len)

    graph = StateGraph(TripGraphState)
    graph.add_node("intent_agent", lambda state: run_intent_agent(state, runtime))
    graph.add_node("research_subgraph", lambda state: _invoke_subgraph(research_graph, state))
    graph.add_node("post_intent_parallel", post_intent_parallel)
    graph.add_node("planner_subgraph", lambda state: _invoke_subgraph(planner_graph, state))
    graph.add_node("transport_lodging_agent", lambda state: run_transport_lodging_agent(state, runtime))
    graph.add_node("budget_reviewer_agent", lambda state: run_budget_reviewer_agent(state, runtime))
    graph.add_node("supervisor_agent", lambda state: decide_supervisor_route(state, runtime))
    graph.add_node("finalize_response", lambda state: compose_final_result(state, runtime))

    graph.add_edge(START, "intent_agent")
    graph.add_edge("intent_agent", "post_intent_parallel")
    graph.add_edge("post_intent_parallel", "planner_subgraph")
    graph.add_edge("planner_subgraph", "transport_lodging_agent")
    graph.add_edge("transport_lodging_agent", "budget_reviewer_agent")
    graph.add_edge("budget_reviewer_agent", "supervisor_agent")
    graph.add_conditional_edges(
        "supervisor_agent",
        supervisor_next_step,
        {
            "research": "research_subgraph",
            "planning": "planner_subgraph",
            "finalize": "finalize_response",
        },
    )
    graph.add_edge("research_subgraph", "planner_subgraph")
    graph.add_edge("finalize_response", END)
    return graph.compile(checkpointer=runtime.checkpointer)
