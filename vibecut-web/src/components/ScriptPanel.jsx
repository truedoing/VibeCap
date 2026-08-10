/**
 * 脚本段面板 v3 — 段落级分镜
 * 每个 segment 是一个叙事单元, 点击触发展开+策划分镜
 * cover 作为独立的 Hook 段插入到 segments 前面
 */
import { useState, useMemo, useEffect } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { cn } from '../lib/utils'

const CHARS = ["苏大强", "苏明哲", "苏明成", "苏明玉", "明玉", "朱丽", "吴非", "石天冬", "蒙总", "老蒙", "蒙太", "沈浩", "柳青", "赵美兰", "小咪"]

function hh(text) {
  if (!text) return ''
  let s = text
  CHARS.forEach(c => { s = s.replaceAll(c, `<span class="char-hl">${c}</span>`) })
  return s
}
function Highlighted({ text, className }) {
  return <span className={className} dangerouslySetInnerHTML={{ __html: hh(text) }} />
}

function getSegStatus(seg, picks) {
  const key = `${seg.seg_id}_0`
  const p = picks?.[key]
  const mainCnt = (p?.main?.length || 0)
  const suppCnt = (p?.supp?.length || 0)
  return { mainCnt, suppCnt, total: mainCnt + suppCnt }
}

/* ── 口播模式: KEEP/CUT 精切列表 ── */
function RefineView({ segments, onSelectSegment }) {
  const allSubClips = useMemo(() => {
    const result = []
    for (const seg of segments) {
      for (const sc of (seg.sub_clips || [])) {
        result.push({ ...sc, seg_id: seg.seg_id, topic: seg.topic })
      }
    }
    return result.sort((a, b) => a.start - b.start)
  }, [segments])
  if (!allSubClips.length) return null
  return (
    <div className="overflow-y-auto flex-1">
      <div className="p-1 space-y-0.5">
        {allSubClips.map((sc, idx) => {
          const isKeep = sc.decision === 'KEEP'
          return (
            <button key={idx} onClick={() => onSelectSegment(sc.seg_id)}
              className={cn('w-full text-left px-2 py-1.5 rounded-r border-l-[3px] transition-colors flex items-start gap-2',
                isKeep ? 'border-emerald-500/60 bg-emerald-500/5 hover:bg-emerald-500/10'
                       : 'border-red-500/40 bg-red-500/3 hover:bg-red-500/8 opacity-80')}>
              <span className={cn('text-[11px] font-bold shrink-0 mt-0.5', isKeep ? 'text-emerald-400' : 'text-red-400')}>
                {isKeep ? '✅' : '❌'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="text-[10px] text-muted-foreground/70 font-mono">S{sc.seg_id}</span>
                </div>
                <p className={cn('text-[11px] leading-snug', isKeep ? 'text-foreground/85' : 'text-foreground/50 line-through')}>
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

/* ── 段落级视图 (drama) ── */
function ParagraphView({ segments, curSid, onSelectSegment, onStoryboard, picks, cover }) {
  const [openSeg, setOpenSeg] = useState(null)

  // cover 作为独立的 Hook 段插入到 segments 前面
  const allSegs = useMemo(() => {
    if (cover) {
      const hookSeg = { seg_id: -1, highlight_text: null, narration_text: cover.replace(/\n/g, ' '), _isHook: true }
      return [hookSeg, ...segments]
    }
    return segments
  }, [cover, segments])

  useEffect(() => {
    if (allSegs.length > 0 && openSeg === null) setOpenSeg(allSegs[0].seg_id)
  }, [allSegs])

  return (
    <div className="overflow-y-auto flex-1">
      <div className="p-1.5 space-y-1">
        {allSegs.map((seg) => {
          const isOpen = openSeg === seg.seg_id
          const isHook = seg._isHook === true
          const status = isHook ? { mainCnt: 0, suppCnt: 0, total: 0 } : getSegStatus(seg, picks)
          const narrText = seg.narration_text || ''

          return (
            <div key={seg.seg_id}>
              <div className={cn('rounded-lg border transition-all', 'border-border bg-card')}>
                {/* ── 台词行：始终可见，点击 → ASR精确匹配 ── */}
                {seg.highlight_text && (
                  <button onClick={() => onSelectSegment(seg.seg_id)}
                    className={cn('w-full text-left px-3 py-2 rounded-t-lg transition-colors flex items-start gap-2',
                      curSid === seg.seg_id ? 'bg-warning/10' : 'hover:bg-warning/5')}>
                    <span className="text-[10px] text-warning/60 font-bold shrink-0 mt-0.5">台词</span>
                    <span className="text-[11px] text-warning/85 leading-snug flex-1">
                      <Highlighted text={seg.highlight_text} />
                    </span>
                    <span className="text-[10px] text-muted-foreground/40 shrink-0 mt-0.5">S{seg.seg_id}</span>
                  </button>
                )}

                {/* ── 解说行：点击展开 → 策划分镜 ── */}
                <div className={cn(!seg.highlight_text && 'rounded-t-lg')}>
                  <button onClick={() => {
                    const next = isOpen ? null : seg.seg_id
                    setOpenSeg(next)
                    if (!isOpen) onStoryboard(isHook ? -1 : seg.seg_id)
                  }}
                    className={cn('w-full text-left px-3 py-2 flex items-center gap-2 transition-colors',
                      !seg.highlight_text && 'rounded-t-lg',
                      isOpen ? 'border-t border-border/20' : '',
                      'hover:bg-accent/50')}>
                    <span className={cn('text-[10px] font-bold shrink-0',
                      isHook ? 'text-purple/80' : 'text-purple/60')}>
                      {isHook ? '🎣 Hook' : '解说'}
                    </span>
                    <span className="text-[11px] text-foreground/70 truncate flex-1">
                      {narrText.substring(0, 50)}{narrText.length > 50 && '...'}
                    </span>
                    {status.total > 0 && (
                      <span className="text-[10px] text-emerald-400 font-medium shrink-0">✓{status.mainCnt}主</span>
                    )}
                    {isOpen ? <ChevronDown className="size-3 text-muted-foreground shrink-0" />
                            : <ChevronRight className="size-3 text-muted-foreground shrink-0" />}
                  </button>
                </div>

                {/* ── 展开：完整解说词 ── */}
                {isOpen && (
                  <div className="px-3 pb-3 border-t border-border/20">
                    <p className="text-[11px] text-foreground/80 leading-relaxed mt-2">{narrText}</p>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ── 主入口 ── */
export default function ScriptPanel({ segments, curSid, onSelectSegment, onStoryboard, picks, cover }) {
  if (!segments?.length) return null
  const hasRefine = segments.some(s => s.sub_clips?.length > 0)
  return (
    <div className="custom-scrollbar overflow-y-auto overflow-x-hidden h-full flex flex-col" style={{ flex: 1, minHeight: 0 }}>
      {hasRefine
        ? <RefineView segments={segments} onSelectSegment={onSelectSegment} />
        : <ParagraphView segments={segments} curSid={curSid} onSelectSegment={onSelectSegment} onStoryboard={onStoryboard} picks={picks} cover={cover} />
      }
    </div>
  )
}
