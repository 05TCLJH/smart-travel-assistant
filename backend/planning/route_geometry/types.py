"""单日路线规划结果（供行程、地图、交通摘要共用）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RouteStatus = Literal["ok", "metrics_only", "unavailable", "no_waypoints", "failed"]


@dataclass
class DayRouteGeometry:
    """路线几何与里程；`draw_path` 为真时前端/静态地图才绘制折线。"""

    status: RouteStatus
    provider: str
    route_profile: str
    effective_mode: str
    distance_m: int = 0
    duration_s: int = 0
    polyline: list[list[float]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    draw_path: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # 兼容旧调用方：近似标记不再用于伪造直线路径
        if self.status == "metrics_only":
            payload["legacy_status"] = "approximate"
        return payload
