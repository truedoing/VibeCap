# VIBECAP 架构设计 v2

> 统一电视剧与口播采访的工作流。
> 2026-08-02 · 基于 杨老师教育 0801学习新东方 实践重构。

---

## 一、全局工作流

```
┌──────────────┬──────────────┬──────────────┬──────────────┐
│  Phase 1     │  Phase 2     │  Phase 3     │  Phase 4     │
│  数据台·初步  │  策划台       │  数据台·全面   │  沉浸剪辑台   │
│  (素材准备)   │  (撰写脚本)   │  (深度索引)    │  (剪辑导出)   │
├──────────────┼──────────────┼──────────────┼──────────────┤
│              │              │              │              │
│ LLM: 批量处理 │ LLM: 交互辅助 │ LLM: 批量校对 │ 纯工程        │
│ 让人能看懂素材 │ 人主导+AI配合  │ 让机器能搜素材 │ 画面匹配+组装 │
│              │              │              │              │
└──────────────┴──────────────┴──────────────┴──────────────┘
        ↑ 全流程 AI 贯穿，区别在于调用方式（批量 vs 交互）↑
```

Phase A 和 Phase B 都在数据台，但目的不同、时机不同：

| | Phase A (写前) | Phase B (写后) |
|---|---|---|
| **目的** | 人看懂素材 | 机器搜索素材 |
| **输入** | 原始视频 | segments.json (脚本) |
| **产出** | 可浏览的文案/摘要 | 语义索引 + 质量报告 |
| **电视剧** | ASR + VLM初步分析 | 解说ASR校对 + BGE索引 + 数据清洗 |
| **口播** | ASR + LLM分类 + LLM分段 | ASR校对 + BGE索引 + 质量评分 |

---

## 二、数据台：双阶段流水线

### 2.1 Phase A — 素材准备

```
电视剧流水线:                       口播流水线:
  analyze_episodes.py                classify_transcript.py
  ├─ 场景切分(10s)                   ├─ LLM分类 (content/meta/guide/filler)
  ├─ ASR转写(faster-whisper)         ├─ LLM分段 (5-8个主题组)
  └─ VLM分析(MiMo)                   └─ 生成标准化文案

                                      clean_interview_data.py (v0.11)
                                      ├─ LLM文本清洗 (去废词/口误)
                                      ├─ 说话人识别 (host/guest)
                                      └─ 输出 classified_enhanced.json

产出:                              产出:
  sources/ep{N}/                      sources_clean/
  ├─ asr_result.json                  ├─ classified.json          (分类后ASR)
  ├─ vlm_analysis.json                ├─ classified_enhanced.json (清洗+说话人)
  └─ scenes.json                      ├─ segmented.json           (分段后文案)
                                      └─ content_report.json      (内容分析)
```

**标准化文案格式 (segmented.json):**

```json
{
  "source": "学习新东方",
  "duration": 1152,
  "total_segments": 7,
  "groups": [
    {
      "title": "人才选拔与激励",
      "summary": "新东方人才选拔和激励策略",
      "start_sec": 103, "end_sec": 191,
      "lines": [
        {"start_sec": 116, "text": "他的人才选拔", "importance": 4},
        {"start_sec": 120, "text": "全是到985211的学校去设招实现的", "importance": 5}
      ]
    }
  ],
  "stats": {"content": 285, "meta": 55, "guide": 75, "filler": 52}
}
```

### 2.2 Phase B — 深度索引

```
电视剧流水线:                       口播流水线:
  cross_calibrate.py                 (分类结果已由LLM完成)
  ├─ ASR ↔ VLM 交叉校准              
  └─ 字幕提取                         
                                     
  clean_data.py                      build_interview_index.py (v0.11)
  ├─ ASR碎片合并                      ├─ 优先使用 enhanced 数据
  ├─ VLM场景智能合并                   ├─ speaker边界断开分块
  └─ 质量标记                          ├─ guest-only 建索引
                                       ├─ cleaned_text 编码
  build_index.py                       ├─ original_text 展示
  └─ BGE语义索引重建                    └─ BGE 768维 → .npy + .json

产出:                              产出:
  sources_clean/ep{N}/                sources_clean/
  ├─ asr_result.json                  ├─ classified_enhanced.json
  ├─ vlm_merged.json                  └─ ...
  └─ ...                             semantic_embeddings.npy (66单元, guest-only)
  semantic_index.npy/mmap             semantic_metas.json
  quality_report
```

**口播索引质量改进 (v0.11):**

| 指标 | 旧索引 | 新索引 |
|---|---|---|
| 数据源 | 原始 ASR (含主持废句) | enhanced (guest-only, cleaned) |
| 索引单元 | 73 条 (主持+嘉宾混合) | 66 条 (纯嘉宾, speaker边界断开) |
| 主持人污染 | "对""你讲吧""举个例子"混入搜索结果 | 零污染 |
| 模型加载 | 194s (HF mirror 超时) | 8s (离线模式) |

### 2.3 数据台 UI 支持

数据台页面需支持两个阶段的展示和触发：

```
数据台页面:

┌─ 项目概览 ───────────────────────────────┐
│ 项目名 | 类型 | 集数 | 索引状态 | 质量分    │
├──────────────────────────────────────────┤
│ 都挺好   drama   46集   ✓ 已索引   85分   │
│ 杨老师   interview 1集   ✓ 已索引   77分   │
└──────────────────────────────────────────┘

┌─ Phase A: 素材准备 ──────────────────────┐
│ [analyze] → [classify] → [segment]       │
│ 已处理: 1/1 集                            │
│ 运行 ▶                                    │
└──────────────────────────────────────────┘

┌─ Phase B: 深度索引 ──────────────────────┐
│ [calibrate] → [clean] → [build_index]    │
│ 状态: 未运行 (需先完成 Phase C 写脚本)       │
│ 运行 ▶                                    │
└──────────────────────────────────────────┘

┌─ 分集质量 ───────────────────────────────┐
│ EP1 学习新东方  77分  ASR=84 索引=25       │
│   碎片率 15% · 语义单元 73 · 内容占比 61%   │
└──────────────────────────────────────────┘
```

---

## 三、策划台：通用脚本工厂

### 3.1 定位

策划台消费数据台 Phase A/B 的产出，生产 segments.json。提供**两条生成策略**，用户按场景选择。

### 3.2 两条流水线

#### v3 搜索流水线 (run_pipeline) — 电视剧/有索引的场景

```
策划师(LLM) → 文案师(BGE搜索) → 精编师(LLM压缩) → 审核师(LLM审核+修复)
                    ↕
              BGE 语义索引
```

**适用**: 电视剧（素材量大、时间跨度大、需要精确搜索匹配画面）

**算法要点**:
- **全局时间跟踪**: 搜索阶段累计每个 30s 窗口的使用次数，后续段落偏好冷门窗口
- **邻近检测** (`_find_time_clusters`): 不依赖硬桶边界。15s 间隔内 ≥3 句即触发去重
- **桶限制** (`max_per_window=2`): 每个 30s 窗口最多保留 2 句
- **口语废句过滤**: 12 条正则（"我就讲吧""这句就不讲了"等）+ 嵌入废词清理
- **强 topic 锚点**: evidence/proof 句需 ≥2 个关键词匹配（防止个人案例漂移到主题分析）
- **累积式修复**: 时间堆砌+收尾薄弱+主题漂移+素材不足 同时修（非互斥 elif）

**API**: `POST /script/generate_script_stream` (SSE 流式)

#### v4 故事优先流水线 (story_first_pipeline) — 口播采访

```
LLM 通读全部 ASR → 理解完整故事 → 一次性输出分组段落脚本
```

**适用**: 口播采访（素材量小、不线性、需要理解全局脉络后才能组织故事）

**算法要点**:
- **单次 LLM 调用**: 输入 299 句 guest ASR (~6000字)，输出分组段落结构
- **分组段落**: `section(clips, 2-5个)` — 每个段落是一个完整意思单元
- **段落内连贯**: clips 来自 ASR 中本就相邻或逻辑相关的位置，保留"第一/第二/第三"编号
- **段落间过渡**: 全部来自 ASR 原文（0 句 AI 生成）。找不到过渡就硬切
- **数据一致性**: LLM 看到全部数据点后自主选择一致的数值，不依赖下游修复

**API**: `POST /script/generate_story_first` (SSE 流式, ~12s 完成)

**对比**:

| | v3 搜索流水线 | v4 故事优先 |
|---|---|---|
| 策略 | 逐段搜索 → 拼句子 | 通读全文 → 设计故事 |
| 调用次数 | 4-8 次 LLM + 8 次 BGE | 1 次 LLM |
| 耗时 | ~40s | ~12s |
| 段落结构 | 扁平句子列表 | 分组段落（section → clips） |
| 过渡句 | 无 | ASR 原文过渡 |
| 连贯性 | 依赖 reviewer 修复 | LLM 一次性设计 |
| 适用 | 电视剧（多集、多镜头） | 口播采访（单文件、单镜头） |

### 3.3 素材面板

```
电视剧模式                        口播模式
──────────────────────────────────────────
数据源:                           数据源:
  sources/ep{N}/                    sources_clean/
  ├─ ASR台词浏览器                   ├─ classified_enhanced.json
  ├─ VLM画面描述                     ├─ 按 speaker 筛选 (guest/host)
  └─ 语义搜索 (keyword/semantic)     ├─ 按 importance 筛选 (4-5星)
                                      └─ 语义搜索 (guest-only 索引)
```

### 3.4 脚本编辑器

每个 segment 结构:
```
seg_id, highlight_text (核心内容: 台词/原话)
source_start / source_end (素材时间戳)
narrative_role (hook_tension/empathy/evidence/insight/...)
edit_type (trim/merge/ai_generated)
topic (主题标签), note (注释)
```

---

## 四、沉浸剪辑台：通用画面组装

```
消费 segments.json，按项目类型选择策略:

电视剧:
  narration_text → BGE语义搜索 → VLM画面匹配 → Elah 4轨
  4轨: 原声主镜头 | 原声音频 | 补充镜头 | 旁白TTS

口播:
  highlight_text → 源视频时间戳定位 → 跳切串联
  可走两条路径:
    A. Elah编辑器 (同电视剧)
    B. CapCut自动导出 (export_capcut.py)
```

---

## 五、目录结构

```
VIBECAP/
├── vibecap-server/
│   ├── server.py
│   ├── db.py
│   ├── script_agents.py           ← 策划台 AI Agent (v3搜索+v4故事优先)
│   ├── analyze_episodes.py        ← 电视剧 Phase A
│   ├── classify_transcript.py     ← 口播 Phase A: LLM 分类
│   ├── segment_transcript.py      ← 口播 Phase A: LLM 分段
│   ├── clean_interview_data.py    ← 口播 Phase A: 清洗+说话人
│   ├── cross_calibrate.py         ← 电视剧 Phase B
│   ├── clean_data.py              ← 电视剧 Phase B
│   ├── build_index.py             ← 电视剧 Phase B (BGE)
│   ├── build_interview_index.py   ← 口播 Phase B (BGE, speaker-aware)
│   └── export_capcut.py           ← 口播 CapCut导出
│
├── vibecap-web/
│   └── src/
│       └── pages/
│           ├── DataDesk.jsx        ← 双阶段流水线UI
│           ├── PlanningDesk.jsx    ← 通用脚本工厂
│           └── VibeEdit.jsx        ← 通用剪辑台
│
├── projects/
│   ├── 都挺好.json
│   └── 杨老师教育.json
│
├── 都挺好/                         ← 电视剧项目
│   ├── sources/ep{N}/             ← Phase A 产出 (原始ASR+VLM)
│   ├── sources_clean/ep{N}/       ← Phase B 产出 (清洗后)
│   ├── proxies/                   ← 540p代理
│   ├── semantic_index.*           ← BGE索引
│   ├── characters.json
│   └── tasks/
│
└── 杨老师教育/                     ← 口播项目
    ├── sources/                    ← Phase A 产出 (原始ASR)
    ├── sources_clean/              ← Phase B 产出
    │   ├── classified.json         ← LLM分类后
    │   ├── segmented.json          ← LLM分段后 (标准化文案)
    │   ├── content_report.json     ← 内容分析
    │   ├── semantic_embeddings.npy ← BGE索引 (73单元)
    │   └── semantic_metas.json
    ├── proxies/
    └── tasks/
        └── 0801学习新东方/
            ├── segments.json       ← 策划台产出
            └── 素材clips/
```

---

## 六、重构计划

### Phase 2-1: 创建口播数据台流水线

```
1. classify_transcript.py
   输入: sources/asr_*.json
   处理: LLM分块分类 (content/meta/guide/filler)
   输出: sources_clean/classified.json

2. segment_transcript.py  
   输入: sources_clean/classified.json
   处理: LLM采样 + 主题分组
   输出: sources_clean/segmented.json

3. 更新 db.py — 注册流水线步骤
4. 更新 DataDesk.jsx — 支持双阶段UI
5. 更新 server.py — 添加流水线API端点
```

### Phase 2-2: 策划台素材面板适配

```
1. PlanningDesk.jsx 加载 segmented.json (替代当前零散的静态文件)
2. 素材面板按 project.type 切换数据源
3. 移除策划台内的 LLM 调用逻辑 (移到数据台)
```

### Phase 2-3: 整合 Phase B 口播流水线

```
1. build_interview_index.py 已就绪
2. 集成到 server.py 数据台流水线
3. 对接 Phase B 触发逻辑 (脚本完成后)
```

---

> 最后更新：2026-08-03 · v0.11.0
