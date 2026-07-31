/**
 * 脚本段面板（左侧）
 * 复刻 MatchingDesk 的段导航交互：展开段落 → 点击台词/句子 → 触发 AI 搜索
 */
import { useState } from 'react'
import { ChevronDown, ChevronRight, Search } from 'lucide-react'
import { cn } from '../lib/utils'

const CHARS = ["苏大强", "苏明哲", "苏明成", "苏明玉", "明玉", "朱丽", "吴非", "石天冬", "蒙总", "老蒙", "蒙太", "沈浩", "柳青", "赵美兰", "小咪"]

function highlightHtml(text) {
  if (!text) return ''
  let s = text
  CHARS.forEach(c => { s = s.replaceAll(c, `<span class="char-hl">${c}</span>`) })
  return s
}

function Highlighted({ text, className }) {
  return <span className={className} dangerouslySetInnerHTML={{ __html: highlightHtml(text) }} />
}

export default function ScriptPanel({ segments, curSid, curSeq, onPickSentence, picks, collapsed }) {
  const [openSeg, setOpenSeg] = useState(null)

  if (!segments?.length) {
    return null
  }

  // 首次加载时自动展开第一个
  if (openSeg === null && segments.length > 0) {
    setOpenSeg(segments[0].seg_id)
  }

  return (
    <div className={cn(
      'custom-scrollbar overflow-y-auto overflow-x-hidden border-r border-border flex-shrink-0 h-full'
    )} style={{ width: collapsed ? 0 : '100%' }}>
      {!collapsed && (
        <div className="p-2">
          {segments.map(seg => {
            const isOpen = openSeg === seg.seg_id
            const sentences = (seg.narration_text || '').split(/[。！？]/).filter(s => s.trim())
            return (
              <div key={seg.seg_id} className="mb-1.5">
                {/* Segment header */}
                <button
                  onClick={() => setOpenSeg(isOpen ? null : seg.seg_id)}
                  className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-card border border-border hover:bg-accent transition-colors text-left"
                >
                  <span className="text-[10px] text-muted-foreground/50 mr-1" title="有解说音频">🔊</span>
                  <span className="text-sm font-medium text-warning">seg_{seg.seg_id}</span>
                  {isOpen ? <ChevronDown className="size-3.5 text-muted-foreground" /> : <ChevronRight className="size-3.5 text-muted-foreground" />}
                </button>

                {isOpen && (
                  <div className="mt-1 ml-1 pl-2 border-l-2 border-border/50">
                    {/* Highlight text */}
                    {seg.highlight_text && (
                      <button
                        onClick={() => onPickSentence(seg.seg_id, 'D')}
                        className={cn(
                          'w-full text-left px-2.5 py-1.5 mb-1 rounded-r-lg border-l-[3px] transition-colors',
                          curSid === seg.seg_id && curSeq === 'D'
                            ? 'bg-warning/20 border-warning shadow-sm'
                            : 'bg-destructive/10 border-warning hover:bg-destructive/15'
                        )}
                      >
                        <span className="text-[10px] text-warning/70">S{seg.seg_id}-D</span>
                        {' '}<span className="text-[11px] text-warning leading-snug">
                          <Highlighted text={seg.highlight_text.substring(0, 80)} />
                          {seg.highlight_text.length > 80 && '...'}
                        </span>
                      </button>
                    )}

                    {/* Narration sentences */}
                    {sentences.map((s, i) => {
                      const summary = getPickSummary(picks, seg.seg_id, i)
                      return (
                        <div key={i} className={cn(
                          'flex items-start gap-1.5 py-1.5 px-1 border-b border-border/30 rounded transition-colors group',
                          curSid === seg.seg_id && curSeq === i
                            ? 'bg-purple/10 border-l-[3px] border-l-purple shadow-sm'
                            : 'hover:bg-accent/50'
                        )}>
                          <span className="text-[10px] text-info font-mono min-w-[38px] pt-0.5 select-none">S{seg.seg_id}-{i}</span>
                          <button
                            onClick={() => onPickSentence(seg.seg_id, i)}
                            className="flex-1 text-left text-xs text-foreground/85 leading-relaxed cursor-pointer hover:text-foreground"
                          >
                            <Highlighted text={s.trim() + '。'} />
                          </button>
                          <button
                            onClick={() => onPickSentence(seg.seg_id, i)}
                            className="p-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity text-purple hover:bg-purple/10 flex-shrink-0"
                          >
                            <Search className="size-3" />
                          </button>
                          {summary && (
                            <span className="text-[10px] text-success font-medium min-w-[40px] text-right">{summary}</span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function getPickSummary(picks, sid, seq) {
  if (!picks) return ''
  const key = `${sid}_${seq}`
  const p = picks[key]
  if (!p) return ''
  const parts = []
  if (p.main?.length) parts.push(`${p.main.length}主`)
  if (p.supp?.length) parts.push(`${p.supp.length}补`)
  return parts.join(' ')
}
