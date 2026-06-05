"""高德地理编码解析模块。

负责从 geocode 结果中提取行政区、名称与范围信息，降低主工具类中的结构解析复杂度。
"""

from __future__ import annotations

from typing import Any

from backend.tools.grounding_tools import (
    admin_aliases,
    is_province_level_destination_name,
    normalize_admin_name,
)


def _extract_geocode_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("geocodes")
    if not rows:
        rows = payload.get("results", [])
    return [row for row in (rows or []) if isinstance(row, dict)]


def extract_geocode_location(payload: dict[str, Any]) -> str:
    """提取地理编码结果中的坐标字符串。"""
    rows = _extract_geocode_rows(payload)
    first = rows[0] if rows else {}
    return str(first.get("location", "")).strip()


def extract_geocode_name(payload: dict[str, Any], default: str) -> str:
    """提取更适合作为展示名称的行政区组合文本。"""
    rows = _extract_geocode_rows(payload)
    first = rows[0] if rows else {}
    province = str(first.get("province", "")).strip()
    city_raw = first.get("city", "")
    city_text = city_raw if isinstance(city_raw, str) else ""
    district_raw = first.get("district", "")
    district = district_raw if isinstance(district_raw, str) else ""
    parts: list[str] = []
    for part in (province, city_text, district):
        if part and part not in parts:
            parts.append(part)
    composed = "".join(parts)
    return composed or str(first.get("formatted_address", "")).strip() or default


def extract_geocode_admin1(payload: dict[str, Any]) -> str:
    """提取省级行政区名称。"""
    rows = _extract_geocode_rows(payload)
    first = rows[0] if rows else {}
    return str(first.get("province", "")).strip()


def extract_geocode_adcode(payload: dict[str, Any]) -> str:
    """提取行政区划编码。"""
    rows = _extract_geocode_rows(payload)
    first = rows[0] if rows else {}
    return str(first.get("adcode", "")).strip()


def extract_destination_scope(payload: dict[str, Any], destination: str) -> dict[str, Any]:
    """结合高德地理编码结果推导当前目的地的规划范围。"""
    rows = _extract_geocode_rows(payload)
    first = rows[0] if rows else {}
    province = str(first.get("province", "")).strip()
    city_raw = first.get("city", "")
    city = str(city_raw[0] if isinstance(city_raw, list) and city_raw else city_raw or "").strip()
    district = str(first.get("district", "")).strip()
    level = str(first.get("level", "")).strip().lower()
    province_like = (
        is_province_level_destination_name(destination)
        or is_province_level_destination_name(province)
        or level in {"province", "省"}
    )
    is_province_level = province_like and not city and not district
    if not is_province_level and province_like and city and normalize_admin_name(city) == normalize_admin_name(province):
        is_province_level = True
    resolved_name = extract_geocode_name(payload, destination)
    return {
        "destination": destination,
        "resolved_name": resolved_name,
        "province": province,
        "city": city,
        "district": district,
        "adcode": str(first.get("adcode", "")).strip(),
        "level": level,
        "is_province_level": is_province_level,
        "destination_aliases": admin_aliases(destination) | admin_aliases(province) | admin_aliases(resolved_name),
    }
