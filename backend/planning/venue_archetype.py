"""景点形态：统一决定游览时长，避免「有山等于五小时」「有公园等于大草原」类误判。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import re as _re

from backend.planning.visit_duration import (
    LOAD_EXTENDED,
    LOAD_FULL_DAY,
    LOAD_HALF_DAY,
    LOAD_LIGHT,
    LOAD_STANDARD,
    ScheduleMode,
    TIER_LOAD,
    compose_visit_metrics,
    infer_schedule_mode,
)

ArchetypeId = Literal[
    "city_square",
    "urban_park_view",
    "heritage_park",
    "temple_garden",
    "museum_major",
    "palace_museum",
    "memorial_hall",
    "street_district",
    "water_experience",
    "landmark_ride",
    "scenic_half_day",
    "scenic_full_day",
    "scenic_city_hill",
    "theme_park",
    "heritage_site",
    "generic_standard",
]

@dataclass(frozen=True)
class ArchetypeSpec:
    tier: str
    visit_hours: float
    activity_load: int
    schedule_mode: ScheduleMode
    pairing_role: str = "standalone"


# 各形态的默认游览时长、体力负荷、时间轴排期模式（单一事实来源）
ARCHETYPE_REGISTRY: dict[ArchetypeId, ArchetypeSpec] = {
    "city_square": ArchetypeSpec("light", 1.2, LOAD_LIGHT, "flexible"),
    "urban_park_view": ArchetypeSpec("standard", 1.5, LOAD_STANDARD, "flexible"),
    "heritage_park": ArchetypeSpec("standard", 2.0, LOAD_STANDARD, "flexible"),
    "temple_garden": ArchetypeSpec("standard", 1.5, LOAD_STANDARD, "contiguous_gate"),
    "memorial_hall": ArchetypeSpec("extended", 2.5, LOAD_EXTENDED, "contiguous_gate", "morning_priority"),
    "museum_major": ArchetypeSpec("half_day", 3.0, LOAD_HALF_DAY, "contiguous_gate", "morning_priority"),
    "palace_museum": ArchetypeSpec("half_day", 3.5, LOAD_HALF_DAY, "contiguous_gate", "morning_priority"),
    "street_district": ArchetypeSpec("standard", 2.5, LOAD_STANDARD, "flexible"),
    "water_experience": ArchetypeSpec("light", 1.5, LOAD_LIGHT, "flexible"),
    "landmark_ride": ArchetypeSpec("light", 1.2, LOAD_LIGHT, "flexible"),
    "heritage_site": ArchetypeSpec("extended", 3.0, LOAD_EXTENDED, "contiguous_gate"),
    "scenic_half_day": ArchetypeSpec("half_day", 5.0, LOAD_HALF_DAY, "full_day_outdoor"),
    "scenic_full_day": ArchetypeSpec("full_day", 7.5, LOAD_FULL_DAY, "full_day_outdoor"),
    # 城市近郊名山通常兼具人文与登山体验，常规停留约 3 到 4 小时，可与书院或街区同日搭配
    "scenic_city_hill": ArchetypeSpec("extended", 3.5, LOAD_EXTENDED, "flexible"),
    "theme_park": ArchetypeSpec("half_day", 6.0, LOAD_HALF_DAY, "theme_park"),
    "generic_standard": ArchetypeSpec("standard", 2.0, LOAD_STANDARD, "flexible"),
}

# 仅覆盖大型主题乐园、游乐园品牌或高德游乐园类型；普通名称带公园的地点不在此列
_THEME_PARK_MARKERS = (
    "迪士尼乐园",
    "迪士尼度假区",
    "迪士尼",
    "环球影城",
    "欢乐谷",
    "方特",
    "长隆海洋王国",
    "长隆欢乐世界",
    "长隆旅游度假区",
    "长隆",
    "主题乐园",
    "世界之窗",
    "锦绣中华",
    "欢乐世界",
    "海洋王国",
    "海洋公园",
    "融创乐园",
    "万达乐园",
    "冒险岛",
    "童话王国",
    "游乐园",
    "游乐场",
)

# 售票处、停车场等：轻量过路，不得因名称含「黄山」等被判为整日景区
_AUXILIARY_FACILITY_MARKERS = (
    "游客中心",
    "售票处",
    "检票口",
    "东门",
    "西门",
    "南门",
    "北门",
    "停车场",
    "服务区",
    "出入口",
    "咨询处",
)

_THEME_PARK_EXCLUDE = (
    "创意文化园",
    "创意文化",
    "文化产业园",
    "摩天轮",
    "温泉",
    "滑雪",
    "漂流",
)

_AMUSEMENT_TYPECODES = frozenset({"080501", "080502", "080503", "080504"})

_LARGE_SCENIC_MARKERS = (
    "国家森林公园",
    "国家地质公园",
    "国家级风景名胜区",
    "风景名胜区",
    "风景旅游区",
    "旅游风景区",
    "世界遗产",
    "自然保护区",
    "国家公园",
    "森林公园",
    "沙漠",
    "冰川",
    "天池",
    "喀纳斯",
    "九寨沟",
    "张家界",
    "黄山",
    "华山",
    "峨眉山",
    "武功山",
    "大峡谷",
    "大草原",
)

_URBAN_PARK_HINTS = ("山公园", "古城公园", "滨河公园")

_REMOTE_NATURE_PARK_MARKERS = (
    "生态公园",
    "湿地公园",
    "森林公园",
    "草原",
    "牧场",
    "草甸",
    "峡谷",
    "徒步",
    "郊野公园",
    "自然保护区",
)

_PALACE_VIEWPOINT_NAMES = frozenset({"景山公园", "北京景山公园"})

_LAKE_SEA_RE = re.compile(r"(湖|海|泊|潭|水库|草原)(?!大桥|喷泉)")

# 知名山岳短名常只返回主名，如「泰山」；这里按登山难度与景区规模分档，不做单点补丁
_FAMOUS_MOUNTAIN_TIERS: dict[str, ArchetypeId] = {
    "泰山": "scenic_full_day",
    "黄山": "scenic_full_day",
    "华山": "scenic_full_day",
    "峨眉山": "scenic_full_day",
    "庐山": "scenic_full_day",
    "武功山": "scenic_full_day",
    "长白山": "scenic_full_day",
    "玉龙雪山": "scenic_full_day",
    "梅里雪山": "scenic_full_day",
    "四姑娘山": "scenic_full_day",
    "神农架": "scenic_full_day",
    "张家界": "scenic_full_day",
    "九寨沟": "scenic_full_day",
    "武当山": "scenic_half_day",
    "武夷山": "scenic_half_day",
    "雁荡山": "scenic_half_day",
    "三清山": "scenic_half_day",
    "崂山": "scenic_half_day",
    "天柱山": "scenic_half_day",
    "梵净山": "scenic_half_day",
    "普陀山": "scenic_half_day",
    "天台山": "scenic_half_day",
    "龙虎山": "scenic_half_day",
    "阿尔山": "scenic_half_day",
    # 城市近郊名岳（非黄山类整日登山）
    "岳麓山": "scenic_city_hill",
    "珞珈山": "scenic_city_hill",
    "紫金山": "scenic_city_hill",
    "香山": "scenic_city_hill",
    "佘山": "scenic_city_hill",
}

_FULL_DAY_PEAK_TOKENS = tuple(
    peak for peak, tier in _FAMOUS_MOUNTAIN_TIERS.items() if tier == "scenic_full_day"
)

_MOUNTAIN_POI_NOISE = (
    "公园",
    "广场",
    "索道站",
    "售票",
    "停车场",
    "游客中心",
    "服务区",
    "公交站",
    "地铁站",
    "酒店",
    "客栈",
    "民宿",
    "餐厅",
    "旗舰店",
)

_MOUNTAIN_SUFFIX_NOISE = ("店", "站", "路", "街", "镇", "村", "乡", "码头", "机场")


@dataclass(frozen=True)
class VenueArchetype:
    archetype: ArchetypeId
    tier: str
    visit_hours: float
    activity_load: int
    schedule_mode: str
    pairing_role: str  # 搭配角色：独立景点 / 宫殿后的观景点 / 上午优先


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in text for m in markers)


def _extract_typecodes(poi: dict[str, Any]) -> set[str]:
    raw = " ".join(
        str(poi.get(key, "") or "")
        for key in ("type", "typecode", "biz_type")
    )
    return {code for code in _re.findall(r"\d{6}", raw) if code}


def is_auxiliary_facility(name: str) -> bool:
    text = str(name or "").strip()
    return bool(text) and _has_any(text, _AUXILIARY_FACILITY_MARKERS)


def is_theme_park_poi(name: str, type_text: str = "", typecodes: set[str] | None = None) -> bool:
    """大型主题乐园/游乐园（约 6h）；不含普通城市公园、滨江公园、湿地公园。"""
    return _is_theme_park(name, type_text, typecodes)


def _is_theme_park(name: str, type_text: str = "", typecodes: set[str] | None = None) -> bool:
    text = str(name or "").strip()
    blob = f"{text} {str(type_text or '').strip()}"
    codes = typecodes or set()
    if not text and not codes:
        return False
    if is_auxiliary_facility(text):
        return False
    if any(marker in text for marker in _THEME_PARK_EXCLUDE):
        return False
    # 普通公园：仅「公园」无游乐园类型/品牌 → 非主题乐园
    if "公园" in text and not (codes & _AMUSEMENT_TYPECODES):
        if not any(marker in blob for marker in _THEME_PARK_MARKERS):
            return False
    if codes & _AMUSEMENT_TYPECODES:
        return True
    if any(marker in blob for marker in _THEME_PARK_MARKERS):
        return True
    if "游乐园" in blob or "主题乐园" in blob or "游乐场" in blob:
        return True
    return False


def _is_ordinary_city_park(name: str) -> bool:
    """市内常规公园（1.5–2h），与 theme_park / 整片山岳景区区分。"""
    if "公园" not in name:
        return False
    if _is_theme_park(name):
        return False
    if _has_any(
        name,
        (
            "风景名胜区",
            "风景区",
            "景区",
            "国家森林公园",
            "国家公园",
            "森林公园",
            "湿地公园",
            "海洋公园",
            "主题乐园",
            "游乐园",
        ),
    ):
        return False
    return True


def _distance_to_destination_km(poi: dict[str, Any]) -> float:
    try:
        return float(poi.get("distance_to_destination_km", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _spec_for(archetype: ArchetypeId, *, region_type: str = "city") -> ArchetypeSpec:
    spec = ARCHETYPE_REGISTRY[archetype]
    if region_type == "scenic_region" and archetype in {"scenic_half_day", "scenic_full_day"}:
        return ArchetypeSpec(
            spec.tier,
            min(9.0, round(spec.visit_hours + 0.5, 1)),
            spec.activity_load,
            spec.schedule_mode,
            spec.pairing_role,
        )
    return spec


def _is_city_square(name: str) -> bool:
    if "广场" in name and not _has_any(name, ("公园", "景区", "风景区")):
        return True
    if _has_any(name, ("大桥", "音乐喷泉", "摩天轮", "观景台")):
        return True
    return False


def _is_urban_park(name: str) -> bool:
    """城市登山/观景公园（非整片山岳景区）。"""
    if "公园" not in name:
        return False
    if _has_any(name, _LARGE_SCENIC_MARKERS):
        return False
    if _has_any(name, ("风景名胜区", "风景区", "景区", "国家森林公园", "湿地公园")):
        return False
    if _has_any(name, _URBAN_PARK_HINTS) or name.endswith("公园"):
        return True
    return False


def _match_famous_mountain_peak(name: str) -> ArchetypeId | None:
    """高德等只返回短名时，用知名山岳表识别（排除景山类城市公园）。"""
    text = str(name or "").strip()
    if not text or "山" not in text:
        return None
    if _has_any(text, _MOUNTAIN_POI_NOISE):
        return None
    if any(text.endswith(suffix) for suffix in _MOUNTAIN_SUFFIX_NOISE):
        return None

    for peak, tier in sorted(_FAMOUS_MOUNTAIN_TIERS.items(), key=lambda item: -len(item[0])):
        if text == peak:
            return tier
        if text.startswith(peak) and len(text) <= len(peak) + 6:
            return tier
    return None


def _is_water_experience(name: str) -> bool:
    if _has_any(name, ("游船", "游艇", "邮轮", "渡轮", "快艇", "帆船", "漂流船")):
        return True
    if "码头" in name and _has_any(name, ("游", "航")):
        return True
    if "海河" in name:
        return True
    return False


def _is_landmark_ride(name: str) -> bool:
    return _has_any(name, ("摩天轮", "之眼", "观景轮", "旋转木马", "游乐轮"))


def _is_urban_street_zone(name: str) -> bool:
    """城市风情街区/观光带，不是大山岳景区。"""
    if _has_any(name, ("风景名胜区", "国家森林公园", "大峡谷", "雪山")):
        return False
    return _has_any(
        name,
        ("古文化街", "文化街", "风情街", "风情区", "历史街区", "步行街", "老街", "古街", "坊", "里弄"),
    ) or (("风情" in name or "观光" in name) and _has_any(name, ("街", "区", "旅游", "小镇")))


def _lake_sea_false_positive(name: str) -> bool:
    return _is_water_experience(name)


def _is_city_hill_scenic(name: str) -> bool:
    """城市近郊名山：有登山与风景，但通常 3–4h 可完成（非整日大山）。"""
    if "山" not in name:
        return False
    if not _has_any(name, ("风景名胜区", "风景区", "景区")):
        return False
    if _has_any(
        name,
        (
            "国家森林公园",
            "国家地质公园",
            "国家公园",
            "雪山",
            "大峡谷",
            "冰川",
            "沙漠",
            "高原",
            "空中草原",
        ),
    ):
        return False
    if _has_any(name, _FULL_DAY_PEAK_TOKENS):
        return False
    return True


def _is_natural_half_or_full(name: str) -> ArchetypeId | None:
    if is_auxiliary_facility(name):
        return None
    if _lake_sea_false_positive(name):
        return None
    if _is_city_hill_scenic(name):
        return "scenic_city_hill"
    if _has_any(name, _LARGE_SCENIC_MARKERS):
        if _has_any(
            name,
            (
                "国家森林公园",
                "国家地质公园",
                "国家公园",
                "世界遗产",
                "大峡谷",
                "雪山",
                "冰川",
                "沙漠",
                "高原",
            ),
        ) or _has_any(name, _FULL_DAY_PEAK_TOKENS):
            return "scenic_full_day"
        return "scenic_half_day"
    if "草原" in name or _LAKE_SEA_RE.search(name):
        return "scenic_half_day"
    if "山" in name and _has_any(name, ("风景名胜区", "风景区", "景区", "国家公园", "森林公园")):
        if "国家森林公园" in name or "国家公园" in name or _has_any(name, _FULL_DAY_PEAK_TOKENS):
            return "scenic_full_day"
        if _is_city_hill_scenic(name):
            return "scenic_city_hill"
        return "scenic_half_day"
    return None


def _remote_nature_archetype(poi: dict[str, Any], name: str) -> ArchetypeId | None:
    """远郊自然型公园不能按市内街心公园处理。"""
    if is_auxiliary_facility(name):
        return None
    if not _has_any(name, _REMOTE_NATURE_PARK_MARKERS):
        return None
    distance = _distance_to_destination_km(poi)
    type_text = str(poi.get("type", "") or "")
    if distance >= 45 and _has_any(name, ("国家", "森林", "草原", "峡谷", "牧场", "徒步")):
        return "scenic_full_day"
    if distance >= 18 or "风景名胜" in type_text or _has_any(name, ("国家", "草原", "牧场", "徒步")):
        return "scenic_half_day"
    return None


def resolve_venue_archetype(name: str, *, region_type: str = "city") -> VenueArchetype:
    return resolve_venue_archetype_from_poi({"name": name}, region_type=region_type)


def resolve_venue_archetype_from_poi(
    poi: dict[str, Any],
    *,
    region_type: str = "city",
) -> VenueArchetype:
    text = str(poi.get("name", "") or "").strip()
    type_text = str(poi.get("type", "") or "").strip()
    typecodes = _extract_typecodes(poi)
    region = str(region_type or "city").strip().lower()

    archetype: ArchetypeId = "generic_standard"
    pairing = "standalone"

    if is_auxiliary_facility(text):
        archetype = "city_square"
    elif _is_theme_park(text, type_text, typecodes):
        archetype = "theme_park"
    elif (famous := _match_famous_mountain_peak(text)) is not None:
        archetype = famous
    elif (remote_nature := _remote_nature_archetype(poi, text)) is not None:
        archetype = remote_nature
    elif (natural := _is_natural_half_or_full(text)) is not None:
        archetype = natural
    elif _is_water_experience(text):
        archetype = "water_experience"
    elif _is_landmark_ride(text):
        archetype = "landmark_ride"
    elif _is_urban_street_zone(text):
        archetype = "street_district"
    elif _is_city_square(text):
        archetype = "city_square"
    elif _has_any(text, ("故宫博物院",)) or ("故宫" in text and "博物" not in text):
        archetype = "palace_museum"
        pairing = "morning_priority"
    elif _has_any(text, ("国家博物馆", "中国博物馆")) or _has_any(
        text, ("省博物馆", "市博物馆", "自治区博物馆")
    ):
        archetype = "museum_major"
        pairing = "morning_priority"
    elif _has_any(text, ("博物馆", "博物院")) or "博物" in text:
        archetype = "museum_major"
        pairing = "morning_priority"
    elif "瓷房子" in text:
        archetype = "heritage_site"
    elif _has_any(text, ("纪念馆", "陈列馆", "纪念园", "美术馆")):
        archetype = "memorial_hall"
        pairing = "morning_priority"
    elif _has_any(text, ("天坛", "地坛", "日坛", "月坛")) and "公园" in text:
        archetype = "heritage_park"
    elif _has_any(text, ("江滩", "滨江", "湖滨", "栈道")) and "公园" in text:
        archetype = "urban_park_view"
    elif _is_ordinary_city_park(text) or _is_urban_park(text):
        archetype = "urban_park_view"
        if text in _PALACE_VIEWPOINT_NAMES:
            pairing = "viewpoint_after_palace"
    elif "公园" in text:
        archetype = "heritage_park"
    elif _has_any(text, ("寺", "庙", "祠", "庵", "观")):
        archetype = "temple_garden"
    elif _has_any(text, ("古镇", "古城", "古街", "历史街区", "步行街", "老街", "巷")):
        archetype = "street_district"
    elif _has_any(text, ("长城", "城墙", "城楼")):
        archetype = "scenic_half_day"
    elif _has_any(text, ("景区", "风景区", "旅游景点")) and not text.endswith("旅游区"):
        archetype = "scenic_half_day"
    elif text.endswith("旅游区") and not _has_any(text, _LARGE_SCENIC_MARKERS):
        archetype = "street_district"
    elif "塔" in text or "阁" in text:
        archetype = "heritage_site"

    reg = _spec_for(archetype, region_type=region)
    pairing = reg.pairing_role if pairing == "standalone" else pairing
    mode: ScheduleMode = reg.schedule_mode
    if archetype == "generic_standard":
        mode = infer_schedule_mode({"name": text, "type": type_text})
    return VenueArchetype(
        archetype=archetype,
        tier=reg.tier,
        visit_hours=reg.visit_hours,
        activity_load=reg.activity_load,
        schedule_mode=mode,
        pairing_role=pairing,
    )


def _metrics_from_spec(spec: VenueArchetype, poi: dict[str, Any]) -> dict[str, Any]:
    composed = compose_visit_metrics(
        activity_load=spec.activity_load,
        activity_tier=spec.tier,
        poi=poi,
        typical_visit_hours=spec.visit_hours,
        schedule_mode=spec.schedule_mode,  # type: ignore[arg-type]
    )
    return {
        **composed,
        "venue_archetype": spec.archetype,
        "pairing_role": spec.pairing_role,
        "activity_load_source": "archetype",
    }


def metrics_from_archetype(name: str, *, region_type: str = "city") -> dict[str, Any]:
    return metrics_from_poi_archetype({"name": name}, region_type=region_type)


def metrics_from_poi_archetype(poi: dict[str, Any], *, region_type: str = "city") -> dict[str, Any]:
    spec = resolve_venue_archetype_from_poi(poi, region_type=region_type)
    return _metrics_from_spec(spec, poi)
