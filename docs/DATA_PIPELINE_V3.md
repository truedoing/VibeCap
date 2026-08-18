# VibeCut 数据加工流程 v3.1 — VLM 三层推理

> 本文档描述**当前生效**的电视剧数据管线（字幕 → scene_map → VLM）。
> 旧 v2 架构（whisper ASR + cross_calibrate + clean_data）已废弃，见 [DATA_PIPELINE.md](./DATA_PIPELINE.md)，其脚本已不存在。

## 一、核心设计哲学：三层推理，各司其职

整条管线不是「让 VLM 看视频」，而是**先让便宜的文本 LLM 把剧情和结构理清楚，再让 VLM 只做它最擅长的画面理解**，从而把 VLM 调用量从每集 241 次压到 10-25 次。

```
字幕(SRT) ──→ DeepSeek 场记Agent ──→ scene_map (人物+地点+事件+情绪)
                                        │
                                        │ mood 锚定 + 时间边界 + 人物权威
                                        ▼
                                  VLM 画面分析 (2帧/场景)
                                        │
                                        ▼
                                  vlm_seg_cache_v3.json
```

三个关键分工原则：

1. **人物是谁 → scene_map 说了算**（VLM 不认人脸，认错配角是已知局限）
2. **情绪是什么 → scene_map mood 锚定**（VLM 只负责把 mood 落实到画面情绪强度）
3. **时间边界 → scene_map time_range**（VLM 采帧按这个边界取）

**核心收益**（v1.3 → v3.1）：

| 指标 | v1.3 (旧) | v3.1 (当前) | 变化 |
|---|---|---|---|
| VLM 调用/集 | 241 次 | 10-25 次 | ↓90% |
| Token/集 | 692K | 43K | ↓94% |
| 关键帧采样 | 首尾帧 | 1/3+2/3 位置 | 避免切点边界 |
| 情绪准确度 | VLM 独立判断 | scene_map mood 锚定 | 零情绪矛盾 |
| 人物识别 | VLM 认人脸 (~29% 错误) | scene_map 确定 (0% 错误) | ✅ |

---

## 二、数据流全景

```
源视频 1080p
   │  ffmpeg fps=1
   ├─→ frames/*.jpg (每秒1帧)
   │
   │  SRT 下载
   ├─→ subtitle_result.json ──┐
   │                           │
   │                           ▼
   │              DeepSeek (lib/scene_map.py)
   │              ├─ ep_synopsis.json  (宏观叙事索引, 结构化)
   │              └─ scene_map.json    (逐场景: 人物/地点/事件/情绪/时间)
   │                           │
   │                           │ mood锚定 + 时间边界 + 人物权威
   │                           ▼
   │              MiMo VLM (cli/analyze_episodes.py)
   │              └─ vlm_seg_cache_v3.json (逐场景: 画面/景别/情绪强度/动作)
   │                           │
   │                           ▼
   │              lib/vlm_cache.load() 合并两者 → 内存场景缓存
   │                           │
   │                           ├─→ lib/storyboard_match.py → 导演Agent分镜
   │                           └─→ cli/build_index.py → BGE语义索引 → /search
```

入口：`cli/analyze_episodes.py` 的 `analyze_episode()`，四步 `[1/4]`~`[4/4]`。

---

## 三、Step 1 — 字幕 (SRT)

读 `subtitle_result.json`（网上下载的 SRT，**已废弃本地 whisper ASR**）。这是整条管线的唯一文本源。

---

## 四、Step 2 — Scene Map（场记Agent，`lib/scene_map.py`）

两个产物，先概要后分段。

### 4.1 `ep_synopsis.json` — 宏观叙事索引（结构化，v3.1 新升级）

```json
{
  "theme": "本集核心主题（一句话）",
  "plot_arc": "起承转合概括（≤100字）",
  "character_arcs": [
    {"character": "苏明成", "arc": "从...到...的转变", "relations_change": ["与苏明玉和解"]}
  ],
  "key_conflicts": ["父子冲突", "兄妹误会"],
  "emotional_curve": ["紧张", "冲突", "和解", "温情"],
  "key_events": [
    {"event": "苏明成持刀阻婚", "time_range": [450, 570]}
  ]
}
```

**职责边界**：只做整集宏观概括，不碰 location/characters 逐场景字段（那是 scene_map 的）。`key_events.time_range` 是连接 synopsis 与 scene_map 的锚点，供下游从「关键事件」跳转到具体镜头。

**消费方**：导演Agent（`handlers/storyboard.py`）+ 编剧Agent（`agents/drama_script_agents.py`），统一经 `lib/synopsis.py` 的 `load_synopsis()`/`to_text()` 读取（双格式兼容旧纯文本）。

### 4.2 `scene_map.json` — 逐场景细粒度（场记Agent 核心产物）

DeepSeek 读「ASR + 概要」切出场景数组，每段：

```json
{"time_range":[60,120], "location":"苏明哲家客厅", "characters":["苏明哲","吴非"],
 "event":"吴非支持苏大强再婚...", "mood":"严肃"}
```

**Prompt 铁律**（`SCENE_MAP_PROMPT`）：
1. `event` 绝对不能为空（空则写"(少量对话)"/"(场景过渡)"）
2. `time_range` 间隔≤15s，场景 60-120s
3. `characters` 至少 1 人，不能空数组
4. **人名归一化铁律**：朱莉→朱丽、宋明成→苏明成、小菜→小蔡 等（ASR 同音字误识别纠正）
5. `location` 不能"未知"（从对话内容推断）
6. `mood` 从标准情绪表选

**后处理**（`build()` 内）：过滤异常段(15s~400s) → 排序 → 补 event/mood/location 空值 → `_fill_gaps` 补 >120s 空隙。失败降级到关键词规则 `_fallback`。

**人名归一化**：`lib/names.py` 是单一真相的 `NAME_MAP` + `normalize_names()`，被 `scene_map.py`（prompt + 生成后兜底）和 `cli/normalize_asr_names.py`（ASR 全量修复）共用。

---

## 五、Step 3 — 提帧 + 关键帧采样

- `extract_frames`：ffmpeg `fps=1`，每秒 1 帧。
- `pick_keyframes_for_segment`：每场景取 1-2 帧，**取 1/3 + 2/3 位置**，避开首尾切点边界（旧版取首尾帧恰好错过高潮动作，是已修复的坑）。

---

## 六、Step 4 — VLM 画面分析（`analyze_segment_vlm`）

每场景喂 2 帧 + scene_map 上下文给 MiMo-v2.5，输出**导演级结构化视觉元数据**：

```json
{"visual_summary":"≤80字画面描述", "shot_size":"中景", "composition":"双人",
 "angle":"平视", "emotional_tone":"愤怒", "intensity":5, "lighting":"暖调", "actions":["拍桌","对峙"]}
```

### 关键机制

| 机制 | 说明 |
|---|---|
| **mood 锚定** | scene_map 的 mood 作为指令注入，强制 `emotional_tone`/`intensity` 与事件基调一致（「情绪矛盾 22→0」的关键） |
| **人物权威在 scene_map** | `_chars` 直接取 `sm['characters']`，**不信任 VLM 人脸识别**（VLM 只分析画面，不负责人） |
| **片头跳过** | `time_range[0] < 60` 的段用降级默认值，不浪费 VLM |
| **MiMo 推理模型适配** | `content` 为空时 fallback 到 `reasoning_content`；max_tokens 4000 |
| **JSON 多层容错** | `_parse_vlm_json` 5 层降级：剥 `<thinking>` → 直接解析 → markdown 代码块 → `{}` 块 → 截断补全 → 正则逐字段 → 纯文本兜底 |

### 调用前 prompt 注入

```python
prompt = (
    f"角色={chars_str}  地点={loc_str}  事件={event_str}{mood_hint}\n"
    f"只用上述角色名，看不清就写衣色。\n"
    ...
)
```

**关键点**：调用前把 scene_map 的「角色+地点+事件+情绪」注入 prompt，`事件`字段本身含人名，所以 VLM 只要照着 event 复述，人名天然正确。**这是「柳青对了」的真正原因——算法喂对的，不是 MiMo 认对的。**

### 返回后人名兜底

```python
# 人物标签直接用 scene_map（权威），不信任 VLM 人脸识别
visible_chars = sm.get('characters', []) or []
```

---

## 七、产物落盘与消费

### 7.1 缓存格式 `vlm_seg_cache_v3.json`

key 是 scene_map 的**下标**（不是场景 id），逐段增量缓存（每分析一段 `json.dump` 一次，断点续跑）。

### 7.2 合并加载 `lib/vlm_cache.py:load()`

惰性把 46 集 `vlm_seg_cache_v3.json` + `scene_map.json` 合并成内存 `{ep: {scene_id: {...}}}`，每场景融合：

| 字段来源 | 字段 |
|---|---|
| scene_map | characters / location / event / mood / time_range |
| VLM | visual_summary / shot_size / composition / angle / emotional_tone / intensity / lighting / actions |

同时统计 `_char_counts` 角色出场次数。

### 7.3 分镜匹配 `lib/storyboard_match.py`

导演Agent 把解说词拆成 beats → shot query → 多维度评分：剧集锚定(三层权重) + 人物精确匹配 + 情绪冲突补偿 + 情绪关键词 + 强度 + 景别距离 + 地点模糊 + 动作滑窗。

### 7.4 语义索引 `cli/build_index.py`

合并后的场景描述喂 BGE，生成 `semantic_embeddings.npy`（29,797 × 768）+ `semantic_metas.json`，供 `/search`。

---

## 八、人名漂移评估结论（2026-08-18）

全量扫描 46 集 1511 场景，检查「`visual_summary` 里出现的人名是否在该场景 scene_map 的 `characters` 里」。

**原始计数「140 处场景外核心人名」严重注水**，精确分类后：

| 分类 | 数量 | 性质 |
|---|---|---|
| 台词提及（「打电话给苏明哲」） | ~97 | 无害，人被提及不在场 |
| 地点名误报（「苏明成家客厅」） | ~16 | 地名非人物 |
| 子串误报（「朱丽母亲」） | ~10 | 人名是更长词前缀 |
| scene_map 漏人（画面有但没列） | ~13 | VLM 反而对 |
| **真·VLM 认错** | **3-4** | 真正有害 |

**结论**：真正有害的 VLM 认错只有个位数（如 EP44 S2 把苏明玉/柳青认成老聂/苏大强）。人物身份由 `_chars`（直取 scene_map）保证，`visual_summary` 人名只作为软噪声参与情绪/动作关键词匹配，不改变选镜头。scene_map 漏人那批修了会踩「禁重切分」铁律，代价远超收益。**决定：不动数据。**

---

## 九、关键设计约束（不变量）

1. **scene_map 分段锁死铁律**：改人物/字段严禁重切分，否则 VLM 缓存（按下标存储）错位。
2. **VLM 只分析画面，不负责人**：人物权威 scene_map，`_chars` 直接取 scene_map.characters。
3. **现有的 46 集 scene_map / VLM 缓存 / 归一化 ASR 不重新生成**（除非另行决定）。
4. **ep_synopsis 结构化**：主题/弧线/冲突/情绪/关键事件，与 scene_map 分工（宏观 vs 细粒度）。

---

## 十、关键文件索引

| 文件 | 职责 |
|---|---|
| `cli/analyze_episodes.py` | 入口：字幕→scene_map→提帧→VLM |
| `lib/scene_map.py` | 场记Agent：`build_synopsis`(宏观) + `build`(scene_map) |
| `lib/names.py` | 人名归一化映射（单一真相） |
| `lib/synopsis.py` | 双格式 synopsis 加载器 + to_text |
| `lib/vlm_cache.py` | VLM 场景缓存懒加载（合并 scene_map+VLM） |
| `lib/storyboard_match.py` | 分镜匹配引擎（纯函数，多维度评分） |
| `cli/regenerate_synopsis.py` | ep_synopsis 结构化迁移工具 |
| `cli/normalize_asr_names.py` | ASR 人名全量修复 |
