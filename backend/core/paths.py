"""Project path helpers."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATA_DIR = PROJECT_ROOT / "data"


def runtime_data_root() -> Path:
    configured = str(os.getenv("EPHEMERAL_RUNTIME_ROOT", "")).strip()
    if configured:
        return Path(configured).expanduser()
    # Hugging Face Spaces runs well with an explicitly ephemeral runtime area.
    if str(os.getenv("SPACE_ID", "")).strip():
        return Path(tempfile.gettempdir()) / "smart-travel-assistant"
    return DATA_DIR


RUNTIME_DATA_ROOT = runtime_data_root()
RUNTIME_DIR = RUNTIME_DATA_ROOT / "runtime"
REPORTS_DIR = RUNTIME_DATA_ROOT / "reports"


def ensure_runtime_dirs() -> None:
    """Ensure runtime directories exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
