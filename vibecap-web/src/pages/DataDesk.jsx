import { useState, useEffect } from 'react'
import { useProject } from '../context/ProjectContext'
import { BarChart3, Database, Shield, TrendingUp, Tv, Loader2, Play, CheckCircle2, XCircle, Clock, Search, Brush, Cpu, HardDrive } from 'lucide-react'

// ── 质量色 ──
function qualityColor(score) {
  if (score >= 75) return 'text-green-400'
  if (score >= 55) return 'text-yellow-400'
  return 'text-red-400'
}
function qualityBg(score) {
  if (score >= 75) return 'bg-green-500'
  if (score >= 55) return 'bg-yellow-500'
  return 'bg-red-500'
}
function qualityLabel(score) {
  if (score >= 75) return '良好'
  if (score >= 55) return '一般'
  return '需优化'
}

// ── 分集质量条 ──
function EpQualityBar({ ep, report, indexed }) {
  const score = report?.overall_score || 0
  const summary = report?.summary || ''
  const asrScore = report?.asr_score || 0
  const vlmScore = report?.vlm_score || 0

  return (
    <div className="flex items-center gap-3 py-2.5 px-3 rounded-lg hover:bg-accent/30 transition-colors">
      <span className="text-xs font-mono text-muted-foreground w-10 shrink-0">
        EP{ep}
      </span>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <div className="flex-1 h-1.5 rounded-full bg-secondary overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${qualityBg(score)}`}
              style={{ width: `${score}%` }}
            />
          </div>
          <span className={`text-xs font-mono font-medium ${qualityColor(score)} w-10 text-right`}>
            {score}分
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-muted-foreground">
            ASR {asrScore} · VLM {vlmScore}
          </span>
          {summary && summary !== '数据质量良好' && (
            <span className="text-[10px] text-yellow-400/80 truncate">{summary}</span>
          )}
          {!indexed && (
            <span className="text-[10px] text-red-400">未索引</span>
          )}
        </div>
      </div>

      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
        score >= 75 ? 'bg-green-500/10 text-green-400 border-green-500/20' :
        score >= 55 ? 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' :
        'bg-red-500/10 text-red-400 border-red-500/20'
      } shrink-0`}>
        {qualityLabel(score)}
      </span>
    </div>
  )
}

// ── 加工步骤图标 ──
const stepIcons = {
  pending: <Clock size={14} className="text-muted-foreground/40" />,
  running: <Loader2 size={14} className="animate-spin text-blue-400" />,
  done: <CheckCircle2 size={14} className="text-green-400" />,
  failed: <XCircle size={14} className="text-red-400" />,
}

export default function DataDesk() {
  const { taskId } = useProject()
  const [quality, setQuality] = useState(null)
  const [loading, setLoading] = useState(true)

  // 加工面板状态
  const defaultSteps = [
    { id: 'analyze', label: '分析剧集', status: 'pending', progress: 0, detail: '', elapsed: 0, log_lines: [] },
    { id: 'clean',   label: '数据清洗', status: 'pending', progress: 0, detail: '', elapsed: 0, log_lines: [] },
    { id: 'build',   label: '重建索引', status: 'pending', progress: 0, detail: '', elapsed: 0, log_lines: [] },
    { id: 'migrate', label: '导入数据库', status: 'pending', progress: 0, detail: '', elapsed: 0, log_lines: [] },
  ]
  const [selectedEps, setSelectedEps] = useState([])
  const [procTaskId, setProcTaskId] = useState(null)
  const [procSteps, setProcSteps] = useState(defaultSteps)

  // 从 quality 数据中获取所有集数及其状态
  const allEpisodes = quality?.episodes || []
  const hasData = (ep) => {
    const e = allEpisodes.find(e => e.ep_number === ep)
    return e && (e.asr_raw_count > 0 || e.vlm_scene_count > 0)
  }

  useEffect(() => {
    fetch('/data/quality')
      .then(r => r.json())
      .then(setQuality)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [taskId])

  // 轮询加工进度
  useEffect(() => {
    if (!procTaskId) return
    const timer = setInterval(() => {
      fetch(`/data/process_status?task_id=${procTaskId}`)
        .then(r => r.json())
        .then(data => {
          if (data.steps) setProcSteps(data.steps)
          // 全部完成或失败则停止轮询
          const allDone = data.steps?.every(s => s.status === 'done' || s.status === 'failed')
          if (allDone) {
            clearInterval(timer)
            // 刷新质量报告
            fetch('/data/quality').then(r => r.json()).then(setQuality)
          }
        })
        .catch(() => {})
    }, 1500)
    return () => clearInterval(timer)
  }, [procTaskId])

  const startProcess = () => {
    if (selectedEps.length === 0) return
    const eps = [...selectedEps].sort((a, b) => a - b)
    // 重置为初始状态，更新第一步标签
    setProcSteps(defaultSteps.map(s =>
      s.id === 'analyze' ? { ...s, label: `分析 EP${eps.join(',')}` } : { ...s }
    ))
    fetch('/data/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ episodes: eps }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) setProcTaskId(data.task_id)
      })
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 size={24} className="animate-spin text-muted-foreground" />
      </div>
    )
  }

  const summary = quality?.summary || {}
  const reports = quality?.reports || []
  const episodes = quality?.episodes || []

  const avgScore = reports.length > 0
    ? Math.round(reports.reduce((s, r) => s + r.overall_score, 0) / reports.length)
    : 0

  return (
    <div className="flex-1 flex flex-col overflow-auto bg-background">
      <div className="max-w-3xl mx-auto w-full p-6 space-y-6">

        {/* ── Header ── */}
        <div>
          <h1 className="text-lg font-bold text-foreground flex items-center gap-2">
            <Shield size={18} className="text-primary" />
            数据台
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            {summary.total_eps || 0} 集已分析 · {summary.total_indexed || 0} 条索引 · 平均质量 {avgScore} 分
          </p>
        </div>

        {/* ── 概览卡片 ── */}
        <div className="grid grid-cols-4 gap-3">
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center gap-2 mb-1">
              <Tv size={14} className="text-blue-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">已索引</span>
            </div>
            <span className="text-2xl font-bold text-foreground">{summary.indexed_eps || 0}</span>
            <span className="text-xs text-muted-foreground ml-1">/ {summary.total_eps || 0} 集</span>
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center gap-2 mb-1">
              <Database size={14} className="text-purple-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">索引条目</span>
            </div>
            <span className="text-2xl font-bold text-foreground">{summary.total_indexed || 0}</span>
            <span className="text-xs text-muted-foreground ml-1">条</span>
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center gap-2 mb-1">
              <TrendingUp size={14} className="text-green-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">平均质量</span>
            </div>
            <span className={`text-2xl font-bold ${qualityColor(avgScore)}`}>{avgScore}</span>
            <span className="text-xs text-muted-foreground ml-1">分</span>
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center gap-2 mb-1">
              <BarChart3 size={14} className="text-yellow-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">字幕提取</span>
            </div>
            <span className="text-2xl font-bold text-foreground">{summary.total_subtitles || 0}</span>
            <span className="text-xs text-muted-foreground ml-1">条</span>
          </div>
        </div>

        {/* ── 分集质量 ── */}
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
            <Database size={14} className="text-muted-foreground" />
            <h3 className="text-sm font-medium text-foreground">分集数据质量</h3>
            <span className="text-[10px] text-muted-foreground ml-auto">
              加权: ASR 35% + VLM 40% + 字幕 10% + 索引 15%
            </span>
          </div>
          <div className="divide-y divide-border/50 px-2">
            {episodes.length === 0 ? (
              <p className="text-xs text-muted-foreground py-8 text-center">暂无数据</p>
            ) : (
              episodes.map(ep => {
                const report = reports.find(r => r.ep_number === ep.ep_number)
                return (
                  <EpQualityBar
                    key={ep.ep_number}
                    ep={ep.ep_number}
                    report={report}
                    indexed={ep.indexed}
                  />
                )
              })
            )}
          </div>
        </div>

        {/* ── 数据加工 ── */}
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
            <Cpu size={14} className="text-muted-foreground" />
            <h3 className="text-sm font-medium text-foreground">数据加工流水线</h3>
            <span className="text-[10px] text-muted-foreground">
              analyze → clean → build_index → migrate
            </span>
          </div>
          <div className="p-4 space-y-4">
            {/* 剧集选择 + 操作按钮 */}
            <div className="space-y-2">
              {/* 剧集网格 */}
              <div className="flex flex-wrap gap-1 max-h-28 overflow-y-auto custom-scrollbar">
                {allEpisodes.map(ep => {
                  const isSelected = selectedEps.includes(ep.ep_number)
                  const hasAnalysis = hasData(ep.ep_number)
                  return (
                    <button
                      key={ep.ep_number}
                      disabled={procSteps.some(s => s.status === 'running')}
                      onClick={() => {
                        setSelectedEps(prev =>
                          prev.includes(ep.ep_number)
                            ? prev.filter(e => e !== ep.ep_number)
                            : [...prev, ep.ep_number]
                        )
                      }}
                      className={`w-9 h-6 rounded text-[11px] font-mono transition-all border flex items-center justify-center ${
                        isSelected
                          ? 'bg-blue-500/20 text-blue-400 border-blue-500/40'
                          : hasAnalysis
                            ? 'bg-card text-foreground/70 border-green-500/30 hover:border-green-500/50'
                            : 'bg-secondary text-muted-foreground border-border hover:border-primary/30 hover:text-foreground'
                      } disabled:opacity-50`}
                    >
                      {ep.ep_number}
                    </button>
                  )
                })}
              </div>

              {/* 操作行 */}
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSelectedEps(allEpisodes.map(e => e.ep_number))}
                  disabled={procSteps.some(s => s.status === 'running')}
                  className="text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-50"
                >
                  全选
                </button>
                <button
                  onClick={() => setSelectedEps([])}
                  disabled={procSteps.some(s => s.status === 'running')}
                  className="text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-50"
                >
                  清空
                </button>
                <span className="text-[10px] text-muted-foreground/50">|</span>
                <span className="text-[10px] text-muted-foreground">
                  已选 <span className="text-foreground font-medium">{selectedEps.length}</span> 集
                  {selectedEps.length > 0 && (
                    <span className="text-muted-foreground/50 ml-1">
                      ({selectedEps.sort((a,b)=>a-b).slice(0,5).join(',')}{selectedEps.length > 5 ? '...' : ''})
                    </span>
                  )}
                </span>
                <div className="flex-1" />
                <button
                  onClick={startProcess}
                  disabled={selectedEps.length === 0 || procSteps.some(s => s.status === 'running')}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-40 hover:opacity-90 transition-opacity"
                >
                  {procSteps.some(s => s.status === 'running') ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Play size={14} />
                  )}
                  开始加工
                </button>
              </div>
            </div>

            {/* ── 工作流管线图 ── */}
            <div className="space-y-0">
              <div className="flex items-start justify-center px-2 py-1">
                {procSteps.map((step, i) => {
                  const isRunning = step.status === 'running'
                  const isDone = step.status === 'done'
                  const isFailed = step.status === 'failed'
                  const isPending = step.status === 'pending'

                  const nameMap = { analyze: '分析剧集', clean: '数据清洗', build: '重建索引', migrate: '导入数据库' }
                  const descMap = { analyze: 'ASR+VLM', clean: '去碎片+字幕', build: 'BGE语义索引', migrate: '写入SQLite' }
                  const iconMap = {
                    analyze: <Search size={14} />,
                    clean: <Brush size={14} />,
                    build: <Cpu size={14} />,
                    migrate: <HardDrive size={14} />,
                  }

                  // 连接线颜色
                  const lineColor = isDone ? 'bg-green-500/60' : 'bg-border'

                  return (
                    <div key={step.id} className="flex items-center flex-1" style={{ minWidth: 0 }}>
                      {/* 阶段节点 */}
                      <div className="flex flex-col items-center gap-1.5 shrink-0">
                        <div className={`w-16 h-10 rounded-lg flex items-center justify-center transition-all duration-300 ${
                          isRunning ? 'bg-blue-500 text-white shadow-lg shadow-blue-500/30' :
                          isDone ? 'bg-green-500 text-white' :
                          isFailed ? 'bg-red-500 text-white' :
                          'bg-card border-2 border-border text-muted-foreground/40'
                        }`}>
                          {isRunning ? <Loader2 size={18} className="animate-spin" /> :
                           isDone ? <CheckCircle2 size={18} /> :
                           isFailed ? <XCircle size={18} /> :
                           iconMap[step.id]}
                        </div>
                        <span className={`text-[10px] font-medium leading-tight text-center ${
                          isRunning ? 'text-blue-400' :
                          isDone ? 'text-green-400' :
                          isFailed ? 'text-red-400' :
                          'text-muted-foreground/50'
                        }`}>
                          {nameMap[step.id]}
                        </span>
                        <span className="text-[9px] text-muted-foreground/40 leading-tight text-center hidden sm:block">
                          {descMap[step.id]}
                        </span>
                        {/* 迷你进度条（仅运行中） */}
                        {isRunning && (
                          <div className="w-full h-0.5 rounded-full bg-secondary overflow-hidden">
                            <div
                              className="h-full rounded-full bg-blue-500 transition-all duration-500"
                              style={{ width: `${Math.max(5, step.progress || 0)}%` }}
                            />
                          </div>
                        )}
                      </div>

                      {/* 连接线（最后一个不加） */}
                      {i < procSteps.length - 1 && (
                        <div className="flex-1 flex items-center mx-0.5" style={{ height: 2, minWidth: 12 }}>
                          <div className={`flex-1 h-0.5 rounded-full transition-colors duration-500 ${lineColor}`} />
                          <div className={`w-0 h-0 border-t-[3px] border-t-transparent border-b-[3px] border-b-transparent border-l-[5px] transition-colors duration-500 ${
                            isDone ? 'border-l-green-500/60' : 'border-l-border'
                          }`} style={{ marginRight: -1 }} />
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

                {/* 运行中的阶段 — 详细信息 */}
                {(() => {
                  const running = procSteps.find(s => s.status === 'running')
                  if (!running) return null
                  return (
                    <div className="mt-3 p-3 rounded-lg bg-blue-500/5 border border-blue-500/20 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-medium text-blue-400">
                          {running.label}
                        </span>
                        <span className="text-[10px] text-blue-400/70 tabular-nums">
                          已用时 {Math.floor(running.elapsed / 60)}分{Math.floor(running.elapsed % 60)}秒
                        </span>
                      </div>
                      {/* 大进度条 */}
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-2 rounded-full bg-secondary overflow-hidden">
                          <div
                            className="h-full rounded-full bg-blue-500 transition-all duration-700"
                            style={{ width: `${Math.max(2, running.progress || 0)}%` }}
                          />
                        </div>
                        <span className="text-[10px] text-blue-400 font-mono w-8 text-right">
                          {running.progress || 0}%
                        </span>
                      </div>
                      {/* 当前操作 */}
                      {running.detail && (
                        <p className="text-[11px] text-foreground/60 truncate font-mono">
                          {running.detail}
                        </p>
                      )}
                      {/* 日志 */}
                      {running.log_lines?.length > 0 && (
                        <div className="max-h-24 overflow-y-auto bg-black/20 rounded-md p-2 font-mono text-[10px] text-muted-foreground space-y-0.5">
                          {running.log_lines.map((l, i) => (
                            <div key={i} className="truncate">{l}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })()}

                {/* 失败的阶段 */}
                {(() => {
                  const failed = procSteps.find(s => s.status === 'failed')
                  if (!failed) return null
                  return (
                    <div className="mt-3 p-3 rounded-lg bg-red-500/5 border border-red-500/20">
                      <div className="flex items-center gap-2 mb-1">
                        <XCircle size={14} className="text-red-400" />
                        <span className="text-xs font-medium text-red-400">{failed.label} 失败</span>
                        <span className="text-[10px] text-red-400/70">
                          用时 {Math.floor(failed.elapsed / 60)}分{Math.floor(failed.elapsed % 60)}秒
                        </span>
                      </div>
                      {failed.detail && (
                        <p className="text-[11px] text-red-400/80 font-mono">{failed.detail}</p>
                      )}
                      {failed.log_lines?.length > 0 && (
                        <div className="mt-1 max-h-20 overflow-y-auto bg-black/20 rounded-md p-2 font-mono text-[10px] text-red-400/70 space-y-0.5">
                          {failed.log_lines.map((l, i) => (
                            <div key={i} className="truncate">{l}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })()}

                {/* 全部完成 */}
                {procSteps.every(s => s.status === 'done') && (
                  <div className="mt-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/20">
                    <CheckCircle2 size={14} className="text-green-400" />
                    <span className="text-xs text-green-400">
                      全部完成！总用时 {
                        Math.floor(procSteps.reduce((s, st) => s + (st.elapsed || 0), 0) / 60)
                      }分
                    </span>
                  </div>
                )}
              </div>
          </div>
        </div>

      </div>
    </div>
  )
}
