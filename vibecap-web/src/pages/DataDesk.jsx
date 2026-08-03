import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useProject } from '../context/ProjectContext'
import { BarChart3, Database, Shield, TrendingUp, Tv, Loader2, Play, CheckCircle2, XCircle, Search, Brush, Cpu, HardDrive } from 'lucide-react'
import { colors, font } from '../styles/theme'
import { btn, card, flexRow, panelHeader, title } from '../styles/mixins'

// ── 质量色 ──
function qualityColor(score) {
  if (score <= 0) return 'text-muted-foreground/30'
  if (score >= 75) return 'text-green-400'
  if (score >= 55) return 'text-yellow-400'
  return 'text-red-400'
}
function qualityBg(score) {
  if (score <= 0) return 'bg-muted-foreground/20'
  if (score >= 75) return 'bg-green-500'
  if (score >= 55) return 'bg-yellow-500'
  return 'bg-red-500'
}
function qualityLabel(score) {
  if (score <= 0) return '未分析'
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

export default function DataDesk() {
  const { seriesId } = useParams()
  const projectName = seriesId === 'doutinghao' ? '都挺好' : seriesId === 'yanglaoshi' ? '杨老师教育' : decodeURIComponent(seriesId || '')
  const { taskId } = useProject()
  const [quality, setQuality] = useState(null)
  const [loading, setLoading] = useState(true)

  // 加工面板状态
  const defaultSteps = [
    { id: 'analyze',   label: '分析剧集', status: 'pending', progress: 0, detail: '', elapsed: 0, log_lines: [] },
    { id: 'calibrate', label: '交叉校准', status: 'pending', progress: 0, detail: '', elapsed: 0, log_lines: [] },
    { id: 'clean',     label: '数据清洗', status: 'pending', progress: 0, detail: '', elapsed: 0, log_lines: [] },
    { id: 'build',     label: '重建索引', status: 'pending', progress: 0, detail: '', elapsed: 0, log_lines: [] },
    { id: 'migrate',   label: '导入数据库', status: 'pending', progress: 0, detail: '', elapsed: 0, log_lines: [] },
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
    fetch(`/data/quality?project=${encodeURIComponent(projectName)}`)
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
      body: JSON.stringify({ episodes: eps, project: projectName }),
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
    ? Math.round(reports.filter(r => r.overall_score > 0).reduce((s, r) => s + r.overall_score, 0)
        / Math.max(1, reports.filter(r => r.overall_score > 0).length))
    : 0

  // 收集所有步骤的日志行（用于统一日志输出区）
  const allLogs = procSteps.flatMap(s => s.log_lines || [])

  return (
    <div className="flex-1 flex flex-col overflow-auto bg-background">
      <div className="max-w-7xl mx-auto w-full p-6 space-y-4">

        {/* ── Header ── */}
        <div>
          <h1 className="text-lg font-bold text-foreground flex items-center gap-2">
            <Shield size={18} className="text-primary" />
            数据台
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            {summary.total_eps || 0} 集 · {summary.total_indexed || 0} 条索引 · 平均质量 {avgScore} 分
          </p>
        </div>

        {/* ── 概览卡片（全宽）── */}
        <div className="grid grid-cols-4 gap-3">
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="flex items-center gap-2 mb-1">
              <Tv size={14} className="text-blue-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">已索引</span>
            </div>
            <span className="text-xl font-bold text-foreground">{summary.indexed_eps || 0}</span>
            <span className="text-xs text-muted-foreground ml-1">/ {summary.total_eps || 0} 集</span>
          </div>
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="flex items-center gap-2 mb-1">
              <Database size={14} className="text-purple-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">索引条目</span>
            </div>
            <span className="text-xl font-bold text-foreground">{summary.total_indexed || 0}</span>
            <span className="text-xs text-muted-foreground ml-1">条</span>
          </div>
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="flex items-center gap-2 mb-1">
              <TrendingUp size={14} className="text-green-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">平均质量</span>
            </div>
            <span className={`text-xl font-bold ${qualityColor(avgScore)}`}>{avgScore}</span>
            <span className="text-xs text-muted-foreground ml-1">分</span>
          </div>
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="flex items-center gap-2 mb-1">
              <BarChart3 size={14} className="text-yellow-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">字幕提取</span>
            </div>
            <span className="text-xl font-bold text-foreground">{summary.total_subtitles || 0}</span>
            <span className="text-xs text-muted-foreground ml-1">条</span>
          </div>
        </div>

        {/* ── 两栏布局 ── */}
        <div className="grid grid-cols-5 gap-4" style={{ minHeight: 'calc(100vh - 220px)' }}>

          {/* 左栏：分集数据质量 */}
          <div className="col-span-2 rounded-xl border border-border bg-card overflow-hidden flex flex-col">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border shrink-0">
              <Database size={14} className="text-muted-foreground" />
              <h3 className="text-sm font-medium text-foreground">分集数据质量</h3>
              <span className="text-[9px] text-muted-foreground/50 ml-auto">ASR35+VLM40+字幕10+索引15</span>
            </div>
            <div className="divide-y divide-border/50 flex-1 overflow-y-auto custom-scrollbar">
              {episodes.map(ep => {
                const report = reports.find(r => r.ep_number === ep.ep_number)
                return (
                  <EpQualityBar
                    key={ep.ep_number}
                    ep={ep.ep_number}
                    report={report}
                    indexed={ep.indexed}
                  />
                )
              })}
            </div>
          </div>

          {/* 右栏：数据加工 + 进度日志 */}
          <div className="col-span-3 flex flex-col gap-4" style={{ minHeight: 0 }}>

            {/* 数据加工流水线 */}
            <div className="rounded-xl border border-border bg-card overflow-hidden shrink-0">
              <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border">
                <Cpu size={14} className="text-muted-foreground" />
                <h3 className="text-sm font-medium text-foreground">数据加工流水线</h3>
                <span className="text-[10px] text-muted-foreground">analyze → calibrate → clean → build → migrate</span>
              </div>
              <div className="p-3 space-y-3">
                {/* 剧集选择 */}
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-1 max-h-20 overflow-y-auto custom-scrollbar">
                    {allEpisodes.map(ep => {
                      const isSelected = selectedEps.includes(ep.ep_number)
                      const hasAnalysis = hasData(ep.ep_number)
                      return (
                        <button
                          key={ep.ep_number}
                          disabled={procSteps.some(s => s.status === 'running')}
                          onClick={() => setSelectedEps(prev =>
                            prev.includes(ep.ep_number) ? prev.filter(e => e !== ep.ep_number) : [...prev, ep.ep_number]
                          )}
                          className={`w-8 h-5.5 rounded text-[10px] font-mono transition-all border flex items-center justify-center ${
                            isSelected ? 'bg-blue-500/20 text-blue-400 border-blue-500/40' :
                            hasAnalysis ? 'bg-card text-foreground/70 border-green-500/30 hover:border-green-500/50' :
                            'bg-secondary text-muted-foreground border-border hover:border-primary/30 hover:text-foreground'
                          } disabled:opacity-50`}
                        >{ep.ep_number}</button>
                      )
                    })}
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => setSelectedEps(allEpisodes.map(e => e.ep_number))}
                      disabled={procSteps.some(s => s.status === 'running')}
                      className="text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-50">全选</button>
                    <button onClick={() => setSelectedEps([])}
                      disabled={procSteps.some(s => s.status === 'running')}
                      className="text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-50">清空</button>
                    <span className="text-[10px] text-muted-foreground">已选 {selectedEps.length} 集</span>
                    <div className="flex-1" />
                    <button onClick={startProcess}
                      disabled={selectedEps.length === 0 || procSteps.some(s => s.status === 'running')}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium disabled:opacity-40 hover:opacity-90 transition-opacity">
                      {procSteps.some(s => s.status === 'running') ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
                      开始加工
                    </button>
                  </div>
                </div>

                {/* 工作流管线图 */}
                <div className="flex items-center px-2">
                  {procSteps.map((step, i) => {
                    const isRunning = step.status === 'running'
                    const isDone = step.status === 'done'
                    const isFailed = step.status === 'failed'
                    const nameMap = { analyze: '分析', calibrate: '校准', clean: '清洗', build: '索引', migrate: '入库' }
                    const iconMap = { analyze: <Search size={12} />, calibrate: <CheckCircle2 size={12} />, clean: <Brush size={12} />, build: <Cpu size={12} />, migrate: <HardDrive size={12} /> }
                    const lineColor = isDone ? 'bg-green-500/60' : 'bg-border'
                    return (
                      <div key={step.id} className="flex items-center flex-1" style={{ minWidth: 0 }}>
                        <div className="flex flex-col items-center gap-0.5 shrink-0">
                          <div className={`w-10 h-7 rounded-md flex items-center justify-center transition-all duration-300 ${
                            isRunning ? 'bg-blue-500 text-white shadow shadow-blue-500/30' :
                            isDone ? 'bg-green-500 text-white' :
                            isFailed ? 'bg-red-500 text-white' :
                            'bg-card border border-border text-muted-foreground/40'
                          }`}>
                            {isRunning ? <Loader2 size={14} className="animate-spin" /> :
                             isDone ? <CheckCircle2 size={14} /> :
                             isFailed ? <XCircle size={14} /> : iconMap[step.id]}
                          </div>
                          <span className={`text-[9px] font-medium ${
                            isRunning ? 'text-blue-400' : isDone ? 'text-green-400' : isFailed ? 'text-red-400' : 'text-muted-foreground/50'
                          }`}>{nameMap[step.id]}</span>
                        </div>
                        {i < procSteps.length - 1 && (
                          <div className="flex-1 flex items-center mx-0.5" style={{ height: 2, minWidth: 8 }}>
                            <div className={`flex-1 h-0.5 rounded-full transition-colors duration-500 ${lineColor}`} />
                            <div className={`w-0 h-0 border-t-[3px] border-t-transparent border-b-[3px] border-b-transparent border-l-[5px] ${
                              isDone ? 'border-l-green-500/60' : 'border-l-border'
                            }`} />
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            {/* 进度日志输出区 */}
            <div className="rounded-xl border border-border bg-card overflow-hidden flex flex-col flex-1" style={{ minHeight: 200 }}>
              <div className="flex items-center gap-2 px-4 py-2 border-b border-border shrink-0">
                <span className="text-sm font-medium text-foreground">进度日志</span>
                {procSteps.some(s => s.status === 'running') && (
                  <span className="text-[10px] text-blue-400 animate-pulse">处理中...</span>
                )}
                {procSteps.every(s => s.status === 'done') && (
                  <span className="text-[10px] text-green-400">
                    全部完成 · 总用时 {Math.floor(procSteps.reduce((s, st) => s + (st.elapsed || 0), 0) / 60)}分
                  </span>
                )}
                {procSteps.some(s => s.status === 'failed') && (
                  <span className="text-[10px] text-red-400">处理失败</span>
                )}
                <span className="text-[10px] text-muted-foreground/50 ml-auto">{allLogs.length} 行</span>
              </div>
              <div className="flex-1 overflow-y-auto custom-scrollbar p-3 font-mono text-[10px] leading-relaxed space-y-0.5 bg-black/10">
                {allLogs.length === 0 ? (
                  <p className="text-muted-foreground/40">选择集数并开始加工后，日志将在此实时输出...</p>
                ) : (
                  allLogs.map((l, i) => (
                    <div key={i} className="whitespace-pre-wrap break-all text-muted-foreground">{l}</div>
                  ))
                )}
              </div>
            </div>

          </div>
        </div>

      </div>
    </div>
  )
}
