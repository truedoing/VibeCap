/**
 * 分镜推荐面板 — 显示 AI 生成的分镜建议列表
 */
import { Sparkles } from 'lucide-react'
import { font } from '../styles/theme'

export default function StoryboardPanel({ suggestions, onSearch, curSid, curSeq }) {
  if (!suggestions?.length) return null

  return (
    <div style={{ borderTop:'1px solid #232938', flexShrink:0, height:170, display:'flex', flexDirection:'column' }}>
      <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-border/30 text-muted-foreground shrink-0"
        style={{ fontSize: font.xs }}>
        <Sparkles size={12} className="text-purple/60" />
        <span>分镜推荐</span>
        {curSid != null && <span className="text-warning/60">S{curSid}-{curSeq}</span>}
      </div>
      <div className="flex-1 overflow-y-auto custom-scrollbar p-1.5 space-y-1">
        {suggestions.map((s, i) => (
          <button key={i} onClick={() => onSearch?.(s)}
            className="w-full text-left px-2.5 py-1.5 rounded-lg border border-border/30 bg-card/30 hover:border-purple/30 hover:bg-purple/[0.04] transition-colors group">
            <div className="flex items-start gap-1.5">
              <span className="text-purple/50 font-mono shrink-0 mt-0.5" style={{ fontSize: font.xxs }}>{i+1}</span>
              <span className="text-foreground/80 leading-snug" style={{ fontSize: font.xs }}>{s}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
