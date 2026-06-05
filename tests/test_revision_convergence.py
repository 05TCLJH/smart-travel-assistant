"""修订收敛测试。

验证规划扩展、预算收缩和监督路由在多轮修订下的收敛行为。
"""

from __future__ import annotations

import unittest

from backend.agents.planner.agent import execute_planner_action
from backend.agents.supervisor.agent import decide_supervisor_route
from backend.tools.budget_tools import review_plan


class _FakeResearchTools:
    def __init__(self, extra: list[dict] | None = None) -> None:
        self._extra = extra or []

    def search_candidate_pois(self, destination: str, persona: dict, query_hint: str) -> list[dict]:
        return list(self._extra)


class _FakeRuntime:
    def __init__(self, extra: list[dict] | None = None) -> None:
        self.max_revisions = 2
        self.research_tools = _FakeResearchTools(extra)
        self.context: dict[str, object] = {}

    def emit_progress(self, *args, **kwargs) -> None:
        return None

    def append_context_progress(self, *args, **kwargs) -> None:
        return None

    def emit_step(self, *args, **kwargs) -> None:
        return None

    def publish_context(self, session_id: str, **sections) -> None:
        self.context.update(sections)


class RevisionConvergenceTests(unittest.TestCase):
    def test_review_plan_routes_preference_mismatch_to_planning(self) -> None:
        request_payload = {"destination": "青岛", "days": 2, "budget": 2000}
        persona = {"likes": ["博物馆"], "travel_style": "文化历史"}
        weather = {"rating": "良好"}
        plan = {
            "estimated_total_cost": 800,
            "routing_policy": {},
            "itinerary": [
                {
                    "day": 1,
                    "route_points": ["五四广场"],
                    "route_waypoints": [{"name": "五四广场", "type": "风景名胜", "knowledge_tags": ["city_landmark"]}],
                    "activity_load_used": 30,
                }
            ],
        }

        feedback = review_plan(request_payload, persona, weather, plan)

        self.assertIn("preference_mismatch", feedback["issue_codes"])
        self.assertEqual(feedback["routing_hint"], "planning")
        self.assertEqual(feedback["next_step"], "planning")

    def test_expand_candidates_marks_exhausted_when_pool_does_not_change(self) -> None:
        poi = {"name": "栈桥", "type": "风景名胜", "location": "120.38,36.07"}
        runtime = _FakeRuntime(extra=[dict(poi)])
        state = {
            "session_id": "s1",
            "trip_request": {"destination": "青岛", "days": 2, "budget": 2000},
            "persona": {"travel_style": "经典热门"},
            "candidate_pois": [dict(poi)],
            "weather": {"rating": "良好"},
            "planner_command": {"action": "expand_candidates", "query_hint": "热门景点"},
            "revision_state": {},
            "agent_trace": [],
            "review_feedback": {},
        }

        updates = execute_planner_action(state, runtime)

        self.assertTrue(updates["revision_state"]["expansion_exhausted"])
        self.assertFalse(updates["revision_state"]["last_action_changed"])

    def test_supervisor_finalizes_when_same_review_repeats_without_plan_change(self) -> None:
        runtime = _FakeRuntime()
        plan = {
            "estimated_total_cost": 1200,
            "itinerary": [
                {
                    "day": 1,
                    "route_points": ["五四广场"],
                    "route_waypoints": [{"name": "五四广场", "type": "风景名胜", "knowledge_tags": ["city_landmark"]}],
                    "activity_load_used": 30,
                }
            ],
        }
        state = {
            "session_id": "s2",
            "trip_request": {"destination": "青岛", "days": 2, "budget": 2000},
            "persona": {"travel_style": "文化历史"},
            "plan": plan,
            "planning_attempts": 1,
            "review_feedback": {
                "passed": False,
                "issues": ["当前路线与用户核心偏好贴合度不足"],
                "issue_codes": ["preference_mismatch"],
                "routing_hint": "planning",
            },
            "revision_state": {
                "last_review_signature": "preference_mismatch",
                "last_plan_signature": "1|1200|1:五四广场:30",
                "stagnant_reviews": 0,
            },
            "weather": {"rating": "良好"},
            "map_data": {"pois": [{"name": "五四广场"}]},
            "agent_trace": [],
        }

        updates = decide_supervisor_route(state, runtime)

        self.assertEqual(updates["review_feedback"]["next_step"], "finalize")
        self.assertTrue(updates["review_feedback"]["forced_finalize"])
        self.assertEqual(updates["revision_state"]["stagnant_reviews"], 1)


if __name__ == "__main__":
    unittest.main()
