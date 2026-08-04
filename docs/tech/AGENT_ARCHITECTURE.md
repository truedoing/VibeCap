# VibeCut Agent-First 架构设计方案 v1.0

> 从 AI 辅助工具 → AI 剪辑师：全应用 Agent 化的完整架构蓝图

---

## 目录

1. [设计目标](#1-设计目标)
2. [当前架构 vs 目标架构](#2-当前架构-vs-目标架构)
3. [Agent 核心：Orchestrator StateGraph](#3-agent-核心orchestrator-stategraph)
4. [Tool 层：模块 → 工具封装](#4-tool-层模块--工具封装)
5. [Memory 与 State 设计](#5-memory-与-state-设计)
6. [Human-in-the-Loop](#6-human-in-the-loop)
7. [Agentic RAG：ChatPanel 升级](#7-agentic-ragchatpanel-升级)
8. [流式用户体验：astream_events](#8-流式用户体验astream_events)
9. [实施路线](#9-实施路线)
10. [代码骨架](#10-代码骨架)

---

## 1. 设计目标

### 从工具到 Agent 的三个跃迁

```
┌──────────────────────────────────────────────────────────────┐
│                      VibeCut v1.0 (当前)                      │
│                                                              │
│  人类操作:                 AI 辅助:                            │
│  "输入主题"     ─────────→  生成脚本 (SSE 流式)                │
│  "点精剪按钮"   ─────────→  精切引擎 (KEEP/CUT 标注)           │
│  "点导出"       ─────────→  CapCut 草稿                       │
│  "搜索镜头"     ─────────→  BGE 语义搜索 + ChatPanel           │
│                                                              │
│  人类决策 ~10 次/任务     AI 执行单个步骤                       │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    VibeCut Agent v2.0 (目标)                   │
│                                                              │
│  人类操作:                 Agent 自主:                         │
│  "剪一个60秒视频           ├── 理解任务意图                     │
│   讲新东方教育理念,        ├── 浏览素材, 分析内容质量            │
│   要有情感冲击力"          ├── 设计叙事结构                     │
│                           ├── 选择素材 + BGE 搜索              │
│                           ├── 生成脚本 (多轮自我审核)           │
│                           ├── 精切 (KEEP/CUT)                 │
│                           ├── 建时间轴                         │
│                           ├── 自我审片, 调整节奏               │
│                           ├── 导出 + 生成报告                  │
│                           └── 等待人类确认                     │
│                                                              │
│  人类决策 ~2 次/任务       Agent 自主决策 N 次                  │
│  (定义目标 + 最终确认)                                        │
└──────────────────────────────────────────────────────────────┘
```

### 设计原则

1. **渐进式 Agent 化**: 不是重写，是封装。现有每个模块保持独立，Agent 层是编排层
2. **人类在回路中**: Agent 可以做 80% 的决策，但关键节点（脚本审核、导出确认）必须人类确认
3. **可降级**: 任何时候可以退回到当前的手动模式 — 关闭 Agent，手动点击按钮
4. **可观察**: Agent 的每一步决策都有日志，人类可以理解它为什么这样做

---

## 2. 当前架构 vs 目标架构

### 2.1 当前: 人类编排 + AI 单步执行

```
┌─────────────────────────────────────────────────────────────┐
│  browser                         server                      │
│  ┌──────────┐                   ┌──────────────────────────┐│
│  │Planning  │── POST /script ──→│ script_agents.py          ││
│  │Desk      │     SSE ←────────│  run_pipeline()           ││
│  │          │                   │  planning_agent() →       ││
│  │  [生成]  │                   │  writer_agent() × N →     ││
│  │  [精剪]  │── POST /refine ──→│  editor_agent() →         ││
│  │  [导出]  │                   │  reviewer_agent() → loop  ││
│  └──────────┘                   └──────────────────────────┘│
│  ┌──────────┐                   ┌──────────────────────────┐│
│  │VibeEdit  │── GET /search ──→ │ server.py                 ││
│  │          │                   │  _semantic_search()       ││
│  │  搜索面板 │── POST /chat ──→  │  _chat_intent()           ││
│  └──────────┘                   └──────────────────────────┘│
│                                                              │
│  问题: 每个按钮 = 一次 API 调用, 人类是编排者                   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 目标: Agent 编排 + 人类监督

```
┌─────────────────────────────────────────────────────────────┐
│  browser                         server                      │
│                                                              │
│  ┌──────────────────────┐      ┌───────────────────────────┐│
│  │  Agent Dashboard      │      │  LangGraph Runtime         ││
│  │                      │      │                            ││
│  │  ┌────────────────┐  │ SSE  │  OrchestratorAgent         ││
│  │  │ 目标输入        │  │←────→│  ┌─────────────────────┐  ││
│  │  │ "剪60s教育视频" │  │      │  │ StateGraph          │  ││
│  │  └────────────────┘  │      │  │                     │  ││
│  │                      │      │  │ plan ──→ search ──→ │  ││
│  │  ┌────────────────┐  │      │  │   │                 │  ││
│  │  │ 实时进度        │  │      │  │   ├──→ write ──→   │  ││
│  │  │ ✅ 分析素材     │  │      │  │   │       │        │  ││
│  │  │ ✅ 设计结构     │  │      │  │   │       ├──→ edit│  ││
│  │  │ 🔄 选素材...    │  │      │  │   │       │    │   │  ││
│  │  │ ⏳ 生成脚本...  │  │      │  │   └───────┘    │   │  ││
│  │  └────────────────┘  │      │  │                 ▼   │  ││
│  │                      │      │  │    review ←────────  │  ││
│  │  ┌────────────────┐  │      │  │      │              │  ││
│  │  │ 审核节点        │  │      │  │      ├─ pass → END │  ││
│  │  │ [确认] [修改]   │──┼──────│→ │      └─ fail → edit│  ││
│  │  └────────────────┘  │      │  └─────────────────────┘  ││
│  │                      │      │                            ││
│  │  ┌────────────────┐  │      │  ┌─────────────────────┐  ││
│  │  │ 最终预览+导出   │  │      │  │  Tools               │  ││
│  │  └────────────────┘  │      │  │  search / refine /   │  ││
│  └──────────────────────┘      │  │  export / build_index │  ││
│                                 │  └─────────────────────┘  ││
│                                 └───────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Agent 核心：Orchestrator StateGraph

### 3.1 整体状态图

```
                    ┌─────────────┐
                    │   START     │
                    │ (接收目标)   │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ understand   │  ← 意图理解 + 素材预浏览
                    │ _task        │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ plan_        │  ← 叙事结构设计
                    │ narrative    │     (planning_agent 升级)
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ search_      │  ← BGE 搜索 + 素材选择
                    │ materials    │     (writer_agent × N 升级)
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ compose_     │  ← 脚本排序 + 压缩
                    │ script       │     (editor_agent 升级)
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ review_      │  ← 质量审核 + 分类修复
                    │ quality      │     (reviewer_agent 升级)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │ pass       │ fail        │
              ▼            ▼             │
    ┌──────────────┐  ┌──────────────┐  │
    │ human_review │  │ auto_fix     │──┘
    │ _script      │  │ (按问题分类    │  循环最多3次
    │ (等待确认)    │  │  定向修复)    │
    └──────┬───────┘  └──────────────┘
           │
    ┌──────┼──────┐
    │ 确认  │ 修改  │
    ▼      ▼
┌────────┐ ┌────────┐
│ refine │ │ 返回    │
│ _clips │ │ plan_   │
│ (精切) │ │ narrative│
└───┬────┘ └────────┘
    │
    ▼
┌────────┐
│ build_ │
│ timeline│  ← Elah 建轨
└───┬────┘
    │
    ▼
┌────────┐
│ self_  │
│ review │  ← Agent 自我审片
└───┬────┘
    │
    ▼
┌────────┐
│ export │  ← CapCut 导出
└───┬────┘
    │
    ▼
┌────────┐
│  END   │
└────────┘
```

### 3.2 State 定义

```python
from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
import operator

class ClipRef(TypedDict):
    """素材引用"""
    source: str       # 源文件名
    start: float      # 开始秒
    end: float        # 结束秒
    text: str         # 文本内容
    score: float      # 相关性分数

class NarrativeSection(TypedDict):
    """叙事段落"""
    role: str         # hook_tension | personal_reveal | empathy | evidence | insight
    point: str        # 核心论点
    duration: int     # 预估时长(秒)
    keywords: list[str]
    clips: list[ClipRef]

class AgentState(TypedDict):
    # ── 输入 ──
    goal: str                          # 用户目标: "剪一个60秒视频讲新东方教育理念"
    project_type: str                  # "drama" | "interview"

    # ── 任务理解 ──
    task_intent: dict                  # {topic, target_duration, style, focus_characters, ...}

    # ── 叙事设计 ──
    sections: list[NarrativeSection]   # 叙事结构 (planning 产出)

    # ── 素材搜索 ──
    material_pool: list[ClipRef]       # 搜索到的全部候选素材

    # ── 脚本编排 ──
    script: list[dict]                 # 最终脚本 (排序+压缩后)

    # ── 质量审核 ──
    review: dict                      # {scores, issues, verdict, revision_notes}
    retry_count: int                  # 修复尝试次数 (max 3)

    # ── 人类审批 ──
    human_approved: bool | None       # None=未审批, True=通过, False=需修改
    human_feedback: str               # 人类修改意见

    # ── 精切 ──
    refined_clips: list[dict]         # sub_clips with KEEP/CUT

    # ── 时间轴 ──
    timeline_ready: bool

    # ── 导出 ──
    export_path: str | None

    # ── 元信息 ──
    messages: Annotated[list, operator.add]  # 对话历史 (累积)
    errors: list[str]                        # 错误日志
    agent_notes: str                         # Agent 内部备注
```

### 3.3 条件路由

```python
def should_retry_or_human(state: AgentState) -> str:
    """审核后决定: 自动修复 / 人工审核 / 直接通过"""
    review = state["review"]
    no_critical = not any(i.get("severity") == "high" for i in review.get("issues", []))
    score_ok = review.get("scores", {}).get("overall", 0) >= 4

    if score_ok and no_critical and state["retry_count"] == 0:
        return "human_review"  # 首次+高质量 → 直接给人类看
    if state["retry_count"] >= 3:
        return "human_review"  # 超过重试次数 → 给人决定
    if not no_critical:
        return "auto_fix"      # 有严重问题 → 自动修复
    return "auto_fix"

def after_human_review(state: AgentState) -> str:
    """人类审批后"""
    if state["human_approved"]:
        return "refine_clips"
    return "plan_narrative"  # 人类不满意 → 重新设计

def after_self_review(state: AgentState) -> str:
    """Agent 自我审片后"""
    if state["agent_notes"] == "ok":
        return "export"
    return "search_materials"  # 回去重新搜素材、调脚本
```

---

## 4. Tool 层：模块 → 工具封装

### 4.1 工具清单

当前 VibeCut 的每个独立模块封装为一个 LangChain Tool：

```
┌──────────────────────────────────────────────────────────────┐
│  Tool                         原模块              输入 → 输出  │
├──────────────────────────────────────────────────────────────┤
│  browse_asr_content           classify + ASR      项目名 → 内容摘要 │
│  semantic_search              BGE + numpy          query → ClipRef[] │
│  keyword_search               n-gram 匹配          query → ClipRef[] │
│  hybrid_search                BGE + keyword        query → ClipRef[] │
│  deep_search                  query expansion      query → ClipRef[] │
│  analyze_transcript           LLM 分析             文本 → 结构化分析 │
│  generate_storyboard          LLM 分镜             解说词 → 视觉描述 │
│  match_dialogue               LLM 台词匹配         台词 → 原剧匹配   │
│  refine_segments              精切引擎             segments → sub_clips │
│  build_timeline               Elah 建轨            picks → timeline │
│  export_capcut                CapCut 导出          segments → 草稿路径 │
│  get_proxy_info               代理引擎             ep → proxy url │
│  get_episode_metadata         SQLite              ep → 集元数据   │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 工具定义示例

```python
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class SearchInput(BaseModel):
    query: str = Field(description="搜索查询文本，自然语言描述想要的画面/台词")
    mode: Literal["semantic", "keyword", "hybrid", "deep", "asr_first"] = "hybrid"
    limit: int = Field(default=15, ge=1, le=50)
    eps: list[int] | None = Field(default=None, description="限定剧集范围")

class SearchResult(BaseModel):
    ep: int
    start: float
    end: float
    description: str
    asr: str
    score: float
    source: str

@tool(args_schema=SearchInput)
def semantic_search(query: str, mode: str = "hybrid", limit: int = 15,
                    eps: list[int] | None = None) -> list[SearchResult]:
    """在已索引的 VLM/ASR 素材库中搜索视频片段。

    使用场景:
    - 找特定角色在某场景的画面
    - 找特定情绪的镜头（愤怒/悲伤/温馨）
    - 找特定台词或话题的片段
    - 找与解说词匹配的原剧镜头
    """
    # 调用现有的 _search() 逻辑
    results = _search_impl(query, mode=mode, limit=limit, eps=eps)
    return [SearchResult(**r) for r in results]

@tool
def browse_asr_content(project_name: str) -> dict:
    """浏览项目的 ASR 内容概况。

    使用场景:
    - Agent 在开始设计脚本前，需要了解素材有什么内容
    - "这个采访主要讲了哪些话题？"
    - "有哪些高重要度的金句？"
    """
    # 调用 classify_transcript + clean_interview 产出
    return _browse_impl(project_name)

@tool
def refine_segments(segments: list[dict], utterances: list[dict]) -> dict:
    """对粗段进行精切，输出 KEEP/CUT 标注的 sub_clips。

    输入 segments (粗段列表) 和 utterances (分类后的 ASR 句子)，
    返回带 sub_clips 和 refine_stats 的 segments。
    """
    from refine_segments import refine
    return refine(segments, utterances)

@tool
def export_to_capcut(segments: list[dict], project_name: str, task_name: str) -> str:
    """将 segments 导出为剪映草稿文件。

    返回: 剪映草稿目录路径
    """
    from export_capcut import export
    return export(segments, project_name, task_name)
```

### 4.3 Tool 绑定到 Agent

```python
from langgraph.prebuilt import ToolNode

# 工具注册表
VIBECUT_TOOLS = [
    browse_asr_content,
    semantic_search,
    keyword_search,
    hybrid_search,
    deep_search,
    analyze_transcript,
    generate_storyboard,
    match_dialogue,
    refine_segments,
    export_to_capcut,
    get_proxy_info,
    get_episode_metadata,
]

# LangGraph ToolNode — Agent 可以自主调用其中任意工具
tool_node = ToolNode(VIBECUT_TOOLS)
```

---

## 5. Memory 与 State 设计

### 5.1 三层记忆

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 1: 工作记忆 (Working Memory)                           │
│  范围: 当前任务                                                │
│  实现: LangGraph State (AgentState)                            │
│  内容: sections, clips, script, review, retry_count           │
│  生命周期: 单次任务                                            │
├──────────────────────────────────────────────────────────────┤
│  Layer 2: 会话记忆 (Session Memory)                            │
│  范围: 当前编辑 session                                        │
│  实现: LangGraph Checkpointer (SqliteSaver)                    │
│  内容: 完整 StateGraph 执行轨迹 + 中间状态                      │
│  生命周期: 跨请求、跨页面刷新生效                               │
│  能力: 中断恢复 — 用户关闭浏览器，明天打开继续                   │
├──────────────────────────────────────────────────────────────┤
│  Layer 3: 长期记忆 (Long-term Memory)                          │
│  范围: 跨任务、跨项目                                          │
│  实现: SQLite (vibecut.db) + embedding vector                  │
│  内容:                                                        │
│    - 用户偏好 (喜欢 insight 收尾、偏好快速节奏)                  │
│    - 成功案例 (高分脚本 → 留存 patterns)                        │
│    - 素材偏好 (苏大强老宅戏效果好 → 优先搜)                     │
│    - 修改历史 (人类常改什么 → 自动调整策略)                     │
│  生命周期: 永久                                                │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 Checkpointer 实现

```python
from langgraph.checkpoint.sqlite import SqliteSaver

# 使用现有的 vibecut.db，新增 agent_checkpoints 表
checkpointer = SqliteSaver.from_conn_string("vibecut.db")

# 编译 Graph 时绑定
app = workflow.compile(checkpointer=checkpointer)

# 执行 — thread_id 区分不同任务
config = {"configurable": {"thread_id": f"task_{task_name}"}}

# 流式执行
for event in app.astream(initial_state, config):
    yield event

# 中断恢复 — 同样的 thread_id，从上次断点继续
for event in app.astream(None, config):  # None = 继续上次
    yield event
```

### 5.3 长期记忆的偏好学习

```python
class UserPreferenceStore:
    """从历史任务中学习用户偏好"""

    def learn_from_feedback(self, task_id: str, human_modifications: dict):
        """
        human_modifications = {
            "accepted": ["s_0", "s_3", "s_5"],   # 人类保留的段
            "rejected": ["s_2"],                   # 人类删除的段
            "modified": {"s_1": "缩短了hook"},      # 人类修改的段
        }
        """
        # 分析模式:
        # - 人类总是删掉 >10s 的 hook → 偏好简短开头
        # - 人类总是保留 insight 结尾 → 偏好深度收尾
        # - 人类倾向选择 score>80 的 clip → 高质量阈值
        patterns = self._analyze_patterns(human_modifications)

        # 存入长期记忆
        for pattern in patterns:
            self._store_preference(pattern)

    def apply_preferences(self, state: AgentState) -> AgentState:
        """将学习到的偏好应用到当前任务"""
        prefs = self._load_preferences()

        # 自动调整 planning prompt 参数
        if prefs.get("prefer_short_hook"):
            # 自动减小 hook 段的目标时长
            for s in state["sections"]:
                if s["role"] == "hook_tension":
                    s["duration"] = min(s["duration"], 8)

        # 自动调整 search 偏好
        if prefs.get("favorite_locations"):
            # 优先搜索特定场景
            state["search_bias"] = prefs["favorite_locations"]

        return state
```

---

## 6. Human-in-the-Loop

### 6.1 审批节点设计

```python
def human_review_node(state: AgentState) -> dict:
    """暂停执行，等待人类审批。
    
    这个节点不会自动完成 — 它调用 interrupt() 暂停 Graph，
    等待外部 API 调用 resume。
    """
    # 准备审批材料
    review_material = {
        "topic": state["task_intent"]["topic"],
        "sections": [
            {
                "role": s["role"],
                "point": s["point"],
                "duration": s["duration"],
                "clips_preview": [c["text"][:80] for c in s["clips"][:3]],
            }
            for s in state["sections"]
        ],
        "script_preview": state["script"],
        "review": state["review"],
        "total_duration": sum(s["duration"] for s in state["sections"]),
    }

    # 推送到前端 (SSE)
    return {
        "agent_notes": "等待人工审核",
        "review_material": review_material,
    }
    # 调用后 LangGraph 自动暂停，等待 resume

# 前端调用 resume:
# POST /agent/resume { thread_id, action: "approve"|"revise", feedback: "..." }
```

### 6.2 审批流 API

```python
# 添加到 server.py
def _handle_agent_resume(self):
    """POST /agent/resume — 人类审批后恢复 Agent 执行"""
    data = json.loads(self._read_body())
    thread_id = data["thread_id"]
    action = data["action"]  # "approve" | "revise"
    feedback = data.get("feedback", "")

    config = {"configurable": {"thread_id": thread_id}}

    # 更新 State
    app.update_state(config, {
        "human_approved": action == "approve",
        "human_feedback": feedback,
    })

    # 恢复执行
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.end_headers()

    for event in app.astream(None, config):  # None = resume
        self._send_sse(event["type"], event["data"])
```

---

## 7. Agentic RAG：ChatPanel 升级

### 7.1 当前 vs 升级后

```
当前 ChatPanel:                         Agentic RAG:
                                        
每轮:                                  每轮:
  user msg                              user msg
    ↓                                     ↓
  LLM 精炼 query                        LLM 规划搜索策略
    ↓                                     ↓
  搜索 (1次)                            搜索 (可多次，不同模式)
    ↓                                     ↓
  返回结果                              评估结果质量
    ↓                                     ↓
  (无记忆)                              决定: 够了 / 换个方向 / 缩小范围
                                           ↓
                                        主动建议: "这些够了, 要不要看看?"
                                           ↓
                                        记住已搜过的、排除的方向
```

### 7.2 Agentic RAG StateGraph

```python
class SearchAgentState(TypedDict):
    messages: Annotated[list, operator.add]
    query: str
    search_history: list[dict]     # [{query, mode, results_count, timestamp}]
    current_results: list[dict]
    excluded_directions: list[str] # "不要室内", "不要愤怒"
    strategy: str                  # "explore" | "exploit" | "refine"
    final_results: list[dict]

def search_agent_graph():
    workflow = StateGraph(SearchAgentState)

    workflow.add_node("plan_search", plan_search_node)
    # → LLM 分析: "用户想要苏大强在老宅的戏, 已经搜了2次,
    #    结果偏少。换个方向: 搜具体集数 EP1-5"

    workflow.add_node("execute_search", execute_search_node)
    # → 调用 BGE search tool, 可能并行调多个 mode

    workflow.add_node("evaluate_results", evaluate_results_node)
    # → LLM 评估: "找到了5个, 其中3个相关度高。
    #    还缺一个院子里的镜头, 建议再搜'苏大强 老宅 院子'"

    workflow.add_node("synthesize", synthesize_node)
    # → 汇总所有搜索结果, 排序, 去重, 输出最佳列表

    workflow.add_conditional_edges(
        "evaluate_results",
        decide_next_action,
        {
            "search_more": "plan_search",   # 不够 → 再搜
            "synthesize": "synthesize",      # 够了 → 汇总
            "ask_user": END,                # 需要人类指导
        }
    )

    workflow.set_entry_point("plan_search")
    workflow.add_edge("plan_search", "execute_search")
    workflow.add_edge("execute_search", "evaluate_results")
    workflow.add_edge("synthesize", END)

    return workflow.compile()

def decide_next_action(state: SearchAgentState) -> str:
    """Agent 自主决定下一步"""
    # 超过5轮搜索 → 强制汇总
    if len(state["search_history"]) >= 5:
        return "synthesize"
    # 最近一次搜索无结果 → 问人类
    if state["current_results"] == [] and len(state["search_history"]) >= 2:
        return "ask_user"
    # 结果数量足够 → 汇总
    if len(state["current_results"]) >= 8:
        return "synthesize"
    # 还不够 → 继续搜
    return "search_more"
```

### 7.3 与现有 ChatPanel 的对比

| 维度 | 当前 ChatPanel | Agentic RAG |
|------|---------------|-------------|
| LLM 角色 | 精炼 query 字符串 | 规划搜索策略 + 评估 + 反思 |
| 搜索次数 | 每轮 1 次 | Agent 决定 (1-5次) |
| 状态 | 无 | 已搜历史、排除方向、策略变化 |
| 主动性 | 被动响应 | 主动建议新方向 |
| 工具选择 | 固定 asr_first/semantic | Agent 自主选择 mode |
| 跨轮记忆 | 6 轮文本 | 结构化 State + Checkpointer |

---

## 8. 流式用户体验：astream_events

### 8.1 从手动 SSE 到 LangGraph 流式事件

```python
# 当前: 手动推送 SSE
def _handle_generate_script_stream(self):
    self.send_header("Content-Type", "text/event-stream")
    emit = lambda step, msg, data: self.wfile.write(
        f"event: {step}\ndata: {json.dumps(data)}\n\n".encode()
    )
    run_pipeline(topic, content, emit_progress=emit)

# 升级: LangGraph astream_events()
async def _handle_agent_run(self):
    self.send_header("Content-Type", "text/event-stream")

    config = {"configurable": {"thread_id": self.thread_id}}

    async for event in app.astream_events(initial_state, config):
        # LangGraph 自动产出每个 Node 的开始/结束/Token 事件
        kind = event["event"]
        name = event["name"]

        if kind == "on_chat_model_stream":
            # LLM Token 级流式
            self._send_sse("token", {"text": event["data"]["chunk"].content})

        elif kind == "on_tool_start":
            self._send_sse("tool_start", {"tool": name, "input": event["data"].get("input")})

        elif kind == "on_tool_end":
            self._send_sse("tool_end", {"tool": name, "output_preview": str(event["data"].get("output"))[:200]})

        elif kind == "on_chain_start" and "review" in name:
            self._send_sse("progress", {"step": "review", "status": "审核脚本质量..."})

        elif kind == "on_chain_end" and name == "human_review":
            self._send_sse("awaiting_approval", event["data"]["output"]["review_material"])

    self._send_sse("done", {"status": "completed"})
```

### 8.2 前端事件消费

```jsx
// AgentDashboard.jsx
const [progress, setProgress] = useState([])
const [awaitingApproval, setAwaitingApproval] = useState(null)

async function runAgent(goal) {
  const resp = await fetch('/agent/run', {
    method: 'POST',
    body: JSON.stringify({ goal, project, task })
  })

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const lines = decoder.decode(value).split('\n')
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const event = JSON.parse(line.slice(6))

      switch (event.type) {
        case 'progress':
          setProgress(prev => [...prev, event.data])
          break
        case 'awaiting_approval':
          setAwaitingApproval(event.data)  // 显示审核面板
          break
        case 'token':
          // 实时显示 LLM 生成内容
          break
        case 'done':
          // 流程结束
          break
      }
    }
  }
}

function approve(feedback) {
  fetch('/agent/resume', {
    method: 'POST',
    body: JSON.stringify({ thread_id, action: 'approve', feedback })
  })
}
```

---

## 9. 实施路线

### Phase 1: 基础设施 (1-2 周)

```
目标: LangChain + LangGraph 引入，不影响现有功能

□ pip install langchain-core langchain-openai langgraph
□ 创建 vibecut-server/agent/ 目录
□ 封装 5 个核心工具 (search, browse, refine, export, proxy)
□ 现有代码零改动 — Agent 层是独立的叠加层
□ 写一个最简单的 "hello agent" 验证链路通
```

### Phase 2: 脚本 Agent (2-3 周)

```
目标: 用 LangGraph 替代 run_pipeline()，功能等价

□ 实现 ScriptAgent StateGraph
  □ understand_task node
  □ plan_narrative node (调 planning_agent)
  □ search_materials node (调 search tool)
  □ compose_script node (调 editor_agent)
  □ review_quality node (调 reviewer_agent)
  □ auto_fix node (复用现有修复逻辑)
  □ human_review node (interrupt)
□ 实现 /agent/run + /agent/resume API
□ 前端 AgentDashboard 基础 UI
□ 与现有 PlanningDesk 共存 (用户可选择手动/Agent模式)
```

### Phase 3: Agentic RAG (1-2 周)

```
目标: ChatPanel 升级为多轮搜索 Agent

□ 实现 SearchAgent StateGraph
  □ plan_search → execute_search → evaluate_results 循环
□ 替换现有 ChatPanel 的后端 /chat 逻辑
□ 前端 ChatPanel 展示 Agent 搜索过程
```

### Phase 4: 记忆与学习 (2-3 周)

```
目标: 长期记忆 + 偏好学习

□ SqliteSaver 持久化 Checkpoints
□ UserPreferenceStore 实现
□ 从历史任务中提取偏好 patterns
□ 偏好自动应用到 planning prompt
```

### Phase 5: 全自动模式 (按需)

```
目标: "一键成片" — 输入目标, Agent 产出成片

□ 端到端自动化 (理解 → 设计 → 搜索 → 剪辑 → 审片 → 导出)
□ self_review node (Agent 审自己的片子)
□ "Agent 剪辑导演" 人格 (主动提建议, 不只被动响应)
```

---

## 10. 代码骨架

### 10.1 目录结构

```
vibecut-server/
├── agent/                        ← 新增: Agent 层
│   ├── __init__.py
│   ├── orchestrator.py           ← OrchestratorAgent StateGraph
│   ├── state.py                  ← AgentState 定义
│   ├── tools/                    ← Tool 封装
│   │   ├── __init__.py
│   │   ├── search.py             ← BGE 搜索 tools
│   │   ├── browse.py             ← ASR 浏览 tool
│   │   ├── refine.py             ← 精切 tool
│   │   ├── export.py             ← CapCut 导出 tool
│   │   └── media.py              ← 代理/元数据 tools
│   ├── nodes/                    ← StateGraph 节点
│   │   ├── __init__.py
│   │   ├── understand.py         ← 意图理解
│   │   ├── plan.py               ← 叙事设计
│   │   ├── search_materials.py   ← 素材搜索
│   │   ├── compose.py            ← 脚本编排
│   │   ├── review.py             ← 质量审核
│   │   ├── fix.py                ← 自动修复
│   │   └── human.py              ← 人类审批
│   ├── memory/                   ← 记忆系统
│   │   ├── __init__.py
│   │   ├── checkpointer.py       ← SqliteSaver 配置
│   │   └── preferences.py        ← UserPreferenceStore
│   └── rag/                      ← Agentic RAG
│       ├── __init__.py
│       └── search_agent.py       ← SearchAgent StateGraph
│
├── server.py                     ← 修改: 添加 /agent/* 端点
├── script_agents.py              ← 保留: 原有逻辑不变
├── refine_segments.py            ← 保留
├── ... (其余文件不变)
```

### 10.2 orchestrator.py 骨架

```python
"""VibeCut Orchestrator Agent — 全应用 Agent 编排器"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from agent.state import AgentState
from agent.tools import VIBECUT_TOOLS
from agent.nodes import (
    understand_task,
    plan_narrative,
    search_materials,
    compose_script,
    review_quality,
    auto_fix,
    human_review,
    refine_clips,
    build_timeline,
    self_review,
    export_final,
)

def create_orchestrator(db_path: str = "vibecut.db"):
    """创建 VibeCut Orchestrator Agent"""

    # ── 构建 Graph ──
    workflow = StateGraph(AgentState)

    # 注册节点
    workflow.add_node("understand_task", understand_task)
    workflow.add_node("plan_narrative", plan_narrative)
    workflow.add_node("search_materials", search_materials)
    workflow.add_node("compose_script", compose_script)
    workflow.add_node("review_quality", review_quality)
    workflow.add_node("auto_fix", auto_fix)
    workflow.add_node("human_review", human_review)
    workflow.add_node("refine_clips", refine_clips)
    workflow.add_node("build_timeline", build_timeline)
    workflow.add_node("self_review", self_review)
    workflow.add_node("export_final", export_final)

    # 注册边
    workflow.set_entry_point("understand_task")
    workflow.add_edge("understand_task", "plan_narrative")
    workflow.add_edge("plan_narrative", "search_materials")
    workflow.add_edge("search_materials", "compose_script")
    workflow.add_edge("compose_script", "review_quality")

    workflow.add_conditional_edges(
        "review_quality",
        should_retry_or_human,
        {
            "human_review": "human_review",
            "auto_fix": "auto_fix",
        }
    )
    workflow.add_edge("auto_fix", "review_quality")  # 循环

    workflow.add_conditional_edges(
        "human_review",
        after_human_review,
        {
            "refine_clips": "refine_clips",
            "plan_narrative": "plan_narrative",
        }
    )

    workflow.add_edge("refine_clips", "build_timeline")
    workflow.add_edge("build_timeline", "self_review")

    workflow.add_conditional_edges(
        "self_review",
        after_self_review,
        {
            "export": "export_final",
            "search_materials": "search_materials",
        }
    )

    workflow.add_edge("export_final", END)

    # ── 编译 ──
    checkpointer = SqliteSaver.from_conn_string(db_path)
    app = workflow.compile(checkpointer=checkpointer)

    return app


# ── 全局单例 ──
_orchestrator = None

def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = create_orchestrator()
    return _orchestrator
```

### 10.3 server.py 新增端点

```python
# server.py 新增

def _handle_agent_run(self):
    """POST /agent/run — 启动 Agent 任务 (SSE)"""
    data = json.loads(self._read_body())
    goal = data["goal"]
    task_id = data.get("task_id", str(uuid.uuid4())[:8])

    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.end_headers()

    app = get_orchestrator()
    initial_state = {"goal": goal, "project_type": _project_type}

    config = {"configurable": {"thread_id": f"task_{task_id}"}}

    for event in app.astream(initial_state, config):
        for node_name, node_output in event.items():
            self._send_sse("node_complete", {
                "node": node_name,
                "output_preview": _summarize_output(node_output),
            })

    self._send_sse("done", {"task_id": task_id})

def _handle_agent_resume(self):
    """POST /agent/resume — 人类审批后继续 (SSE)"""
    data = json.loads(self._read_body())
    thread_id = data["thread_id"]
    action = data["action"]
    feedback = data.get("feedback", "")

    app = get_orchestrator()
    config = {"configurable": {"thread_id": thread_id}}

    app.update_state(config, {
        "human_approved": action == "approve",
        "human_feedback": feedback,
    })

    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.end_headers()

    for event in app.astream(None, config):
        for node_name, node_output in event.items():
            self._send_sse("node_complete", {
                "node": node_name,
                "output_preview": _summarize_output(node_output),
            })

    self._send_sse("done", {"thread_id": thread_id})
```

### 10.4 节点示例: plan_narrative

```python
# agent/nodes/plan.py

def plan_narrative(state: AgentState) -> dict:
    """叙事结构设计节点。
    
    这个节点封装了现有的 planning_agent()，
    但让它能被 Agent 自主调用和重试。
    """
    from script_agents import planning_agent
    from langchain_core.messages import SystemMessage, HumanMessage

    llm = ChatOpenAI(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        temperature=0.4,
    )

    system = (
        "你是 VibeCut 的叙事设计师。根据任务目标设计 5-8 段叙事结构。\n\n"
        f"当前偏好: {state.get('preferences', {})}\n"
        f"历史反馈: {state.get('human_feedback', '')}\n"
    )

    response = llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=f"任务: {state['goal']}\n素材分析: {state.get('task_intent', {})}")
    ])

    # 结构化输出
    sections = llm.with_structured_output(PlanningOutput).invoke(...)

    return {
        "sections": sections,
        "messages": [response],  # 自动累积到对话历史
    }
```

---

## 附录：关键决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| Agent 框架 | LangGraph | 有状态图、Checkpointer、HITL、流式事件全部内置 |
| 模型调用 | langchain-openai | DeepSeek 兼容 OpenAI API，无需额外适配 |
| 工具定义 | @tool decorator | LangChain 原生，自动生成 JSON Schema |
| Checkpointer | SqliteSaver | 复用现有 vibecut.db，零额外依赖 |
| 流式协议 | SSE + astream_events | 与现有 SSE 前端兼容，渐进升级 |
| 代码组织 | 新增 agent/ 目录 | 现有代码零改动，Agent 层纯叠加 |

---

> 文档版本: v1.0 | 生成日期: 2026-08-04
