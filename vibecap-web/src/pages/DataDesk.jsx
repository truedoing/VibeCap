import { useState, useEffect } from 'react'
import { useProject } from '../context/ProjectContext'
import { BarChart3, Database, Shield, TrendingUp, Tv, Loader2 } from 'lucide-react'

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

export default function DataDesk() {
  const { taskId } = useProject()
  const [quality, setQuality] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/data/quality')
      .then(r => r.json())
      .then(setQuality)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [taskId])

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

      </div>
    </div>
  )
}
