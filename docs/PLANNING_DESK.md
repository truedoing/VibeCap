# 编剧台 (Planning Desk) — 算法与功能文档

> v0.11.0 · 2026-08-03

## 定位

消费数据台产出的结构化 ASR，产出 `segments.json`（可直接交给分镜台或剪映导出）。

## 两条生成策略

### v3 搜索流水线 (`run_pipeline`)

**适用**: 电视剧（素材量大、多集跨时间、需要精确匹配画面）

**流程**: 策划师(LLM) → 文案师(BGE搜索) → 精编师(LLM压缩) → 审核师(LLM审核+累积修复)

```
Phase 1: Planning
  └─ planning_agent(topic, ASR) → sections[n] {role, point, duration, topic_keywords}

Phase 2: Writing (BGE语义搜索 + 全局时间跟踪)
  └─ 逐段搜索, 每段取 top-5 结果
      ├─ global_window_usage 计数器: 每个30s窗口被选一次扣分, 后续段落偏好冷门窗口
      ├─ topic_keywords 软过滤: 匹配的句排前面
      └─ oral_filler 源头拦截: 12条正则 + _clean_embedded_fillers()

Phase 3: Editing (时间感知LLM压缩)
  └─ editor_agent(rich, hook_indices, ending_indices) → kept_indices
      ├─ 输入: 时间分布摘要 + 🔒标记
      ├─ 输出: 压缩后的句子索引
      └─ 后编辑强制: enforce_time_diversity(final, max_per_window=2, max_nearby=3, proximity_sec=8)

Phase 4: Review (累积式修复, 非互斥)
  └─ 最多2轮重试, 每轮所有修复同时生效:
      ├─ 时间堆砌 → 邻近检测 + 桶限制 + 口语废句清理
      ├─ 收尾薄弱 → _search_insight_sentences() + 洞察句替换
      ├─ 主题漂移 → 强topic锚点 (evidence/proof ≥2关键词, hook/insight ≥1)
      └─ 素材不足 → 高重要度冷门窗口补充
```

**核心算法**:

#### 全局时间跟踪
```python
global_window_usage = {}  # {window_id: usage_count}
for section in sections:
    results = search(query)
    # 排序: kw_match优先 → 冷门窗口(5 - usage) → 语义分
    results.sort(key=lambda r: (not kw_match, -(5 - window_usage[w]), -score))
    # 更新使用计数
    window_usage[window_id] += 1
```

#### 邻近检测 (`_find_time_clusters`)
不依赖硬桶边界的聚类算法:
```python
# 按 source_start 排序, 找 proximity_sec 内的连续簇
# 簇大小 ≥ max_nearby 时触发, 保留 role_rank 最高的句子
cluster = []
for s in sorted_by_time:
    if gap < proximity_sec: cluster.append(s)
    else: process_cluster(cluster)
```

#### 口语废句过滤
12 条正则 + 嵌入废词清理:
- `"这句就不讲了"`, `"我就讲吧"`, `"讲到哪儿"`, `"自己组织一下"`
- `"我应该说"`, `"你可以试着讲"`, `"不知道这是不是内容"`

#### 强 Topic 锚点
```python
# evidence/proof 句需 ≥2 个关键词 (防止"我的校区"漂移到"新东方"主题)
if role in ('evidence', 'proof'):
    match = _topic_keyword_match(text, keywords, min_matches=2)
```

---

### v4 故事优先流水线 (`story_first_pipeline`)

**适用**: 口播采访（素材量小、不线性、后期补充或推翻前期）

**流程**: LLM 通读全部 ASR → 理解完整故事 → 一次性输出分组段落

```
输入: 299句 guest ASR (~6000字, DeepSeek 128K上下文)
处理: 单次 LLM 调用
输出: {story, sections[{role, title, clips[{text, source_start, source_end}]}]}
```

**算法要点**:

1. **全量理解**: 不拆段搜索。LLM 一次性看到全部 ASR，理解采访的完整脉络
2. **分组段落**: `section(clips, 2-5个)` — 每个段落是一个完整意思单元
3. **段落内连贯**: clips 来自 ASR 中本就相邻或逻辑相关的位置。保留"第一/第二/第三"编号
4. **段落间过渡**: 全部来自 ASR 原文。如果 ASR 中有"那第三个点""除了这个还有"等自然过渡句，就作为段的第一个 clip。找不到就硬切
5. **数据一致性**: LLM 看到全部数据点后自主选择一致的数值（不会出现"1000万 vs 3亿"矛盾）
6. **零 AI 生成**: 所有 highlight_text 必须来自 ASR 原文。过渡句也是从 ASR 找的

**对比**:

| | v3 搜索流水线 | v4 故事优先 |
|---|---|---|
| 策略 | 逐段搜索 → 拼句子 | 通读全文 → 设计故事 |
| LLM 调用 | 4-8 次 (策划+编辑+审核×N) | 1 次 |
| 耗时 | ~40s | ~12s |
| 输出结构 | 扁平句子列表 | 分组段落 → clips |
| 过渡句 | 无 | ASR 原文过渡 |
| 连贯性 | reviewer 修复 | LLM 一次性设计 |
| 典型问题 | 拼句不连贯、数据矛盾 | 依赖源素材质量 |

---

## API 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/script/generate_script_stream` | POST | v3 搜索流水线 (SSE) |
| `/script/generate_story_first` | POST | v4 故事优先 (SSE) |
| `/script/analyze_transcript` | POST | LLM 分析转写 |
| `/script/generate_from_outline` | POST | 根据大纲生成 segments |
| `/script/generate_script` | POST | 三步混编 (非SSE) |

## SSE 事件格式

```
event: progress
data: {"step":"planning","status":"running","msg":"策划师: 设计叙事结构..."}

event: progress
data: {"step":"writing","status":"running","msg":"搜索 1/8: 新东方..."}

event: complete
data: {"ok":true,"segments":[...],"total":22,"time_estimate":{...}}
```

## 前端状态

- `segments`: 当前脚本
- `genResult`: 生成结果 (sections, checks, bridges, notes, time_estimate)
- `genLog`: 进度日志列表
- `generating`: 生成中标志
