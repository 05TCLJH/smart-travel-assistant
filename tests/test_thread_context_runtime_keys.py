from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from backend.agents.research.agent import run_research_agent
from backend.core.runtime_context import runtime_keys_scope
from backend.core.settings import amap_key
from backend.core.thread_context import submit_with_context


def test_submit_with_context_preserves_runtime_keys_in_threads():
    with runtime_keys_scope(amap_api_key="0123456789abcdef0123456789abcdef"):
        with ThreadPoolExecutor(max_workers=2) as executor:
            future = submit_with_context(executor, amap_key)
            assert future.result() == "0123456789abcdef0123456789abcdef"


def test_research_agent_parallel_fetches_keep_runtime_keys():
    seen: list[str] = []

    class DummyResearchTools:
        def build_weather(self, _dest, _dates):
            seen.append(amap_key())
            return {"rating": "ok", "daily": []}

        def build_map_data(self, destination, _persona, emit_step=None):
            seen.append(amap_key())
            return {"resolved_name": destination, "pois": []}

    class DummyRuntime:
        research_tools = DummyResearchTools()

        def emit_step(self, *_args, **_kwargs):
            pass

        def append_context_progress(self, *_args, **_kwargs):
            pass

        def check_cancelled(self):
            pass

        def publish_context(self, *_args, **_kwargs):
            pass

    state = {
        "trip_request": {"destination": "Xiamen", "days": 3, "budget": 3000},
        "persona": {},
        "dates": ["2026-06-06"],
        "session_id": "test-session",
        "agent_trace": [],
    }

    with runtime_keys_scope(amap_api_key="0123456789abcdef0123456789abcdef"):
        run_research_agent(state, DummyRuntime())

    assert seen == ["0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef"]
