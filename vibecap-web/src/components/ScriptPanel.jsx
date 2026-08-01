/**
 * 脚本段面板 — 标签式段落选择 + 展开句子明细
 */
import { useState } from 'react'
import { ChevronDown, ChevronRight, Search } from 'lucide-react'
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

export default function ScriptPanel({ segments, curSid, curSeq, onPickSentence, picks }) {
  const [openSeg, setOpenSeg] = useState(null)

  if (!segments?.length) return null

  if (openSeg === null && segments.length > 0) setOpenSeg(segments[0].seg_id)

  return (
    <div className="custom-scrollbar overflow-y-auto overflow-x-hidden h-full" style={{ flex:1, minHeight:0 }}>
      <div className="p-1.5 space-y-1">
        {segments.map(seg => {
          const isOpen = openSeg === seg.seg_id
          const sentences = (seg.narration_text || '').split(/[。！？]/).filter(s => s.trim())
          return (
            <div key={seg.seg_id}>
              <button
                onClick={() => setOpenSeg(isOpen ? null : seg.seg_id)}
                className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-card border border-border hover:bg-accent transition-colors text-left">
                <span className="text-[10px] text-muted-foreground/50">🔊</span>
                <span className="text-xs font-semibold text-warning">S{seg.seg_id}</span>
                <span className="text-[10px] text-muted-foreground truncate flex-1">{(seg.narration_text||'').substring(0, 30)}</span>
                {isOpen ? <ChevronDown className="size-3 text-muted-foreground shrink-0" /> : <ChevronRight className="size-3 text-muted-foreground shrink-0" />}
              </button>
              {isOpen && (
                <div className="ml-2 pl-2 border-l-2 border-border/50 mt-0.5 space-y-0.5">
                  {seg.highlight_text && (
                    <button onClick={() => onPickSentence(seg.seg_id, 'D')}
                      className={cn('w-full text-left px-2 py-1 rounded-r border-l-[3px] transition-colors',
                        curSid===seg.seg_id&&curSeq==='D' ? 'bg-warning/20 border-warning' : 'bg-destructive/10 border-warning hover:bg-destructive/15')}>
                      <span className="text-[9px] text-warning/70">台词</span>
                      <span className="text-[10px] text-warning leading-snug ml-1"><Highlighted text={seg.highlight_text.substring(0,60)} />{seg.highlight_text.length>60&&'...'}</span>
                    </button>
                  )}
                  {sentences.map((s, i) => {
                    const p = picks?.[`${seg.seg_id}_${i}`]
                    const cnt = (p?.main?.length||0)+(p?.supp?.length||0)
                    return (
                      <div key={i} className={cn('flex items-start gap-1 py-0.5 px-1 rounded group transition-colors',
                        curSid===seg.seg_id&&curSeq===i ? 'bg-purple/10 border-l-[3px] border-l-purple' : 'hover:bg-accent/50')}>
                        <span className="text-[9px] text-info font-mono pt-0.5 shrink-0">句{i}</span>
                        <button onClick={() => onPickSentence(seg.seg_id, i)} className="flex-1 text-left text-[10px] text-foreground/80 leading-relaxed">
                          <Highlighted text={s.trim()+'。'} />
                        </button>
                        <button onClick={() => onPickSentence(seg.seg_id, i)} className="p-0.5 opacity-0 group-hover:opacity-100 text-purple shrink-0"><Search className="size-2.5" /></button>
                        {cnt>0 && <span className="text-[9px] text-success font-medium shrink-0">{cnt}主</span>}
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
