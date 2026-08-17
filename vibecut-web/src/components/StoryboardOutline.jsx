/**
 * 分镜大纲 — 全局分镜脚本（storyboard.json）浏览 + 预览
 *
 * 纯展示组件：storyboard 由父组件（VibeEdit）统一加载后传入。
 * - 段级纵向大纲：seq + type 色标 + 内容摘要 + 镜头数/时长
 * - 展开看该段 shot_sequence，shot_type 6 类分色
 * - 点击镜头 → 用 source_file(EP) + in_point(timecode) + duration_sec 定位源检视器预览真实画面
 */
import { useState, useCallback, useMemo } from 'react'
import { ChevronDown, ChevronRight, Play } from 'lucide-react'
import { cn } from '../lib/utils'
import { colors } from '../styles/theme'
import { buildSourceFileToEp, resolveShotSource } from '../lib/storyboardUtils'

/* ── shot_type 6 类色标 ── */
const SHOT_TYPE_STYLE = {
  main:         { label: '主镜头',  color: colors.purple,     bg: 'rgba(167,139,250,0.12)' },
  establishing: { label: '建立',    color: colors.blue,       bg: 'rgba(96,165,250,0.12)' },
  reaction:     { label: '反应',    color: colors.gold,       bg: 'rgba(251,191,36,0.12)' },
  insert:       { label: '插入',    color: colors.green,      bg: 'rgba(34,197,94,0.12)' },
  cutaway:      { label: '切离',    color: colors.textMuted,  bg: 'rgba(156,163,175,0.10)' },
  emphasis:     { label: '强调',    color: colors.red,        bg: 'rgba(239,68,68,0.12)' },
  transition:   { label: '转场',    color: colors.textFaint,  bg: 'rgba(107,114,128,0.10)' },
}

const SEG_TYPE_STYLE = {
  narration: { label: '解说', color: colors.purple, bg: 'rgba(167,139,250,0.10)' },
  dialogue:  { label: '台词', color: colors.gold,   bg: 'rgba(251,191,36,0.10)' },
}

/* ── 单个镜头卡片 ── */
function ShotRow({ shot, onPreview }) {
  const st = SHOT_TYPE_STYLE[shot.shot_type] || SHOT_TYPE_STYLE.cutaway
  const hasSource = shot.source_file != null && shot.in_point != null

  return (
    <button
      onClick={() => hasSource && onPreview(shot)}
      disabled={!hasSource}
      className={cn(
        'w-full text-left px-2 py-1.5 rounded flex items-start gap-1.5 transition-colors border-l-2',
        hasSource ? 'hover:bg-accent/50 cursor-pointer' : 'opacity-45 cursor-default'
      )}
      style={{ borderLeftColor: st.color }}
    >
      <span className="text-[10px] font-mono font-bold shrink-0 mt-0.5"
        style={{ color: st.color, background: st.bg, padding: '1px 4px', borderRadius: 2 }}>
        {st.label}
      </span>
      <span className="text-[10px] font-mono text-textFaint shrink-0 mt-0.5">{shot.shot_id}</span>
      <span className="flex-1 min-w-0 leading-snug">
        <span className="text-[12px] text-foreground/75 block">
          {shot.description || (hasSource ? '' : (shot.role || '无源画面'))}
        </span>
      </span>
      <span className="flex items-center gap-1 shrink-0 mt-0.5">
        {hasSource && <Play size={9} className="text-purple/70" />}
        <span className="text-[10px] font-mono text-textFaint">
          {hasSource ? `${shot.duration_sec ?? 0}s` : '—'}
        </span>
      </span>
    </button>
  )
}

/* ── 单个段落 ── */
function SegmentBlock({ seg, expanded, onToggle, onPreview }) {
  const segSt = SEG_TYPE_STYLE[seg.type] || SEG_TYPE_STYLE.narration
  const shots = seg.shot_sequence || []

  return (
    <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
      <button onClick={onToggle} className="w-full flex items-center gap-1.5 px-2.5 py-2 text-left hover:bg-accent/40 transition-colors">
        <span className="text-[10px] font-bold shrink-0 px-1 py-0.5 rounded"
          style={{ color: segSt.color, background: segSt.bg }}>
          {segSt.label}
        </span>
        <span className="text-[11px] font-mono text-textFaint shrink-0">S{seg.seq}</span>
        <span className="text-[12px] text-foreground/80 flex-1 min-w-0"
          style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {seg.content || ''}
        </span>
        <span className="text-[10px] font-mono text-textFaint shrink-0">{shots.length}镜/{seg.total_duration_sec ?? 0}s</span>
        {expanded ? <ChevronDown className="size-3 text-textFaint shrink-0" /> : <ChevronRight className="size-3 text-textFaint shrink-0" />}
      </button>

      {expanded && (
        <div className="px-1.5 pb-1.5 pt-0.5 border-t border-border/40 space-y-0.5">
          {/* 段落完整原文 */}
          {seg.content && (
            <p className="text-[12px] text-foreground/70 leading-relaxed px-1.5 py-1 mb-0.5">
              {seg.content}
            </p>
          )}
          {shots.map((shot) => (
            <ShotRow key={shot.shot_id || shot.description} shot={shot} onPreview={onPreview} />
          ))}
        </div>
      )}
    </div>
  )
}

/* ── 主组件 ── */
export default function StoryboardOutline({ storyboard, loading, error }) {
  const [openSeg, setOpenSeg] = useState(null)

  // 默认展开第一段
  useMemo(() => {
    if (storyboard?.segments?.length && openSeg == null) {
      setOpenSeg(storyboard.segments[0].seq)
    }
  }, [storyboard])

  const sourceFileToEp = useMemo(() => buildSourceFileToEp(storyboard?.source_files), [storyboard])

  const handlePreview = useCallback((shot) => {
    const src = resolveShotSource(shot, sourceFileToEp)
    if (!src) return
    if (window.__sourceLoadEpisode) {
      window.__sourceLoadEpisode(src.ep, src.startSec, src.endSec)
    }
  }, [sourceFileToEp])

  if (loading) {
    return <div className="h-full flex items-center justify-center text-xs text-textMuted">加载分镜脚本…</div>
  }
  if (error) {
    return <div className="h-full flex items-center justify-center text-xs text-textMuted">{error}</div>
  }
  if (!storyboard) return null

  const notes = storyboard.editing_notes || {}

  return (
    <div className="flex flex-col h-full">
      {/* 顶部汇总条 */}
      <div className="flex items-center gap-2 px-2.5 py-1.5 border-b border-border/50 shrink-0">
        <span className="text-[11px] font-medium text-foreground truncate">{storyboard.title || '分镜脚本'}</span>
        <span className="text-[9px] font-mono text-textFaint ml-auto shrink-0">
          {storyboard.segments?.length ?? 0}段/{notes.total_shots ?? 0}镜
        </span>
      </div>

      {/* 段列表 */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-1.5 space-y-1">
        {(storyboard.segments || []).map((seg) => (
          <SegmentBlock
            key={seg.seq}
            seg={seg}
            expanded={openSeg === seg.seq}
            onToggle={() => setOpenSeg(openSeg === seg.seq ? null : seg.seq)}
            onPreview={handlePreview}
          />
        ))}
      </div>
    </div>
  )
}
