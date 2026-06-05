"""基于高德搜索结果的餐饮、住宿与交通辅助工具。"""

from __future__ import annotations

import math
import re
from typing import Any

from backend.planning.budget_style import lodging_fallback_types, lodging_search_keywords, normalize_budget_style
from backend.tools.amap_tools import TravelResearchTools, safe_float, safe_int
from backend.tools.grounding_tools import is_auxiliary_poi


FOOD_TYPECODE_LABELS = {
    "050100": "中餐厅",
    "050200": "外国餐厅",
    "050300": "快餐厅",
    "050400": "休闲餐饮",
    "050500": "咖啡厅",
    "050600": "茶艺馆",
    "050700": "冷饮店",
    "050800": "糕饼店",
    "050900": "甜品店",
}
FOOD_TYPE_PREFIX_LABELS = {
    "0501": "中餐厅",
    "0502": "外国餐厅",
    "0503": "快餐厅",
    "0504": "休闲餐饮",
    "0505": "咖啡厅",
    "0506": "茶艺馆",
    "0507": "冷饮店",
    "0508": "糕饼店",
    "0509": "甜品店",
    "05": "餐饮",
}
LODGING_CLUSTER_SPLIT_DISTANCE_KM = 6.0
LODGING_SAME_HOTEL_DISTANCE_BUFFER_KM = 2.2
LODGING_MAX_REASONABLE_DAY_DISTANCE_KM = 6.5
LODGING_COST_GAP_TOLERANCE = 1.6
LODGING_REAL_HOTEL_COVERAGE_KM = 18.0
LODGING_HARD_UNFIT_DISTANCE_KM = 28.0
LODGING_BROAD_REAL_HOTEL_COVERAGE_KM = 55.0


class LocalServiceTools:
    def __init__(self, research_tools: TravelResearchTools) -> None:
        self.research_tools = research_tools
        self.amap = research_tools.amap

    def search_local_foods(self, destination: str, persona: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
        scope = self._resolve_destination_scope(destination)
        anchor = scope.get("anchor")
        if self.amap.enabled:
            queries = self._food_queries(destination)
            foods = self._search_local_places(
                destination=destination,
                city_ref=str(scope.get("city_ref", "")).strip() or destination,
                queries=queries,
                anchor=anchor,
                limit=limit,
                around_types="050000",
                normalizer=lambda rows: self._normalize_food_rows(rows, destination, anchor),
            )
            if foods:
                return foods[:limit]
        return self._fallback_foods(destination, limit)

    def search_lodgings(
        self,
        destination: str,
        budget_style: str,
        limit: int = 6,
        plan: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        budget_style = normalize_budget_style(budget_style)
        scope = self._resolve_destination_scope(destination)
        anchor = scope.get("anchor")
        if self.amap.enabled:
            hotels = self._search_lodgings_by_zone(destination, budget_style, anchor, plan, limit)
            if hotels:
                return hotels[: max(limit, 8)]
            queries = self._lodging_queries(destination, budget_style, plan)
            hotels = self._search_local_places(
                destination=destination,
                city_ref=str(scope.get("city_ref", "")).strip() or destination,
                queries=queries,
                anchor=anchor,
                limit=limit,
                around_types="100000",
                normalizer=lambda rows: self._normalize_lodging_rows(rows, destination, anchor, budget_style),
            )
            if hotels:
                return hotels[:limit]
        return self._fallback_lodgings(destination, budget_style, limit)

    def build_transport_plan(
        self,
        request_payload: dict[str, Any],
        persona: dict[str, Any],
        plan: dict[str, Any],
        routing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        itinerary = plan.get("itinerary", []) or []
        total_distance_m = 0
        total_duration_s = 0
        approximate = False
        route_planning_enabled = False
        for day in itinerary:
            route_geometry = day.get("route_geometry", {}) or {}
            status = str(route_geometry.get("status", "")).strip()
            has_drawn_route = bool(route_geometry.get("draw_path")) or status == "ok"
            route_planning_enabled = route_planning_enabled or has_drawn_route
            if not has_drawn_route:
                continue
            total_distance_m += safe_int(route_geometry.get("distance_m", 0), 0)
            total_duration_s += safe_int(route_geometry.get("duration_s", 0), 0)
            approximate = approximate or status in {"metrics_only", "approximate", "failed", "unavailable"}

        preferred = str(persona.get("transport_preference", "打车/网约车优先")).strip()
        rp = routing_policy or {}
        profile = str(rp.get("route_profile") or "").strip().lower()
        metrics_available = route_planning_enabled and (total_distance_m > 0 or total_duration_s > 0)

        if not route_planning_enabled:
            suggested_mode = "地图 App 实时导航"
            summary_note = "这版方案先把景点取舍和住宿落位排顺，具体导航建议到当天直接跟着地图实时走。"
        elif profile == "walking":
            suggested_mode = "步行"
            summary_note = "整体更适合慢慢走，体力好的时段可以多留给街区、江边或夜景。"
        elif profile == "transit":
            suggested_mode = "地铁 / 公交"
            summary_note = "公共交通会更省预算，换乘多的时段记得给自己留一点缓冲。"
        elif profile == "mixed":
            suggested_mode = "公共交通与打车混合"
            summary_note = "白天可以按路况在地铁和打车之间灵活切换，回程通常会更从容。"
        else:
            suggested_mode = "步行 + 地铁 / 公交" if ("公交" in preferred or "地铁" in preferred) else "打车 / 网约车"
            summary_note = ""

        return {
            "preferred_mode": preferred,
            "suggested_mode": suggested_mode,
            "route_profile": profile or ("none" if not route_planning_enabled else "driving"),
            "route_planning_enabled": route_planning_enabled,
            "route_metrics_available": metrics_available,
            "estimated_total_distance_km": round(total_distance_m / 1000, 1) if metrics_available else None,
            "estimated_total_duration_h": round(total_duration_s / 3600, 1) if metrics_available else None,
            "is_approximate": approximate,
            "summary": (
                f"按 {request_payload.get('days', 0)} 天行程已生成出行建议，建议以 {suggested_mode} 为主。"
                + (f" {summary_note}" if summary_note else "")
            ),
            "cross_city_hint": "",
        }

    def assign_lodging_days(self, lodgings: list[dict[str, Any]], plan: dict[str, Any], trip_days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        hotels = [dict(item) for item in (lodgings or []) if isinstance(item, dict)]
        itinerary = list((plan or {}).get("itinerary", []) or [])
        hotels = self._hydrate_hotel_locations(hotels)
        hotels = self._ensure_lodging_zone_coverage(hotels, itinerary, max(1, int(trip_days or 1)))
        if not hotels:
            hotels = self._fallback_lodgings_for_itinerary(itinerary, max(1, int(trip_days or 1)))
        if not hotels:
            return [], []

        for hotel in hotels:
            hotel["recommended_days"] = []

        daily_stays: list[dict[str, Any]] = []
        total_days = max(1, int(trip_days or 1))
        assigned_hotels = self._assign_hotels_for_itinerary(itinerary, hotels, total_days)
        primary_hotel = hotels[0]
        for day_index, hotel in enumerate(assigned_hotels, start=1):
            day_payload = itinerary[day_index - 1] if day_index - 1 < len(itinerary) else {}
            picked = hotel or primary_hotel
            day_center = self._day_center(day_payload)
            hotel_location = self.research_tools.parse_lnglat(str(picked.get("location", "")).strip())
            fit_distance = self._hotel_day_fit_distance(day_payload, hotel_location)
            if day_payload.get("route_waypoints") and fit_distance > LODGING_HARD_UNFIT_DISTANCE_KM:
                replacement = self._best_concrete_hotel_for_day(day_payload, hotels, day_index)
                if replacement:
                    picked = replacement
                    hotel_location = self.research_tools.parse_lnglat(str(picked.get("location", "")).strip())
            picked["recommended_days"].append(day_index)
            daily_stays.append(
                {
                    "day": day_index,
                    "hotel_name": picked.get("name", ""),
                    "hotel_address": picked.get("address", ""),
                    "hotel_type": picked.get("type", ""),
                    "is_lodging_zone_suggestion": bool(picked.get("is_synthetic_lodging_zone")),
                    "lodging_status": "ok",
                    "distance_to_day_center_km": round(self.research_tools.distance_km(day_center, hotel_location), 1)
                    if day_center and hotel_location
                    else None,
                    "reason": self._build_night_stay_reason(
                        day_payload,
                        itinerary[day_index] if day_index < len(itinerary) else None,
                        picked,
                    ),
                }
            )

        for hotel in hotels:
            hotel["stay_label"] = self._format_day_ranges(hotel.get("recommended_days", []))
            hotel["is_primary"] = bool(hotel.get("recommended_days"))

        return hotels, daily_stays

    def _search_local_places(
        self,
        destination: str,
        city_ref: str,
        queries: list[str],
        anchor: tuple[float, float] | None,
        limit: int,
        around_types: str,
        normalizer,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        anchor_text = f"{anchor[0]},{anchor[1]}" if anchor else ""
        city_candidates = [str(city_ref or "").strip(), str(destination or "").strip(), ""]
        for query in queries:
            variants = [str(query or "").strip()]
            prefixed = f"{destination}{query}".strip()
            if prefixed and prefixed not in variants and destination not in str(query or ""):
                variants.append(prefixed)
            for variant in variants:
                for city_arg in city_candidates:
                    try:
                        rows = self.amap.text_search(variant, city=city_arg).get("pois", [])
                    except Exception:
                        continue
                    for item in normalizer(rows):
                        name = str(item.get("name", "")).strip()
                        if not name or name in seen:
                            continue
                        seen.add(name)
                        merged.append(item)
                        if len(merged) >= limit * 2:
                            return merged
                if anchor_text:
                    try:
                        rows = self.amap.around_search(variant, anchor_text, radius=8000, types=around_types).get("pois", [])
                    except Exception:
                        continue
                    for item in normalizer(rows):
                        name = str(item.get("name", "")).strip()
                        if not name or name in seen:
                            continue
                        seen.add(name)
                        merged.append(item)
                        if len(merged) >= limit * 2:
                            return merged
        return merged

    def _resolve_destination_scope(self, destination: str) -> dict[str, Any]:
        return self.research_tools.get_destination_scope(destination)

    def _resolve_destination_anchor(self, destination: str) -> tuple[float, float] | None:
        return self._resolve_destination_scope(destination).get("anchor")

    @staticmethod
    def _clean_address_text(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        cleaned = re.sub(r"^\s*\d{6}\s*", "", text)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ·|:：,，;/\\-?？")
        return cleaned or text

    @staticmethod
    def _humanize_lodging_type(type_text: str, name: str = "") -> str:
        raw = str(type_text or "").strip()
        if raw:
            tokens = [part.strip() for part in re.split(r"[;|/]", raw) if part.strip()]
            for token in tokens:
                if token.isdigit():
                    continue
                if any(ch.isalpha() for ch in token) or any("\u4e00" <= ch <= "\u9fff" for ch in token):
                    return token
        name_text = str(name or "")
        if "民宿" in name_text:
            return "民宿"
        if any(token in name_text for token in ("客栈", "旅舍")):
            return "客栈"
        return "酒店"

    def _search_lodgings_by_zone(
        self,
        destination: str,
        budget_style: str,
        anchor: tuple[float, float] | None,
        plan: dict[str, Any] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        zones = self._lodging_search_zones(plan)
        if not zones:
            return []
        merged: dict[str, dict[str, Any]] = {}
        diversified: list[dict[str, Any]] = []
        diversified_names: set[str] = set()
        for zone in zones[:6]:
            location = str(zone.get("location", "")).strip()
            if not location:
                continue
            zone_candidates: dict[str, dict[str, Any]] = {}
            for keyword in lodging_search_keywords(budget_style):
                try:
                    rows = self.amap.around_search(keyword, location, radius=4500).get("pois", [])
                except Exception:
                    continue
                for hotel in self._normalize_lodging_rows(rows, destination, anchor, budget_style, zone=zone):
                    name = str(hotel.get("name", "")).strip()
                    if not name:
                        continue
                    candidate = zone_candidates.get(name)
                    if candidate is None or (
                        safe_float(hotel.get("min_zone_distance_km"), 99.0),
                        -safe_float(hotel.get("rating"), 0.0),
                    ) < (
                        safe_float(candidate.get("min_zone_distance_km"), 99.0),
                        -safe_float(candidate.get("rating"), 0.0),
                    ):
                        zone_candidates[name] = hotel
                    existing = merged.get(name)
                    if existing is None:
                        merged[name] = hotel
                        continue
                    zone_days = {
                        int(day)
                        for day in (existing.get("zone_days", []) or [])
                        if isinstance(day, int) or str(day).isdigit()
                    }
                    zone_days.update(
                        int(day)
                        for day in (hotel.get("zone_days", []) or [])
                        if isinstance(day, int) or str(day).isdigit()
                    )
                    existing["zone_days"] = sorted(zone_days)
                    existing["min_zone_distance_km"] = min(
                        safe_float(existing.get("min_zone_distance_km"), 99.0),
                        safe_float(hotel.get("min_zone_distance_km"), 99.0),
                    )
                    existing["zone_label"] = existing.get("zone_label") or hotel.get("zone_label") or ""
                    if safe_float(hotel.get("rating"), 0.0) > safe_float(existing.get("rating"), 0.0):
                        existing["rating"] = hotel.get("rating", "")
                        existing["address"] = hotel.get("address", existing.get("address", ""))
                        existing["location"] = hotel.get("location", existing.get("location", ""))
            ranked_zone = sorted(
                zone_candidates.values(),
                key=lambda item: (
                    safe_float(item.get("min_zone_distance_km"), 99.0),
                    -safe_float(item.get("rating"), 0.0),
                ),
            )
            for hotel in ranked_zone[:2]:
                name = str(hotel.get("name", "")).strip()
                if name and name not in diversified_names:
                    diversified.append(hotel)
                    diversified_names.add(name)
        ranked = sorted(
            merged.values(),
            key=lambda item: (
                safe_float(item.get("min_zone_distance_km"), 99.0),
                -len(item.get("zone_days", []) or []),
                -safe_float(item.get("rating"), 0.0),
            ),
        )
        for hotel in ranked:
            name = str(hotel.get("name", "")).strip()
            if name and name not in diversified_names:
                diversified.append(hotel)
                diversified_names.add(name)
        return diversified[: max(limit, 8)]

    def _lodging_search_zones(self, plan: dict[str, Any] | None) -> list[dict[str, Any]]:
        itinerary = list((plan or {}).get("itinerary", []) or [])
        return [
            {
                "day": cluster["days"][0],
                "days": list(cluster["days"]),
                "label": str(cluster.get("label", "")).strip() or f"Day {cluster['days'][0]}",
                "location": f"{cluster['center'][0]},{cluster['center'][1]}",
                "cluster_id": cluster["cluster_id"],
            }
            for cluster in self._build_lodging_clusters(itinerary, len(itinerary))
            if cluster.get("center")
        ]

    def _build_lodging_clusters(self, itinerary: list[dict[str, Any]], total_days: int) -> list[dict[str, Any]]:
        clusters: list[dict[str, Any]] = []
        for day_idx in range(total_days):
            day_payload = itinerary[day_idx] if day_idx < len(itinerary) else {}
            waypoints = list(day_payload.get("route_waypoints", []) or [])
            lead = waypoints[0] if waypoints else {}
            day_center = self._day_lodging_anchor(day_payload)
            district = str(lead.get("district", "")).strip()
            place = str(lead.get("name", "")).strip()
            label = district or place or f"Day {day_idx + 1}"

            if not clusters:
                clusters.append(
                    {
                        "cluster_id": 1,
                        "days": [day_idx + 1],
                        "label": label,
                        "district": district,
                        "centers": [day_center] if day_center else [],
                        "center": day_center,
                    }
                )
                continue

            current_cluster = clusters[-1]
            current_center = current_cluster.get("center")
            should_split = False
            if current_center and day_center:
                center_distance = self.research_tools.distance_km(current_center, day_center)
                if center_distance >= LODGING_CLUSTER_SPLIT_DISTANCE_KM:
                    should_split = True
                elif center_distance >= 4.5 and district and current_cluster.get("district") and district != current_cluster.get("district"):
                    should_split = True

            if should_split:
                clusters.append(
                    {
                        "cluster_id": len(clusters) + 1,
                        "days": [day_idx + 1],
                        "label": label,
                        "district": district,
                        "centers": [day_center] if day_center else [],
                        "center": day_center,
                    }
                )
                continue

            current_cluster["days"].append(day_idx + 1)
            if not str(current_cluster.get("label", "")).strip():
                current_cluster["label"] = label
            if not str(current_cluster.get("district", "")).strip():
                current_cluster["district"] = district
            if day_center:
                current_cluster.setdefault("centers", []).append(day_center)
                centers = [point for point in current_cluster.get("centers", []) if point]
                if centers:
                    current_cluster["center"] = (
                        sum(point[0] for point in centers) / len(centers),
                        sum(point[1] for point in centers) / len(centers),
                    )
        return clusters

    def _assign_hotels_for_itinerary(
        self,
        itinerary: list[dict[str, Any]],
        hotels: list[dict[str, Any]],
        total_days: int,
    ) -> list[dict[str, Any] | None]:
        if not hotels:
            return [None] * total_days

        day_payloads = [itinerary[day_idx] if day_idx < len(itinerary) else {} for day_idx in range(total_days)]
        if not any(day_payloads):
            return [hotels[0]] * total_days

        hotel_locations = [self.research_tools.parse_lnglat(str(hotel.get("location", "")).strip()) for hotel in hotels]
        day_centers = [self._day_lodging_anchor(day_payload) for day_payload in day_payloads]
        hotel_day_distances = [
            [
                self._hotel_day_fit_distance(day_payloads[day_idx], hotel_locations[hotel_idx])
                for hotel_idx in range(len(hotels))
            ]
            for day_idx in range(total_days)
        ]
        hotel_day_costs = [
            [
                self._stay_night_hotel_cost(
                    day_idx,
                    day_payloads,
                    hotels[hotel_idx],
                    hotel_locations[hotel_idx],
                    hotel_day_distances[day_idx][hotel_idx],
                )
                for hotel_idx in range(len(hotels))
            ]
            for day_idx in range(total_days)
        ]
        best_day_distances = [min(distances) if distances else 99.0 for distances in hotel_day_distances]
        best_day_costs = [min(costs) if costs else 18.0 for costs in hotel_day_costs]

        dp: list[list[float]] = [[float("inf")] * len(hotels) for _ in range(total_days)]
        parent: list[list[int]] = [[-1] * len(hotels) for _ in range(total_days)]

        for hotel_idx in range(len(hotels)):
            dp[0][hotel_idx] = hotel_day_costs[0][hotel_idx] + self._daily_fit_penalty(
                hotel_day_costs[0][hotel_idx],
                best_day_costs[0],
                hotel_day_distances[0][hotel_idx],
                best_day_distances[0],
            )

        for day_idx in range(1, total_days):
            travel_shift_km = self._hotel_distance_from_center(day_centers[day_idx - 1], day_centers[day_idx])
            for hotel_idx in range(len(hotels)):
                current_cost = hotel_day_costs[day_idx][hotel_idx]
                fit_penalty = self._daily_fit_penalty(
                    current_cost,
                    best_day_costs[day_idx],
                    hotel_day_distances[day_idx][hotel_idx],
                    best_day_distances[day_idx],
                )
                for prev_idx in range(len(hotels)):
                    previous_hotel_still_reasonable = self._is_reasonable_day_fit(
                        hotel_day_costs[day_idx][prev_idx],
                        best_day_costs[day_idx],
                        hotel_day_distances[day_idx][prev_idx],
                        best_day_distances[day_idx],
                    )
                    switch_cost = self._hotel_switch_penalty(prev_idx == hotel_idx, travel_shift_km, previous_hotel_still_reasonable)
                    score = dp[day_idx - 1][prev_idx] + current_cost + fit_penalty + switch_cost
                    if score < dp[day_idx][hotel_idx]:
                        dp[day_idx][hotel_idx] = score
                        parent[day_idx][hotel_idx] = prev_idx

        best_last = min(range(len(hotels)), key=lambda idx: dp[total_days - 1][idx])
        assignment: list[dict[str, Any] | None] = [None] * total_days
        cursor = best_last
        for day_idx in range(total_days - 1, -1, -1):
            assignment[day_idx] = hotels[cursor]
            cursor = parent[day_idx][cursor] if day_idx > 0 else cursor
        return assignment

    def _hydrate_hotel_locations(self, hotels: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """补齐已有酒店候选的坐标，避免真实酒店因缺坐标被判为不可用。"""
        if not hotels or not self.amap.enabled:
            return hotels
        hydrated: list[dict[str, Any]] = []
        for hotel in hotels:
            item = dict(hotel)
            if self.research_tools.parse_lnglat(str(item.get("location", "")).strip()):
                hydrated.append(item)
                continue
            query_parts = [
                str(item.get("name", "")).strip(),
                str(item.get("address", "")).strip(),
                str(item.get("city", "") or item.get("cityname", "")).strip(),
            ]
            query = " ".join(part for part in query_parts if part)
            if query:
                try:
                    payload = self.research_tools.resolve_geocode_payload(query)
                    rows = payload.get("geocodes") or payload.get("results") or []
                    first = rows[0] if rows and isinstance(rows[0], dict) else {}
                    location = str(first.get("location", "")).strip()
                    if location:
                        item["location"] = location
                except Exception:
                    pass
            hydrated.append(item)
        return hydrated

    def _ensure_lodging_zone_coverage(
        self,
        hotels: list[dict[str, Any]],
        itinerary: list[dict[str, Any]],
        total_days: int,
    ) -> list[dict[str, Any]]:
        """按每天住宿锚点补齐真实酒店候选，避免远距离硬套同一家。"""
        if not itinerary:
            return hotels
        enriched = list(hotels)
        existing_names = {str(hotel.get("name", "")).strip() for hotel in enriched}
        for day_idx in range(total_days):
            day_payload = itinerary[day_idx] if day_idx < len(itinerary) else {}
            anchor = self._day_lodging_anchor(day_payload)
            if not anchor:
                continue
            if self._has_reasonable_real_hotel(enriched, day_payload, day_idx + 1):
                continue
            for hotel in self._search_lodgings_for_day_anchor(day_payload, day_idx + 1, anchor, broad=False):
                name = str(hotel.get("name", "")).strip()
                if name and name not in existing_names:
                    enriched.append(hotel)
                    existing_names.add(name)
            if self._has_reasonable_real_hotel(enriched, day_payload, day_idx + 1):
                continue
            for hotel in self._search_lodgings_for_day_anchor(day_payload, day_idx + 1, anchor, broad=True):
                name = str(hotel.get("name", "")).strip()
                if name and name not in existing_names:
                    enriched.append(hotel)
                    existing_names.add(name)
        return enriched

    def _search_lodgings_for_day_anchor(
        self,
        day_payload: dict[str, Any],
        day_number: int,
        anchor: tuple[float, float],
        *,
        broad: bool = False,
    ) -> list[dict[str, Any]]:
        if not self.amap.enabled:
            return []
        location = f"{anchor[0]},{anchor[1]}"
        waypoints = list((day_payload or {}).get("route_waypoints", []) or [])
        last = waypoints[-1] if waypoints else {}
        first = waypoints[0] if waypoints else {}
        city_hint = str(
            last.get("city", "")
            or last.get("cityname", "")
            or first.get("city", "")
            or first.get("cityname", "")
            or ""
        ).strip()
        name_hints = [
            str(last.get("name", "") or "").strip(),
            str(first.get("name", "") or "").strip(),
        ]
        zone = {
            "day": day_number,
            "days": [day_number],
            "label": str(
                last.get("district", "")
                or last.get("adname", "")
                or last.get("city", "")
                or last.get("cityname", "")
                or last.get("name", "")
                or first.get("district", "")
                or first.get("city", "")
                or first.get("name", "")
                or f"Day {day_number}"
            ).strip(),
            "location": location,
        }
        destination_hint = str(
            last.get("province", "")
            or last.get("pname", "")
            or first.get("province", "")
            or first.get("pname", "")
            or last.get("city", "")
            or last.get("cityname", "")
            or first.get("city", "")
            or first.get("cityname", "")
            or ""
        ).strip()
        keywords = ["酒店", "宾馆", "快捷酒店", "商务酒店", "民宿", "客栈"]
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        max_distance = LODGING_BROAD_REAL_HOTEL_COVERAGE_KM if broad else LODGING_REAL_HOTEL_COVERAGE_KM
        radii = (5000, 10000, 20000, 35000, 50000) if broad else (5000, 10000, 20000)
        for radius in radii:
            for keyword in keywords:
                try:
                    rows = self.amap.around_search(keyword, location, radius=radius).get("pois", [])
                except Exception:
                    continue
                for hotel in self._normalize_lodging_rows(rows, destination_hint, None, "舒适", zone=zone):
                    hotel_location = self.research_tools.parse_lnglat(str(hotel.get("location", "")).strip())
                    if self._hotel_day_fit_distance(day_payload, hotel_location) > max_distance:
                        continue
                    name = str(hotel.get("name", "")).strip()
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    hotel["source"] = "amap_lodging_day_anchor"
                    found.append(hotel)
                if len(found) >= 4:
                    return found
        text_queries = [
            f"{hint} 附近酒店"
            for hint in name_hints
            if hint
        ] + [
            f"{zone['label']} 酒店",
            f"{zone['label']} 宾馆",
            f"{city_hint} 酒店" if city_hint else "",
        ]
        for query in [item for item in text_queries if item.strip()]:
            try:
                rows = self.amap.text_search(query, city=city_hint).get("pois", [])
            except Exception:
                continue
            for hotel in self._normalize_lodging_rows(rows, destination_hint or city_hint, None, "舒适", zone=zone):
                hotel_location = self.research_tools.parse_lnglat(str(hotel.get("location", "")).strip())
                if self._hotel_day_fit_distance(day_payload, hotel_location) > max_distance:
                    continue
                name = str(hotel.get("name", "")).strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                hotel["source"] = "amap_lodging_day_text_search"
                found.append(hotel)
            if len(found) >= 4:
                return found
        return found

    def _best_concrete_hotel_for_day(
        self,
        day_payload: dict[str, Any],
        hotels: list[dict[str, Any]],
        day_number: int,
    ) -> dict[str, Any] | None:
        """兜住分配结果：无论 DP 选到谁，最终当天必须落到具体酒店名。"""
        candidates = [hotel for hotel in hotels if not hotel.get("is_synthetic_lodging_zone")]
        anchor = self._day_lodging_anchor(day_payload)
        if anchor:
            candidates.extend(self._search_lodgings_for_day_anchor(day_payload, day_number, anchor, broad=True))
        if not candidates:
            return None
        ranked: list[tuple[float, dict[str, Any]]] = []
        for hotel in self._hydrate_hotel_locations(candidates):
            name = str(hotel.get("name", "")).strip()
            if not name:
                continue
            location = self.research_tools.parse_lnglat(str(hotel.get("location", "")).strip())
            distance = self._hotel_day_fit_distance(day_payload, location)
            zone_days = {str(day) for day in (hotel.get("zone_days", []) or [])}
            score = distance
            if str(day_number) in zone_days:
                score -= 6.0
            score -= min(2.0, safe_float(hotel.get("rating"), 0.0) / 2.5)
            ranked.append((score, hotel))
        if not ranked:
            return None
        return min(ranked, key=lambda item: item[0])[1]

    def _fallback_lodgings_for_itinerary(self, itinerary: list[dict[str, Any]], total_days: int) -> list[dict[str, Any]]:
        """最后的结构兜底仍输出具体酒店名，不输出片区或空状态。"""
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for day_idx in range(total_days):
            day_payload = itinerary[day_idx] if day_idx < len(itinerary) else {}
            anchor = self._day_lodging_anchor(day_payload)
            if anchor:
                for hotel in self._search_lodgings_for_day_anchor(day_payload, day_idx + 1, anchor, broad=True):
                    name = str(hotel.get("name", "")).strip()
                    if name and name not in seen:
                        rows.append(hotel)
                        seen.add(name)
            if rows:
                continue
            waypoints = list((day_payload or {}).get("route_waypoints", []) or [])
            first = waypoints[0] if waypoints else {}
            city = str(first.get("city", "") or first.get("cityname", "") or "").strip()
            if city and self.amap.enabled:
                try:
                    raw = self.amap.text_search("酒店", city=city).get("pois", [])
                except Exception:
                    raw = []
                for hotel in self._normalize_lodging_rows(raw, city, None, "舒适"):
                    name = str(hotel.get("name", "")).strip()
                    if name and name not in seen:
                        rows.append(hotel)
                        seen.add(name)
                        break
        return rows

    def _has_reasonable_real_hotel(
        self,
        hotels: list[dict[str, Any]],
        day_payload: dict[str, Any],
        day_number: int,
    ) -> bool:
        zone_days_key = str(day_number)
        for hotel in hotels:
            if hotel.get("is_synthetic_lodging_zone"):
                continue
            hotel_location = self.research_tools.parse_lnglat(str(hotel.get("location", "")).strip())
            if not hotel_location:
                continue
            distance = self._hotel_day_fit_distance(day_payload, hotel_location)
            if distance <= LODGING_REAL_HOTEL_COVERAGE_KM:
                return True
            zone_days = {str(day) for day in (hotel.get("zone_days", []) or [])}
            if zone_days_key in zone_days and distance <= LODGING_HARD_UNFIT_DISTANCE_KM:
                return True
        return False

    @staticmethod
    def _hotel_distance_from_center(
        center: tuple[float, float] | None,
        hotel_location: tuple[float, float] | None,
    ) -> float:
        if not center or not hotel_location:
            return 99.0
        lng_gap = (center[0] - hotel_location[0]) * 85
        lat_gap = (center[1] - hotel_location[1]) * 111
        return safe_float(math.hypot(lng_gap, lat_gap), 99.0)

    def _day_route_locations(self, day_payload: dict[str, Any]) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        for poi in list((day_payload or {}).get("route_waypoints", []) or []):
            location = self.research_tools.parse_lnglat(str(poi.get("location", "")).strip())
            if location:
                points.append(location)
        return points

    def _day_lodging_anchor(self, day_payload: dict[str, Any]) -> tuple[float, float] | None:
        points = self._day_route_locations(day_payload)
        if not points:
            return None
        first = points[0]
        last = points[-1]
        center = (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
        # 夜间回酒店最怕终点太远，因此终点权重更高；首站仍参与次日早出发判断。
        weighted = [first, center, last, last]
        return (
            sum(point[0] for point in weighted) / len(weighted),
            sum(point[1] for point in weighted) / len(weighted),
        )

    def _hotel_day_fit_distance(
        self,
        day_payload: dict[str, Any],
        hotel_location: tuple[float, float] | None,
    ) -> float:
        points = self._day_route_locations(day_payload)
        if not points or not hotel_location:
            return 99.0
        center = self._day_center(day_payload)
        center_distance = self._hotel_distance_from_center(center, hotel_location)
        first_distance = self._hotel_distance_from_center(points[0], hotel_location)
        last_distance = self._hotel_distance_from_center(points[-1], hotel_location)
        return max(center_distance, first_distance * 0.55, last_distance * 0.9)

    def _day_hotel_cost(
        self,
        day_number: int,
        day_payload: dict[str, Any],
        hotel: dict[str, Any],
        distance: float,
    ) -> float:
        if distance >= 99.0:
            return 18.0
        if distance > LODGING_HARD_UNFIT_DISTANCE_KM and not hotel.get("is_synthetic_lodging_zone"):
            return 220.0 + distance * 4.0
        far_penalty = max(0.0, distance - 3.6) * 1.7 + max(0.0, distance - 6.0) * 3.3 + max(0.0, distance - 10.0) * 4.8
        zone_days = {
            int(day)
            for day in (hotel.get("zone_days", []) or [])
            if isinstance(day, int) or str(day).isdigit()
        }
        zone_bonus = -2.4 if day_number in zone_days else (0.9 if zone_days else 0.0)
        rating_bonus = min(1.2, safe_float(hotel.get("rating"), 0.0) / 10.0)
        waypoints = list((day_payload or {}).get("route_waypoints", []) or [])
        district = str((waypoints[0] or {}).get("district", "")).strip() if waypoints else ""
        hotel_district = str(hotel.get("district", "")).strip()
        district_penalty = 0.0
        if district and hotel_district and district != hotel_district and distance >= 4.5:
            district_penalty = 1.4
        return distance + far_penalty + zone_bonus + district_penalty - rating_bonus

    def _stay_night_hotel_cost(
        self,
        day_idx: int,
        day_payloads: list[dict[str, Any]],
        hotel: dict[str, Any],
        hotel_location: tuple[float, float] | None,
        day_fit_distance: float,
    ) -> float:
        """第 N 晚住宿：同时服务 Day N 晚回酒店与 Day N+1 早出发。"""
        base = self._day_hotel_cost(day_idx + 1, day_payloads[day_idx], hotel, day_fit_distance)
        if not hotel_location:
            return base + 35.0

        current_points = self._day_route_locations(day_payloads[day_idx])
        next_points = self._day_route_locations(day_payloads[day_idx + 1]) if day_idx + 1 < len(day_payloads) else []
        current_end_distance = self._hotel_distance_from_center(current_points[-1], hotel_location) if current_points else 0.0
        next_start_distance = self._hotel_distance_from_center(next_points[0], hotel_location) if next_points else 0.0

        night_penalty = max(0.0, current_end_distance - 5.0) * 2.6 + max(0.0, current_end_distance - 15.0) * 4.2
        morning_penalty = max(0.0, next_start_distance - 6.0) * 2.2 + max(0.0, next_start_distance - 18.0) * 4.0
        return base + night_penalty + morning_penalty

    @staticmethod
    def _daily_fit_penalty(
        current_cost: float,
        best_cost: float,
        current_distance: float,
        best_distance: float,
    ) -> float:
        allowed_distance = max(best_distance + LODGING_SAME_HOTEL_DISTANCE_BUFFER_KM, LODGING_MAX_REASONABLE_DAY_DISTANCE_KM)
        distance_penalty = max(0.0, current_distance - allowed_distance) * 3.6
        cost_penalty = max(0.0, current_cost - (best_cost + LODGING_COST_GAP_TOLERANCE)) * 2.4
        return distance_penalty + cost_penalty

    @staticmethod
    def _is_reasonable_day_fit(
        current_cost: float,
        best_cost: float,
        current_distance: float,
        best_distance: float,
    ) -> bool:
        allowed_distance = max(best_distance + LODGING_SAME_HOTEL_DISTANCE_BUFFER_KM, LODGING_MAX_REASONABLE_DAY_DISTANCE_KM)
        return current_distance <= allowed_distance and current_cost <= best_cost + LODGING_COST_GAP_TOLERANCE

    @staticmethod
    def _hotel_switch_penalty(keep_same_hotel: bool, travel_shift_km: float, previous_hotel_still_reasonable: bool) -> float:
        if keep_same_hotel:
            return 0.0
        if travel_shift_km <= 3.0:
            return 2.6 if previous_hotel_still_reasonable else 1.8
        if travel_shift_km <= LODGING_CLUSTER_SPLIT_DISTANCE_KM:
            return 1.7 if previous_hotel_still_reasonable else 1.1
        return 0.9 if previous_hotel_still_reasonable else 0.45

    def _day_center(self, day_payload: dict[str, Any]) -> tuple[float, float] | None:
        points = self._day_route_locations(day_payload)
        if not points:
            return None
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    @staticmethod
    def _format_day_ranges(days: list[int]) -> str:
        ordered = sorted({int(day) for day in days if isinstance(day, int) or str(day).isdigit()})
        if not ordered:
            return ""
        ranges: list[str] = []
        start = ordered[0]
        previous = ordered[0]
        for current in ordered[1:]:
            if current == previous + 1:
                previous = current
                continue
            ranges.append(f"Day {start}" if start == previous else f"Day {start}-{previous}")
            start = previous = current
        ranges.append(f"Day {start}" if start == previous else f"Day {start}-{previous}")
        return "、".join(ranges)

    def _build_day_stay_reason(self, day_payload: dict[str, Any], hotel: dict[str, Any]) -> str:
        waypoints = list((day_payload or {}).get("route_waypoints", []) or [])
        if not waypoints:
            return "当日保留弹性活动，建议优先住在交通更方便的酒店。"
        if hotel.get("is_synthetic_lodging_zone"):
            return "当天未拿到足够可靠的具体酒店候选，先给出住宿选址范围；请在地图上按评分、价格和交通再选具体酒店。"
        first_poi = str((waypoints[0] or {}).get("name", "")).strip()
        center = self._day_center(day_payload)
        hotel_location = self.research_tools.parse_lnglat(str(hotel.get("location", "")).strip())
        distance_text = ""
        if center and hotel_location:
            distance = self.research_tools.distance_km(center, hotel_location)
            distance_text = f"，距当日活动中心约 {distance:.1f} km"
        if first_poi:
            return f"优先覆盖当日首个活动点 {first_poi}，兼顾早出发与晚间回程{distance_text}。"
        return f"建议将该酒店作为当天活动的交通落点{distance_text}。"

    def _build_night_stay_reason(
        self,
        day_payload: dict[str, Any],
        next_day_payload: dict[str, Any] | None,
        hotel: dict[str, Any],
    ) -> str:
        waypoints = list((day_payload or {}).get("route_waypoints", []) or [])
        next_waypoints = list((next_day_payload or {}).get("route_waypoints", []) or []) if next_day_payload else []
        if not waypoints:
            return self._build_day_stay_reason(day_payload, hotel)
        hotel_location = self.research_tools.parse_lnglat(str(hotel.get("location", "")).strip())
        end_name = str((waypoints[-1] or {}).get("name", "")).strip()
        next_name = str((next_waypoints[0] or {}).get("name", "")).strip() if next_waypoints else ""
        end_distance = self.research_tools.distance_km(
            self.research_tools.parse_lnglat(str((waypoints[-1] or {}).get("location", "")).strip()),
            hotel_location,
        ) if hotel_location else 0.0
        next_distance = self.research_tools.distance_km(
            self.research_tools.parse_lnglat(str((next_waypoints[0] or {}).get("location", "")).strip()),
            hotel_location,
        ) if hotel_location and next_waypoints else 0.0
        if next_name:
            return (
                f"兼顾今晚从 {end_name} 回酒店（约 {end_distance:.1f} km）"
                f"和明早去 {next_name}（约 {next_distance:.1f} km），减少晚归和次日早出发折返。"
            )
        return f"优先照顾今晚从 {end_name} 回酒店，距当日终点约 {end_distance:.1f} km。"

    @staticmethod
    def _food_queries(destination: str) -> list[str]:
        province_cuisine = {
            "南昌": ["赣菜", "南昌拌粉", "瓦罐汤", "老字号餐厅", "特色小吃"],
            "长沙": ["湘菜", "老字号餐厅", "特色小吃"],
            "成都": ["川菜", "老字号餐厅", "特色小吃"],
            "西安": ["陕西菜", "老字号餐厅", "特色小吃"],
        }
        queries = province_cuisine.get(destination, [])
        queries.extend(["本地菜", "特色菜", "老字号餐厅", "特色小吃"])
        return queries

    @staticmethod
    def _lodging_queries(destination: str, budget_style: str, plan: dict[str, Any] | None = None) -> list[str]:
        queries: list[str] = []
        seen: set[str] = set()

        def add(query: str) -> None:
            text = str(query or "").strip()
            if not text or text in seen:
                return
            seen.add(text)
            queries.append(text)

        for day in list((plan or {}).get("itinerary", []) or [])[:6]:
            waypoints = list(day.get("route_waypoints", []) or [])
            for point in waypoints[:2]:
                district = str(point.get("district", "")).strip()
                name = str(point.get("name", "")).strip()
                if district:
                    add(f"{district} 酒店")
                    add(f"{district} 民宿")
                if name and len(name) <= 18:
                    add(f"{name} 附近酒店")

        for fallback in lodging_search_keywords(budget_style):
            add(fallback if fallback.startswith(destination) else f"{destination}{fallback}")

        return queries

    def _enrich_row(self, row: dict[str, Any], destination: str) -> dict[str, Any]:
        current = dict(row)
        current["location"] = str(current.get("location") or "").strip()
        current["address"] = self._clean_address_text(current.get("address"))
        current["cityname"] = str(current.get("cityname") or destination).strip()
        current["pname"] = str(current.get("pname") or "").strip()
        current["adname"] = str(current.get("adname") or "").strip()
        current["type"] = str(current.get("type") or current.get("typecode") or "").strip()
        current["biz_ext"] = {
            "rating": str((current.get("biz_ext") or {}).get("rating") or ""),
            "cost": str((current.get("biz_ext") or {}).get("cost") or ""),
        }
        return current

    def _within_destination_scope(self, row: dict[str, Any], destination: str, anchor: tuple[float, float] | None) -> bool:
        province = str(row.get("pname", row.get("province", ""))).strip()
        city = str(row.get("cityname", "")).strip()
        district = str(row.get("adname", "")).strip()
        address = str(row.get("address", "")).strip()
        haystack = " ".join(part for part in (province, city, district, address) if part)
        if destination and destination in haystack:
            return True
        location = self.research_tools.parse_lnglat(row.get("location", ""))
        if anchor and location and self.research_tools.distance_km(anchor, location) <= 35:
            return True
        return not city

    @staticmethod
    def _food_quality_score(row: dict[str, Any], destination: str) -> float:
        name = str(row.get("name", "")).strip()
        type_text = str(row.get("type", row.get("typecode", ""))).strip()
        rating = float(str((row.get("biz_ext") or {}).get("rating", "0") or "0") or 0)
        score = rating * 10
        if any(token in f"{name} {type_text}" for token in ("老字号", "本帮", "小吃", "餐馆", "酒楼")):
            score += 8
        if any(token in name for token in ("美食城", "美食广场", "小吃城", "餐饮管理", "特产")):
            score -= 14
        if destination and destination in name:
            score -= 4
        return score

    @staticmethod
    def _humanize_food_type(type_text: str, name: str = "") -> str:
        raw = str(type_text or "").strip()
        if not raw:
            return "地方菜"
        if any(ch.isalpha() for ch in raw) or any("\u4e00" <= ch <= "\u9fff" for ch in raw):
            tokens = [part.strip() for part in raw.replace("|", ";").split(";") if part.strip()]
            for token in tokens:
                if any(char.isdigit() for char in token) and not any("\u4e00" <= ch <= "\u9fff" for ch in token):
                    continue
                return token
        compact = raw.replace(" ", "")
        if compact in FOOD_TYPECODE_LABELS:
            return FOOD_TYPECODE_LABELS[compact]
        for prefix, label in FOOD_TYPE_PREFIX_LABELS.items():
            if compact.startswith(prefix):
                return label
        if any(token in str(name or "") for token in ("咖啡", "coffee")):
            return "咖啡厅"
        if any(token in str(name or "") for token in ("甜品", "面包", "蛋糕", "dessert")):
            return "甜品店"
        return "餐饮"

    def _normalize_food_rows(self, rows: list[Any], destination: str, anchor: tuple[float, float] | None) -> list[dict[str, Any]]:
        foods: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            current = self._enrich_row(row, destination)
            name = str(current.get("name", "")).strip()
            if not name or name in seen:
                continue
            type_text = str(current.get("type", current.get("typecode", ""))).strip()
            if not type_text.startswith("05"):
                continue
            if any(token in name for token in ("酒店", "停车场", "公交站", "地铁站", "食堂")):
                continue
            if is_auxiliary_poi({"name": name, "type": type_text}):
                continue
            if not self._within_destination_scope(current, destination, anchor):
                continue
            seen.add(name)
            foods.append(
                {
                    "name": name,
                    "type": self._humanize_food_type(type_text, name),
                    "type_code": type_text,
                    "address": self._clean_address_text(current.get("address", "")),
                    "location": str(current.get("location", "")),
                    "rating": str((current.get("biz_ext") or {}).get("rating", "")),
                    "avg_cost": str((current.get("biz_ext") or {}).get("cost", "")),
                    "city": str(current.get("cityname", "")),
                    "district": str(current.get("adname", "")),
                    "quality_score": round(self._food_quality_score(current, destination), 2),
                    "source": "amap_food_search",
                }
            )
        return sorted(foods, key=lambda item: (item.get("quality_score", 0.0), item.get("rating", "")), reverse=True)

    def _normalize_lodging_rows(
        self,
        rows: list[Any],
        destination: str,
        anchor: tuple[float, float] | None,
        budget_style: str,
        zone: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        hotels: list[dict[str, Any]] = []
        seen: set[str] = set()
        zone_location = self.research_tools.parse_lnglat(str((zone or {}).get("location", "")).strip())
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            current = self._enrich_row(row, destination)
            name = str(current.get("name", "")).strip()
            if not name or name in seen:
                continue
            type_text = str(current.get("type", current.get("typecode", "")))
            if not any(token in f"{name} {type_text}" for token in ("酒店", "宾馆", "民宿", "客栈", "旅舍")):
                continue
            if not self._within_destination_scope(current, destination, anchor):
                continue
            seen.add(name)
            hotel_location = self.research_tools.parse_lnglat(str(current.get("location", "")).strip())
            hotels.append(
                {
                    "name": name,
                    "type": self._humanize_lodging_type(type_text, name),
                    "address": self._clean_address_text(current.get("address", "")),
                    "location": str(current.get("location", "")),
                    "rating": str((current.get("biz_ext") or {}).get("rating", "")),
                    "city": str(current.get("cityname", "")),
                    "district": str(current.get("adname", "")),
                    "budget_tier": budget_style,
                    "zone_days": list((zone or {}).get("days", []) or []),
                    "zone_label": str((zone or {}).get("label", "")).strip(),
                    "min_zone_distance_km": round(self.research_tools.distance_km(zone_location, hotel_location), 1)
                    if zone_location and hotel_location
                    else 99.0,
                    "source": "amap_lodging_search",
                }
            )
        return sorted(
            hotels,
            key=lambda item: (
                safe_float(item.get("min_zone_distance_km"), 99.0),
                -safe_float(item.get("rating"), 0.0),
            ),
        )

    @staticmethod
    def _fallback_foods(destination: str, limit: int) -> list[dict[str, Any]]:
        library = {
            "南昌": [
                {"name": "南昌拌粉", "type": "江西特色小吃", "address": "本地老城小吃街", "rating": "4.6", "avg_cost": "18", "source": "demo_food_library"},
                {"name": "瓦罐汤", "type": "江西特色汤品", "address": "本地早餐店", "rating": "4.5", "avg_cost": "12", "source": "demo_food_library"},
                {"name": "白糖糕", "type": "传统点心", "address": "步行街周边", "rating": "4.4", "avg_cost": "10", "source": "demo_food_library"},
            ],
            "北京": [
                {"name": "北京烤鸭", "type": "京味特色", "address": "核心商圈餐厅", "rating": "4.7", "avg_cost": "120", "source": "demo_food_library"},
                {"name": "炸酱面", "type": "京味面食", "address": "胡同周边", "rating": "4.5", "avg_cost": "35", "source": "demo_food_library"},
            ],
        }
        return library.get(
            destination,
            [{"name": f"{destination} 本地特色餐厅", "type": "地方菜", "address": f"{destination} 市区", "rating": "4.5", "avg_cost": "60", "source": "demo_food_library"}],
        )[:limit]

    @staticmethod
    def _fallback_lodgings(destination: str, budget_style: str, limit: int) -> list[dict[str, Any]]:
        budget_style = normalize_budget_style(budget_style)
        downtown_type, scenic_type, transit_type = lodging_fallback_types(budget_style)
        rows = [
            {"name": f"{destination} 市中心酒店", "type": downtown_type, "address": f"{destination} 市中心", "rating": "4.5", "budget_tier": budget_style, "source": "demo_lodging_library"},
            {"name": f"{destination} 景区周边民宿", "type": scenic_type, "address": f"{destination} 核心景区周边", "rating": "4.4", "budget_tier": budget_style, "source": "demo_lodging_library"},
            {"name": f"{destination} 交通枢纽酒店", "type": transit_type, "address": f"{destination} 交通枢纽附近", "rating": "4.3", "budget_tier": budget_style, "source": "demo_lodging_library"},
        ]
        return rows[:limit]
