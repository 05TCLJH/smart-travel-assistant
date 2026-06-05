"""景点坐标解析适配层，具体算法仍由调研工具提供，以避免循环依赖。"""

from __future__ import annotations

from typing import Any, Protocol


class CoordinateResolver(Protocol):
    def should_resolve_search_coordinate(self, row: dict[str, Any], name: str, address: str) -> bool: ...

    def resolve_poi_coordinate(self, row: dict[str, Any], detail: dict[str, Any] | None, destination: str) -> str: ...
