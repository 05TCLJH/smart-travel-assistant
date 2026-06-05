"""主图拓扑测试：总控回流调研后必须回到规划链，否则会无声结束且没有最终结果。"""

from __future__ import annotations

import unittest

from backend.graphs.main_graph import build_trip_graph
from backend.runtime.graph_factory import TripGraphRuntime
from backend.services.persona_service import PersonaService
from backend.tools.amap_tools import TravelResearchTools
from backend.tools.local_service_tools import LocalServiceTools


class MainGraphTopologyTests(unittest.TestCase):
    def test_start_goes_to_intent_agent(self) -> None:
        rt = TripGraphRuntime(
            PersonaService(),
            TravelResearchTools(),
            LocalServiceTools(TravelResearchTools()),
            progress_callback=lambda *a, **k: None,
        )
        g = build_trip_graph(rt)
        edges = [(e.source, e.target) for e in g.get_graph().edges]
        self.assertIn(("__start__", "intent_agent"), edges)

    def test_research_subgraph_goes_to_planner_not_end(self) -> None:
        rt = TripGraphRuntime(
            PersonaService(),
            TravelResearchTools(),
            LocalServiceTools(TravelResearchTools()),
            progress_callback=lambda *a, **k: None,
        )
        g = build_trip_graph(rt)
        edges = [(e.source, e.target) for e in g.get_graph().edges]
        self.assertIn(("research_subgraph", "planner_subgraph"), edges)
        self.assertNotIn(("research_subgraph", "__end__"), edges)


if __name__ == "__main__":
    unittest.main()
