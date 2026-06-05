"""景点图像识别服务。"""

from __future__ import annotations

import base64
import os
from typing import Any

from backend.core.http_client import post_json
from backend.core.settings import bailian_enabled, bailian_key, first_env
from backend.mcp.amap_client import AmapMcpClient

_DEFAULT_MAX_IMAGE_BYTES = 4 * 1024 * 1024
_ALLOWED_MIME = frozenset({"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"})


class VisionService:
    """调用百炼/Qwen 视觉模型并返回前端友好结果。"""

    def __init__(self) -> None:
        self.api_key = bailian_key()
        self.base_url = first_env("ALIYUN_BAILIAN_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.model = first_env("VISION_MODEL") or "qwen-vl-max"
        self.timeout = float(os.getenv("VISION_TIMEOUT_SECONDS", "90").strip() or 90)
        self.max_retries = int(os.getenv("VISION_HTTP_RETRIES", "3").strip() or 3)
        self.max_image_bytes = int(
            os.getenv("VISION_MAX_IMAGE_BYTES", str(_DEFAULT_MAX_IMAGE_BYTES)).strip() or _DEFAULT_MAX_IMAGE_BYTES
        )
        self.amap = AmapMcpClient()

    @property
    def enabled(self) -> bool:
        return bailian_enabled()

    def recognize(self, image_bytes: bytes, mime_type: str, persona: dict | None = None) -> dict:
        if not image_bytes:
            raise RuntimeError("图片内容为空")
        if not self.enabled:
            raise RuntimeError("当前未配置图片识别所需的 Bailian/Qwen Key")

        mime = str(mime_type or "image/jpeg").strip().lower()
        if mime not in _ALLOWED_MIME:
            raise RuntimeError("仅支持 JPEG/PNG/WebP/GIF 图片")
        if len(image_bytes) > self.max_image_bytes:
            size_kb = len(image_bytes) // 1024
            limit_kb = self.max_image_bytes // 1024
            raise RuntimeError(
                f"图片过大（约 {size_kb}KB），请压缩到 {limit_kb}KB 以内后再识别。"
                "过大图片在 HTTPS 上传时易触发 SSL 连接中断。"
            )

        prompt = (
            "你是旅游景点识别助手。请根据图片识别景点，并只返回 JSON 对象。"
            "字段必须包含：is_scenic(boolean), scenic_name(string), city(string), province(string), "
            "confidence(number,0-1), category(string), tags(array<string>), intro(string), best_query(string)。"
        )
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": "你是专业旅游顾问，擅长识别知名景区。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                    ],
                },
            ],
        }
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        data = post_json(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            body=payload,
            timeout=self.timeout,
            max_retries=self.max_retries,
            service_name="DashScope 视觉模型",
        )

        content = self._extract_content(data)
        parsed = self._parse_json_object(content)
        scenic_name = str(parsed.get("scenic_name", "")).strip()
        city = str(parsed.get("city", "")).strip()
        location = {}
        related_pois: list[dict[str, Any]] = []
        warning = ""
        if scenic_name and self.amap.enabled:
            try:
                location = self._build_location(parsed.get("best_query") or scenic_name)
                related_pois = self._search_related_pois(scenic_name, city)
            except Exception as exc:
                warning = str(exc)
        suitability = self._suitability(persona or {}, scenic_name, parsed)
        return {
            "is_scenic": bool(parsed.get("is_scenic", True)),
            "vision": {
                "scenic_name": scenic_name,
                "city": city,
                "province": str(parsed.get("province", "")).strip(),
                "country": "中国",
                "confidence": float(parsed.get("confidence", 0.0) or 0.0),
                "category": str(parsed.get("category", "")).strip(),
                "tags": parsed.get("tags", []) if isinstance(parsed.get("tags"), list) else [],
                "intro": str(parsed.get("intro", "")).strip(),
                "best_query": str(parsed.get("best_query", "")).strip(),
                "provider": "aliyun-bailian-vision",
                "model": self.model,
            },
            "scenic_name": scenic_name,
            "query": str(parsed.get("best_query", "")).strip(),
            "location": location,
            "poi": related_pois[0] if related_pois else {},
            "related_pois": related_pois,
            "knowledge": {"tags": parsed.get("tags", []) if isinstance(parsed.get("tags"), list) else []},
            "suitability": suitability,
            "warning": warning,
        }

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices", [])
        if not choices:
            raise RuntimeError("视觉模型返回为空")
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [item.get("text", "") for item in content if isinstance(item, dict)]
            return "\n".join(texts)
        raise RuntimeError("视觉模型返回格式异常")

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        import json

        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise RuntimeError("视觉模型未返回 JSON 对象")

    def _build_location(self, query: str) -> dict[str, Any]:
        geo = self.amap.geocode(query)
        rows = geo.get("geocodes", []) if isinstance(geo, dict) else []
        first = rows[0] if rows and isinstance(rows[0], dict) else {}
        location = str(first.get("location", ""))
        lng, lat = location.split(",") if "," in location else ("0", "0")
        return {
            "destination": query,
            "resolved_name": str(first.get("formatted_address", "")).strip() or query,
            "geo": {"lng": float(lng), "lat": float(lat)},
            "provider": "amap-mcp",
        }

    def _search_related_pois(self, scenic_name: str, city: str) -> list[dict[str, Any]]:
        rows = self.amap.text_search(scenic_name, city=city).get("pois", [])
        results = []
        for row in rows[:4]:
            if not isinstance(row, dict):
                continue
            results.append(
                {
                    "name": str(row.get("name", "")),
                    "type": str(row.get("type", "")),
                    "address": str(row.get("address", "")),
                    "location": str(row.get("location", "")),
                    "rating": str((row.get("biz_ext") or {}).get("rating", "")),
                    "ticket": "未知",
                    "knowledge_tags": [],
                    "knowledge_hit": False,
                }
            )
        return results

    @staticmethod
    def _suitability(persona: dict, scenic_name: str, parsed: dict[str, Any]) -> dict:
        tags = parsed.get("tags", []) if isinstance(parsed.get("tags"), list) else []
        likes = persona.get("likes", []) if isinstance(persona.get("likes"), list) else []
        concerns = persona.get("dislikes", []) if isinstance(persona.get("dislikes"), list) else []
        score = 72
        score += min(15, len(tags) * 3)
        score += min(10, len(likes) * 2)
        score -= min(12, len(concerns) * 3)
        score = max(40, min(96, score))
        return {
            "score": score,
            "attractions": [f"识别到景点标签：{tag}" for tag in tags[:3]] or [f"{scenic_name} 具备较强展示性"],
            "concerns": [f"注意偏好避让：{item}" for item in concerns[:2]],
            "summary": f"{scenic_name or '该地点'} 与当前画像整体匹配度较高，适合纳入竞赛展示版路线。",
        }
