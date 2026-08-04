# VibeCut Agent 架构升级开发计划 v1.0

> 从纯手动编排到 Agent 自主编排 — 四阶段落地路线

## 前置条件

- [x] 知识库就绪 (knowledge/ 33篇笔记)
- [x] 架构设计完成 (docs/tech/AGENT_ARCHITECTURE.md)
- [x] 框架选型确认 (LangGraph + langchain-core + langchain-openai)
- [x] 当前版本打标 (v1.0.0-pre-agent)
- [x] 开发分支就绪 (agent-arch)

---

## Phase 1: 基础设施 (预计 3-5 天)

**目标：LangGraph 链路跑通，不影响现有功能。**

### 任务清单

```
□ 1.1 安装依赖
     pip install langchain-core langchain-openai langgraph
     验证: import langgraph 无报错

□ 1.2 创建 agent/ 目录结构
     vibecut-server/agent/
     ├── __init__.py
     ├── state.py          ← AgentState TypedDict
     ├── tools/
     │   ├── __init__.py
     │   └── search.py     ← semantic_search tool
     └── hello_agent.py    ← 最简 Agent 验证链路

□ 1.3 封装第一个 Tool
     把 server.py 的 _semantic_search() 封装为 @tool
     验证: Agent 能自主调用搜索工具并返回结果

□ 1.4 跑通最简 Agent
     写一个 HelloAgent: 输入主题 → 调搜索 → 返回结果
     验证: LangGraph StateGraph 编译、执行、stream 正常

□ 1.5 SSE 流式打通
     新增 POST /agent/run 端点
     前端能通过 SSE 接收 Agent 执行进度
     验证: 浏览器看到 Agent 的实时输出

□ 1.6 理论补充 (按需)
     阅读 knowledge/LangGraph框架.md
     阅读 LangGraph Quick Start 官方教程
```

### 验收标准

```bash
curl -X POST http://localhost:8765/agent/run \
  -d '{"goal": "搜索新东方教育理念相关的素材"}' \
  --stream

# 预期: SSE 流式返回 Agent 执行过程
# event: tool_start → 调用 semantic_search
# event: tool_end → 返回搜索结果
# event: done → Agent 完成
```

### 学习要点
- StateGraph 的三个核心概念 (State/Node/Edge)
- @tool 装饰器的工作原理
- astream_events() 的流式模型

---

## Phase 2: ScriptAgent (预计 7-10 天)

**目标：用 LangGraph 替代 run_pipeline()，功能等价。**

### 任务清单

```
□ 2.1 实现 ScriptAgent StateGraph
     节点:
     ├── understand_task   ← 意图理解 (LLM)
     ├── plan_narrative    ← 叙事设计 (调 planning_agent)
     ├── search_materials  ← 素材搜索 (调 search tool × N)
     ├── compose_script    ← 脚本编排 (调 editor_agent)
     ├── review_quality    ← 质量审核 (调 reviewer_agent)
     ├── auto_fix          ← 自动修复 (复用现有修复逻辑)
     └── human_review      ← 人类审批 (interrupt)

□ 2.2 实现条件路由
     review → [pass → human_review] / [fail → auto_fix → review]
     human_review → [approve → next] / [revise → plan_narrative]
     max 3 次自动修复循环

□ 2.3 实现 Checkpointer
     SqliteSaver 绑定 vibecut.db
     验证: 关闭浏览器 → 重新打开 → Agent 从中断点继续

□ 2.4 实现 Human-in-the-Loop
     human_review 节点调用 interrupt()
     前端展示审核面板 → 用户确认/修改 → resume

□ 2.5 前后端联调
     AgentDashboard 组件 (简易版)
     展示 Agent 执行进度 + 审核面板

□ 2.6 兼容性验证
     新旧两套并行运行:
     - 旧: POST /script/generate_script_stream (不变)
     - 新: POST /agent/run (新增)
     用户可选择使用哪套
```

### 验收标准

```
用户输入: "剪一个60秒视频讲新东方的教育理念"
  ↓
Agent 自动:
  1. 理解任务 → 确定目标时长、风格
  2. 设计结构 → 5段叙事
  3. 搜索素材 → 每段3-5个候选片段
  4. 编排脚本 → 压缩+排序
  5. 自我审核 → 评分+修复 (循环最多3次)
  6. 暂停 → 等待人类确认
  ↓
人类确认/修改 → Agent 继续 → 输出 segments
```

### 学习要点
- ConditionalEdge 的设计方法
- Checkpointer 的持久化原理
- interrupt/resume 的 HITL 机制
- State 的更新与传递

---

## Phase 3: Agentic RAG (预计 5-7 天)

**目标：ChatPanel 升级为多轮搜索 Agent。**

### 任务清单

```
□ 3.1 实现 SearchAgent StateGraph
     节点:
     ├── plan_search      ← LLM 拆分搜索策略
     ├── execute_search   ← 调用 BGE 搜索
     ├── evaluate_results ← LLM 评估结果质量
     └── synthesize       ← 汇总最佳结果

□ 3.2 实现搜索决策循环
     evaluate → [continue → plan_search] / [stop → synthesize]
     max 5 轮搜索
     Agent 自主决定搜索模式和参数

□ 3.3 替换 /chat 端点
     旧: POST /chat → _chat_intent → _search
     新: POST /agent/search → SearchAgent

□ 3.4 前端适配
     ChatPanel 展示 Agent 搜索过程
     "Agent: 搜了3个方向，找到8个候选，选了5个最佳的"
```

### 验收标准

```
用户在 ChatPanel 输入: "找苏大强在老宅发火的戏"
  ↓
Agent:
  Round 1: 搜"苏大强 老宅 愤怒" → 3个结果
  Agent: "还有回忆片段可能更合适"
  Round 2: 搜"苏大强 老宅 回忆 EP38" → 2个新结果
  Agent: "够了，5个最佳结果如下"
  ↓
返回: 5个结果 + 搜索策略说明
```

---

## Phase 4: 记忆与打磨 (预计 5-7 天)

**目标：长期记忆 + 偏好学习 + 完善体验。**

### 任务清单

```
□ 4.1 偏好记录
     SQLite 新表: user_preferences
     记录每次人工修改的 diff
     提取偏好模式 (hook时长/节奏/素材偏好)

□ 4.2 偏好应用
     planning prompt 自动注入偏好参数
     搜索时优先推荐符合偏好的素材类型

□ 4.3 错误处理
     Tool 调用失败 → 自动重试 + 降级
     LLM 返回异常 → 人工介入提示

□ 4.4 Agent 日志
     每个 Node 输出可读的决策日志
     "Agent: 审核不通过(节奏问题), 自动修复中..."

□ 4.5 性能优化
     并行搜索 (多段同时搜)
     模型预热优化
```

---

## 总时间线

```
Week 1: Phase 1 (基础设施)
        ████████████████░░░░░░░░░░░░░░░░  3-5天

Week 2-3: Phase 2 (ScriptAgent)
          ████████████████████████████████  7-10天

Week 3-4: Phase 3 (Agentic RAG)
          ████████████████████████████░░░  5-7天

Week 4-5: Phase 4 (记忆与打磨)
          ████████████████████████████░░░  5-7天

总计: 4-5 周
```

## 每个 Phase 的标签

```
Phase 1 完成 → git tag v2.0.0-alpha1
Phase 2 完成 → git tag v2.0.0-alpha2
Phase 3 完成 → git tag v2.0.0-alpha3
Phase 4 完成 → git tag v2.0.0-rc1
稳定后合入 main → git tag v2.0.0
```

---

## 回滚策略

- 每个 Phase 在新文件中开发 (agent/ 目录),不动现有代码
- 旧端点全部保留, Agent 端点新增
- 出问题: 前端切回旧端点, Agent 端点下线, 不影响使用
- 任何时候可 `git checkout v1.0.0-pre-agent` 回到纯手动版本

---

## 学习资源 (按需查阅)

| 遇到问题 | 查阅 |
|---------|------|
| LangGraph 概念不清 | `knowledge/LangGraph框架.md` |
| Agent 设计思路 | `knowledge/Agent核心概念.md` |
| Tool 怎么定义 | `knowledge/工具定义与MCP.md` |
| HITL 怎么实现 | `knowledge/人机协作HITL.md` |
| 架构参考 | `docs/tech/AGENT_ARCHITECTURE.md` |

---

> 文档版本: v1.0 | 创建日期: 2026-08-04 | 分支: agent-arch
