"""基于流程图框架的行程规划服务。"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Callable

from backend.core.runtime_context import runtime_keys_scope
from backend.exceptions import TripGenerationCancelled
from backend.graphs.main_graph import build_trip_graph
from backend.runtime.graph_factory import TripGraphRuntime
from backend.services.persona_service import PersonaService
from backend.tools.amap_tools import TravelResearchTools
from backend.tools.local_service_tools import LocalServiceTools


class TravelService:
    """将规划委托给 LangGraph 多 Agent 工作流的入口服务。"""

    def __init__(self) -> None:
        self.persona_service = PersonaService()
        self.research_tools = TravelResearchTools()

    def generate(
        self,
        trip_request: dict[str, Any],
        incoming_persona: dict[str, Any] | None = None,
        progress: Callable[..., Any] | None = None,
        cancel_event: threading.Event | None = None,
        runtime_keys: dict[str, str] | None = None,
        *,
        owner_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_owner_id = str(owner_id or "").strip() or str(session_id or "").strip() or uuid.uuid4().hex
        resolved_session_id = str(session_id or "").strip() or uuid.uuid4().hex
        with runtime_keys_scope(owner_id=resolved_owner_id, **(runtime_keys or {})):
            runtime = TripGraphRuntime(
                persona_service=self.persona_service,
                research_tools=self.research_tools,
                owner_id=resolved_owner_id,
                local_service_tools=LocalServiceTools(self.research_tools),
                progress_callback=progress,
                cancel_event=cancel_event,
            )
            graph = build_trip_graph(runtime)
            runtime.start_context_session(
                resolved_session_id,
                {
                    "trip_request": trip_request,
                    "persona": incoming_persona or {},
                    "status": "running",
                },
            )
            try:
                if cancel_event is not None and cancel_event.is_set():
                    raise TripGenerationCancelled()
                final_state = graph.invoke(
                    {
                        "session_id": resolved_session_id,
                        "thread_id": resolved_session_id,
                        "user_query": "",
                        "trip_request": trip_request,
                        "persona": incoming_persona or {},
                        "planning_attempts": 0,
                        "revision_state": {},
                        "progress_events": [],
                        "agent_trace": [],
                        "errors": [],
                    },
                    config={"configurable": {"thread_id": resolved_session_id}},
                )
            except TripGenerationCancelled:
                runtime.publish_context(resolved_session_id, status="cancelled")
                raise
            except Exception as exc:
                runtime.publish_context(resolved_session_id, status="failed", errors=[str(exc)])
                raise
            payload = final_state.get("final_result")
            if payload is None:
                keys = ",".join(sorted(final_state.keys()))
                raise RuntimeError(
                    "规划流程未写出汇总结果（缺少 final_result）。"
                    "通常是 Supervisor 回流「调研」后未再回到规划/定稿链路，请检查主图 research_subgraph 出口。"
                    f" 当前状态键：{keys}"
                )
            runtime.publish_context(resolved_session_id, status="completed", final_result=payload)
            return payload
