# 游览时长标准

**知识库 JSON 里不再保存每个景点的时长。**  
`destination_knowledge.json` 只保留：目的地元数据、`hotspots`（搜哪些种子景点）等。

## 运行时怎么有时长？

```
destination_knowledge.json (hotspots 种子名)
        ↓
visit_profiles_for_destination()  ← backend/knowledge/destination_catalog.py
        ↓
venue_archetype.py（景点类型：城市公园/国博/草原/知名山岳短名表…）→ guide_visit_estimate.py
        + data/curated_visit_profiles.json（名景校准；与 archetype 差 ≥1h 时以 archetype 为准）
        ↓
venue_schedule_policy.py（闭馆/停止入馆/排队/观景公园靠后）→ day_schedule 时间轴
```

## 两套数值

| 字段 | 含义 |
|------|------|
| `visit_hours` | 真实停留时间（时间轴） |
| `activity_tier` / `activity_load` | 分日装箱权重 |

## 搜到的 POI 怎么对上「设计好的时间」（命中率）

1. **名称清洗**：去掉「旗舰店 / 南门 / 停车场」等再匹配热点种子  
2. **三层匹配**：  
   - 对得上目的地热点或全国名景表 → `knowledge`  
   - 对不上但名字像博物馆/草原 → `guide`（导游规则，不是 2h 兜底）  
   - 实在不像旅游景点 → 高德类型规则  
3. **名景表**：`curated_visit_profiles.json` 已同步约 **1800** 个热点种子，全国通用  

同步名景表：`python scripts/sync_curated_from_hotspots.py`

## 维护方式

| 要改什么 | 改哪里 |
|----------|--------|
| 某一类景点默认时长 | `backend/planning/venue_archetype.py`（含 `_FAMOUS_MOUNTAIN_TIERS` 知名山岳短名） |
| 旧版导游规则兜底 | `backend/knowledge/guide_visit_estimate.py` |
| 单个景点精确时长 | `data/curated_visit_profiles.json` |
| 某城市搜哪些点 | `destination_knowledge.json` 的 `hotspots` |

**不要**再往 JSON 里写 `visit_profiles`（旧字段已清理完毕）。

## 档位参考

见 `guide_visit_estimate.py` 中 `TIER_HOURS_RANGE`：博物馆约 2–3.5h，草原湖泊约 5h，大山岳整日约 7–8h，大桥打卡约 1.2h。
