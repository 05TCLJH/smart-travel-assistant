"""高德天气数据处理模块。

负责天气概率估算、预报结构标准化与本地兜底结果生成，避免主工具类承担过多纯计算逻辑。
"""

from __future__ import annotations

from typing import Any

from backend.core.api_key_specs import classify_service_failure
from backend.tools.amap_common import amap_failure_followup_hint, safe_float


def weather_rain_prob(condition: str) -> float | None:
    """根据天气描述粗略估算降水概率。"""
    text = str(condition or "").strip()
    if not text or text == "待更新":
        return None
    if any(token in text for token in ("暴雨", "大雨", "中雨", "雷阵雨", "雪", "台风")):
        return 0.75
    if any(token in text for token in ("小雨", "阵雨", "阴")):
        return 0.45
    if any(token in text for token in ("多云", "雾", "霾")):
        return 0.25
    return 0.12


def build_condition(day_weather: str, night_weather: str) -> str:
    """把白天与夜间天气合并成统一描述。"""
    day = str(day_weather or "").strip()
    night = str(night_weather or "").strip()
    if day and night and day != night:
        return f"{day}转{night}"
    return day or night or "未知"


def extract_forecast_reporttime(payload: dict[str, Any]) -> str:
    """读取高德天气返回中的预报更新时间。"""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("reporttime", "")).strip()


def fallback_weather_payload(destination: str, dates: list[str], reason: str) -> dict[str, Any]:
    """生成天气服务不可用时的本地兜底结果。"""
    return {
        "destination": destination,
        "resolved_name": destination,
        "geo": {},
        "rating": "良好",
        "live": {},
        "daily": [
            {
                "date": travel_date,
                "week": "",
                "condition": "多云",
                "day_weather": "多云",
                "night_weather": "多云",
                "temp_min": 18,
                "temp_max": 26,
                "rain_prob": 0.2,
                "outdoor_ok": True,
                "is_estimated": True,
                "is_pending": False,
                "note": "天气服务不可用，当前使用本地兜底估算。",
            }
            for travel_date in dates
        ],
        "advice": "天气服务暂不可用，建议临行前再次复核。",
        "provider": "fallback",
        "is_fallback": True,
        "warning": reason,
    }


def format_weather_failure_reason(reason: str) -> str:
    """把天气失败原因转成前端可读提示。"""
    text = str(reason or "").strip()
    if not text:
        return "天气服务暂不可用，建议临行前再次复核。"
    info = classify_service_failure(text, hint="amap weather")
    if info.get("code") != "unknown":
        tail = amap_failure_followup_hint(text)
        return f"{info['title']}：{info['message']}{tail}".strip()
    return f"{text}{amap_failure_followup_hint(text)}".strip()


def normalize_weather_payload(destination: str, dates: list[str], payload: dict[str, Any]) -> list[dict[str, Any]]:
    """把高德天气返回统一转换为按日期排列的前端可用结构。"""
    forecasts = payload.get("forecasts", []) if isinstance(payload, dict) else []
    casts = forecasts if isinstance(forecasts, list) else []
    if not casts:
        lives = payload.get("lives", []) if isinstance(payload, dict) else []
        if isinstance(lives, dict):
            live = lives
        else:
            live = lives[0] if lives and isinstance(lives[0], dict) else {}
        if live:
            condition = str(live.get("weather", "")).strip() or "未知"
            temperature = safe_float(live.get("temperature"), 24.0)
            rain_prob = weather_rain_prob(condition)
            return [
                {
                    "date": travel_date,
                    "week": "",
                    "condition": condition,
                    "day_weather": condition,
                    "night_weather": condition,
                    "temp_min": round(temperature - 4, 1),
                    "temp_max": round(temperature + 3, 1),
                    "rain_prob": rain_prob,
                    "outdoor_ok": (rain_prob or 0.0) < 0.45,
                    "is_estimated": True,
                    "is_pending": False,
                    "note": "高德 MCP 当前返回实时天气，未来日期使用近似推断。",
                }
                for travel_date in dates
            ]
    rows_by_date: dict[str, dict[str, Any]] = {}
    for cast in casts if isinstance(casts, list) else []:
        if not isinstance(cast, dict) or not cast.get("date"):
            continue
        condition = build_condition(str(cast.get("dayweather", "")), str(cast.get("nightweather", "")))
        rain_prob = weather_rain_prob(condition)
        rows_by_date[str(cast["date"])] = {
            "date": str(cast["date"]),
            "week": str(cast.get("week", "")),
            "condition": condition,
            "day_weather": str(cast.get("dayweather", "")),
            "night_weather": str(cast.get("nightweather", "")),
            "temp_min": safe_float(cast.get("nighttemp_float", cast.get("nighttemp")), 0.0),
            "temp_max": safe_float(cast.get("daytemp_float", cast.get("daytemp")), 0.0),
            "rain_prob": rain_prob,
            "outdoor_ok": (rain_prob or 0.0) < 0.45,
            "is_estimated": False,
            "is_pending": False,
            "note": "",
        }
    sorted_dates = sorted(rows_by_date.keys())
    last_known = sorted_dates[-1] if sorted_dates else ""
    daily: list[dict[str, Any]] = []
    for travel_date in dates:
        if travel_date in rows_by_date:
            daily.append(rows_by_date[travel_date])
        elif last_known and travel_date > last_known:
            daily.append(
                {
                    "date": travel_date,
                    "week": "",
                    "condition": "待更新",
                    "day_weather": "",
                    "night_weather": "",
                    "temp_min": None,
                    "temp_max": None,
                    "rain_prob": None,
                    "outdoor_ok": None,
                    "is_estimated": False,
                    "is_pending": True,
                    "note": f"该日期超出高德天气短期预报范围，当前仅返回到 {last_known}。",
                }
            )
        else:
            daily.append(fallback_weather_payload(destination, [travel_date], "该日期缺少天气数据")["daily"][0])
    return daily
