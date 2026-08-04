---
name: vibecut-project-overview
description: VibeCut 项目核心信息 — 定位、架构、技术栈、当前状态
metadata:
  type: project
---

# VibeCut 项目概览

## 定位
VibeCut 是 AI 影视解说/口播剪辑台。技术本质：多模态素材理解（ASR + VLM）→ 语义索引（BGE）→ Agent 编排（LangGraph）→ 辅助剪辑决策。

## 最高准则：三位一体
- 🏗️ **系统 (System)**: 独特的、能跑的产品 — "唯一用视频剪辑教AI全栈开发的完整产品"
- 📚 **知识 (Knowledge)**: 最新、最深的技术积累 — knowledge/ 33篇笔记 + docs/tech/ 7份架构文档
- 💰 **商业 (Business)**: 最贴合市场的变现路径 — "AI全栈工程师实战培训课程"以 VibeCut 为教学案例
- 原则: 系统开发驱动知识积累 → 知识积累支撑商业价值 → 商业反馈反哺系统迭代

## 技术栈
- 后端: Python 3.12, http.server, SQLite, SSE
- AI模型: BGE-base-zh-v1.5, faster-whisper, DeepSeek-Chat, MiMo v2.5
- 前端: React 19, Vite 8, Tailwind 4, Elah (@elah/editor)
- 当前版本: v1.0.0-pre-agent (纯手动编排)
- 开发分支: agent-arch (Agent 化升级中)

## 目录结构
- vibecut-server/ — Python 后端
- vibecut-web/ — React 前端
- knowledge/ — Obsidian 知识库 (33篇笔记)
- docs/tech/ — 架构文档 (7份)
- projects/ — 项目配置

## 当前状态 (2026-08-04)
- 产品已改名 VibeCut (原 VIBECAP)
- v1.0.0-pre-agent 标签已打 (Agent 化前的架构快照)
- agent-arch 分支已创建，准备开始 Agent 架构升级
- Agent 化方案已完成设计论证
- 知识库体系已建立
- 商业化路线已分析，AI培训课程为主力方向

**Why:** 项目定位从"个人剪辑工具"升级为"AI应用开发教学产品"，需要系统架构 + 知识体系 + 商业路径三者协调。
**How to apply:** 所有开发决策参考三位一体原则；当前在 agent-arch 分支上工作。

## 关联
- [[vibecut-agent-upgrade-plan]] — Agent 升级计划
- [[vibecut-tech-stack]] — 技术栈详细
- [[vibecut-commercial-strategy]] — 商业化路线
