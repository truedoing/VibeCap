/**
 * 脚本段面板
 * 口播: 如有精切 sub_clips → 直接显示精切结果 (KEEP/CUT)
 * 影剧: 显示粗段脚本 + 展开句子明细
 */
import { useState, useMemo } from 'react'
import { ChevronDown, ChevronRight, Search } from 'lucide-react'
import { cn } from '../lib/utils'
import { font, colors } from '../styles/theme'

const CHARS = ["苏大强", "苏明哲", "苏明成", "苏明玉", "明玉", "朱丽", "吴非", "石天冬", "蒙总", "老蒙", "蒙太", "沈浩", "柳青", "赵美兰", "小咪"]

function getSegStatus(seg, picks) {
  // 统计该 segment 下所有 sentence 的 picks 数
  let mainCnt = 0, suppCnt = 0
  const ns = (seg.narration_text || '').split(/[。！？]/).filter(s => s.trim())
  // 台词
  const dp = picks?.[`${seg.seg_id}_D`]
  mainCnt += (dp?.main?.length || 0) + (dp?.supp?.length || 0)
  // 解说句
  ns.forEach((_, i) => {
    const p = picks?.[`${seg.seg_id}_${i}`]
    mainCnt += (p?.main?.length || 0)
    suppCnt += (p?.supp?.length || 0)
  })
  const hasVideo = seg.source_start > 0 || seg.video_start > 0
  return { mainCnt, suppCnt, hasVideo, total: mainCnt + suppCnt }
}

function hh(text) {
  if (!text) return ''
  let s = text
  CHARS.forEach(c => { s = s.replaceAll(c, `<span class="char-hl">${c}</span>`) })
  return s
}
function Highlighted({ text, className }) {
  return <span className={className} dangerouslySetInnerHTML={{ __html: hh(text) }} />
}

/* ── 精切视图 (口播) ── */
function RefineView({ segments, onPickSentence }) {
  const allSubClips = useMemo(() => {
    const result = []
    for (const seg of segments) {
      for (const sc of (seg.sub_clips || [])) {
        result.push({ ...sc, seg_id: seg.seg_id, topic: seg.topic })
      }
    }
    return result.sort((a, b) => a.start - b.start)
  }, [segments])

  const stats = useMemo(() => {
    let keep = 0, cut = 0, keepDur = 0, cutDur = 0
    for (const sc of allSubClips) {
      if (sc.decision === 'KEEP') { keep++; keepDur += sc.end - sc.start }
      else { cut++; cutDur += sc.end - sc.start }
    }
    return { keep, cut, keepDur, cutDur }
  }, [allSubClips])

  if (!allSubClips.length) return null

  return (
    <div className="overflow-y-auto flex-1">
      <div className="px-2 py-1.5 flex items-center gap-3 text-[11px] border-b border-border/30 shrink-0 bg-emerald-500/5">
        <span className="text-emerald-400 font-medium">{stats.keep} 保留</span>
        <span className="text-red-400 font-medium">{stats.cut} 删除</span>
        <span className="text-muted-foreground">保留 {stats.keepDur.toFixed(0)}s</span>
        <span className="text-muted-foreground/50">删除 {stats.cutDur.toFixed(0)}s</span>
      </div>
      <div className="p-1 space-y-0.5">
        {allSubClips.map((sc, idx) => {
          const isKeep = sc.decision === 'KEEP'
          const dur = sc.end - sc.start
          return (
            <button key={idx}
              onClick={() => onPickSentence(sc.seg_id, 'D')}
              className={cn(
                'w-full text-left px-2 py-1.5 rounded-r border-l-[3px] transition-colors flex items-start gap-2',
                isKeep
                  ? 'border-emerald-500/60 bg-emerald-500/5 hover:bg-emerald-500/10'
                  : 'border-red-500/40 bg-red-500/3 hover:bg-red-500/8 opacity-80'
              )}>
              <span className={cn('text-[11px] font-bold shrink-0 mt-0.5',
                isKeep ? 'text-emerald-400' : 'text-red-400')}>
                {isKeep ? '✅' : '❌'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="text-[10px] text-muted-foreground/70 font-mono">
                    S{sc.seg_id} {sc.start.toFixed(0)}s-{sc.end.toFixed(0)}s
                  </span>
                  <span className={cn('text-[10px] font-medium',
                    isKeep ? 'text-emerald-500/70' : 'text-red-400/70')}>
                    {dur.toFixed(1)}s
                  </span>
                  <span className="text-[10px] text-muted-foreground/50">{sc.speaker}</span>
                </div>
                <p className={cn('text-[11px] leading-snug',
                  isKeep ? 'text-foreground/85' : 'text-foreground/50 line-through')}>
                  {sc.text.length > 80 ? sc.text.substring(0, 80) + '...' : sc.text}
                </p>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

/* ── 粗段脚本视图 (影剧/通用) ── */
function ScriptView({ segments, curSid, curSeq, onPickSentence, picks, cover }) {
  const [openSeg, setOpenSeg] = useState(null)
  if (openSeg === null && segments.length > 0) setOpenSeg(segments[0].seg_id)

  return (
    <div className="overflow-y-auto flex-1">
      <div className="p-1.5 space-y-1">
        {/* 封面描述 — 仅供参考，不需要选镜头 */}
        {cover && (
          <div style={{
            margin: '0 4px 8px', padding: '8px 12px', borderRadius: 8,
            border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)',
            fontSize: font.sm, lineHeight: 1.6, color: colors.textMuted,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span style={{ fontSize: font.xs, color: colors.textFaint, fontWeight: 600 }}>📋 封面文案</span>
              <span style={{ fontSize: font.xxs, color: colors.textDisabled }}>（不需要选镜头）</span>
            </div>
            {cover.split('\n').map((line, i) => (
              <p key={i} style={{ margin: 0 }}>{line}</p>
            ))}
          </div>
        )}
        {segments.map(seg => {
          const isOpen = openSeg === seg.seg_id
          const sentences = (seg.narration_text || '').split(/[。！？]/).filter(s => s.trim())
          const status = getSegStatus(seg, picks)
          // 段状态标记
          let statusBadge = null
          if (status.total > 0) {
            statusBadge = <span className="text-[10px] text-emerald-400 font-medium shrink-0 ml-1">✓{status.mainCnt}主{status.suppCnt > 0 ? `+${status.suppCnt}补` : ''}</span>
          } else if (status.hasVideo) {
            statusBadge = <span className="text-[10px] text-amber-400 font-medium shrink-0 ml-1">📍已定位</span>
          }
          return (
            <div key={seg.seg_id}>
              <button
                onClick={() => {
                  const next = isOpen ? null : seg.seg_id
                  setOpenSeg(next)
                }}
                className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-card border border-border hover:bg-accent transition-colors text-left">
                <span className="text-[10px] text-muted-foreground/50">🔊</span>
                <span className="text-xs font-semibold text-warning">S{seg.seg_id}</span>
                <span className="text-[11px] text-warning/80 font-medium truncate flex-1">{(seg.highlight_text || seg.narration_text || '').substring(0, 30)}</span>
                {statusBadge}
                {isOpen ? <ChevronDown className="size-3 text-muted-foreground shrink-0" /> : <ChevronRight className="size-3 text-muted-foreground shrink-0" />}
              </button>
              {isOpen && (
                <div className="ml-2 pl-2 border-l-2 border-border/50 mt-0.5 space-y-0.5">
                  {seg.highlight_text && (
                    <button onClick={() => onPickSentence(seg.seg_id, 'D')}
                      className={cn('w-full text-left px-2 py-1 rounded-r border-l-[3px] transition-colors',
                        curSid===seg.seg_id&&curSeq==='D' ? 'bg-warning/20 border-warning' : 'bg-destructive/10 border-warning hover:bg-destructive/15')}>
                      <span style={{ fontSize: font.xs, color: colors.textMuted }}>台词</span>
                      <span className="text-[11px] text-warning leading-snug ml-1"><Highlighted text={seg.highlight_text.substring(0,60)} />{seg.highlight_text.length>80&&'...'}</span>
                    </button>
                  )}
                  {sentences.map((s, i) => {
                    const p = picks?.[`${seg.seg_id}_${i}`]
                    const cnt = (p?.main?.length||0)+(p?.supp?.length||0)
                    return (
                      <div key={i} className={cn('flex items-start gap-1 py-0.5 px-1 rounded group transition-colors',
                        curSid===seg.seg_id&&curSeq===String(i) ? 'bg-purple/10 border-l-[3px] border-l-purple' : 'hover:bg-accent/50')}>
                        <span className="text-[10px] text-info font-mono pt-0.5 shrink-0">句{i}</span>
                        <button onClick={() => onPickSentence(seg.seg_id, i)} className="flex-1 text-left text-[11px] text-foreground/80 leading-relaxed">
                          <Highlighted text={s.trim()+'。'} />
                        </button>
                        <button onClick={() => onPickSentence(seg.seg_id, i)} className="p-0.5 opacity-0 group-hover:opacity-100 text-purple shrink-0"><Search className="size-2.5" /></button>
                        {cnt>0 && <span className="text-[10px] text-success font-medium shrink-0">{mainCnt}{suppCnt>0 ? `+${suppCnt}` : ''}</span>}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ── 主入口：有精切→精切视图，无→脚本视图 ── */
export default function ScriptPanel(props) {
  const { segments } = props
  if (!segments?.length) return null

  const hasRefine = segments.some(s => s.sub_clips?.length > 0)

  return (
    <div className="custom-scrollbar overflow-y-auto overflow-x-hidden h-full flex flex-col" style={{ flex:1, minHeight:0 }}>
      {hasRefine
        ? <RefineView {...props} />
        : <ScriptView {...props} />
      }
    </div>
  )
}
