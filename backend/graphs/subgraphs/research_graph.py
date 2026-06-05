"""调研子图。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.research.agent import run_research_agent
from backend.schemas.graph_state import TripGraphState


def build_research_subgraph(runtime):
    graph = StateGraph(TripGraphState)
    graph.add_node("research_agent", lambda state: run_research_agent(state, runtime))
    graph.add_edge(START, "research_agent")
    graph.add_edge("research_agent", END)
    return graph.compile()
