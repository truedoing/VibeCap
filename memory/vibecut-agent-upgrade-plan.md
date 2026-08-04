---
name: vibecut-agent-upgrade-plan
description: VibeCut Agent 架构升级计划 — 四阶段开发路线
metadata:
  type: project
---

# Agent 架构升级计划

## 目标
从纯手动编排 (run_pipeline) 升级为 Agent 自主编排 (LangGraph StateGraph)。

## 四阶段路线
1. **Phase 1 (3-5天): 基础设施** — 安装依赖、创建 agent/ 目录、封装第一个 Tool、跑通最简 Agent、SSE 流式打通
2. **Phase 2 (7-10天): ScriptAgent** — 用 LangGraph 替代 run_pipeline()，含 Checkpointer + HITL
3. **Phase 3 (5-7天): Agentic RAG** — ChatPanel 升级为多轮搜索 Agent
4. **Phase 4 (5-7天): 记忆与打磨** — 偏好学习 + 错误处理 + 日志 + 性能优化

## 技术选型
- Agent 框架: LangGraph (StateGraph + ConditionalEdge + Checkpointer + ToolNode)
- 模型调用: langchain-openai (DeepSeek 走 OpenAI 兼容 API)
- 工具定义: @tool decorator
- 状态持久化: SqliteSaver (复用 vibecut.db)
- 流式协议: SSE + astream_events()

## 关键原则
- Agent 层是叠加层，不动现有代码
- 新旧两套并行运行，可随时回退
- 每个 Phase 完成后打标签 (v2.0.0-alpha1/2/3/rc1)

## 分支
- 开发分支: agent-arch
- 稳定版本: main (v1.0.0-pre-agent)

**Why:** 当前手动编排模式无法实现 Agent 自主决策，需要升级架构以支持全流程自主运行。
**How to apply:** 按 Phase 1→2→3→4 顺序执行，每阶段有明确验收标准。详见 docs/tech/UPGRADE_PLAN.md。

## 关联
- [[vibecut-project-overview]] — 项目概览
- [[vibecut-tech-stack]] — 技术栈
