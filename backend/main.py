"""后端应用入口。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.core.paths import FRONTEND_DIR, PROJECT_ROOT, ensure_runtime_dirs
from backend.core.settings import consolidate_amap_env_keys, cors_allow_origin_regex, cors_allowed_origins, public_api_base_url
from backend.runtime.state_store import runtime_state_store
from backend.runtime.task_manager import TripTaskManager
from backend.runtime.task_runner import TripTaskRunner
from backend.routers import mcp, persona, report, system, trip, vision


def _render_index_html() -> str:
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return f"<html><body><h1>Frontend entry not found</h1><p>{index_path}</p></body></html>"
    html = index_path.read_text(encoding="utf-8")
    injected = public_api_base_url().strip()
    return html.replace("__API_BASE_URL__", injected)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    ensure_runtime_dirs()
    consolidate_amap_env_keys()
    runtime_state_store.initialize()
    recovered = TripTaskManager().recover_incomplete_tasks()
    runner = TripTaskRunner()
    runner.start()
    app.state.trip_task_runner = runner
    print("Smart Travel Assistant backend started.")
    print(f"Project root: {PROJECT_ROOT}")
    if recovered:
        print(f"Recovered queued tasks after restart: {recovered}")
    try:
        yield
    finally:
        runner.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Smart Travel Assistant API",
        description="Backend API for the smart travel assistant.",
        version="3.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    allow_origins = cors_allowed_origins()
    allow_origin_regex = cors_allow_origin_regex() or None
    if allow_origins or allow_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_origin_regex=allow_origin_regex,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(system.router, prefix="/api/system", tags=["system"])
    app.include_router(persona.router, prefix="/api/persona", tags=["persona"])
    app.include_router(trip.router, prefix="/api/trip", tags=["trip"])
    app.include_router(report.router, prefix="/api/report", tags=["report"])
    app.include_router(vision.router, prefix="/api/vision", tags=["vision"])
    app.include_router(mcp.router, prefix="/mcp", tags=["mcp"])

    for route_path in ("css", "js", "assets"):
        directory = FRONTEND_DIR / route_path
        app.mount(f"/{route_path}", StaticFiles(directory=str(directory), check_dir=False), name=route_path)

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        return HTMLResponse(_render_index_html())

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "smart-travel-assistant-api",
            "project_root": str(PROJECT_ROOT),
            "frontend_dir": str(FRONTEND_DIR),
        }

    return app


application = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:application",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
