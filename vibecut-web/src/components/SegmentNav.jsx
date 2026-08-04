/**
 * 横向段落导航条
 * 显示 S0 ~ S8 段落标签，带已选镜头数量标记
 * 可折叠 / 展开
 */
import { useState, useEffect } from 'react'
import { ChevronUp, ChevronDown } from 'lucide-react'
import { cn } from '../lib/utils'

export default function SegmentNav({ segments, curSid, curSeq, onSelect, picks, collapsed, onToggleCollapse }) {
  if (!segments?.length) {
    return (
      <div className="flex items-center px-3 py-1 border-b border-border/50 bg-card/30 text-[10px] text-muted-foreground">
        暂无段落数据
      </div>
    )
  }

  if (collapsed) {
    return (
      <div className="flex items-center px-3 h-7 border-b border-border/50 bg-card/30">
        <button
          onClick={onToggleCollapse}
          className="text-[10px] text-muted-foreground hover:text-foreground flex items-center gap-1"
        >
          <ChevronDown size={12} />
          段落导航 · {curSid != null ? `S${curSid}` : '—'}
        </button>
      </div>
    )
  }

  return (
    <div className="flex items-center border-b border-border/50 bg-card/30" style={{ height: 36 }}>
      <div className="flex items-center gap-1 px-3 overflow-x-auto custom-scrollbar flex-1" style={{ scrollbarWidth: 'thin' }}>
        {segments.map(seg => {
          const segId = seg.seg_id
          const key = `${segId}_${curSeq ?? 0}`
          const segPicks = picks?.[key]
          const mainCount = segPicks?.main?.length || 0
          const suppCount = segPicks?.supp?.length || 0
          const totalCount = mainCount + suppCount

          const isActive = curSid === segId

          return (
            <button
              key={segId}
              onClick={() => onSelect(segId)}
              className={cn(
                'text-xs px-2.5 py-1 rounded-md transition-colors whitespace-nowrap flex items-center gap-1',
                isActive
                  ? 'bg-warning/15 text-warning font-medium shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
              )}
              title={`段落 ${segId}${totalCount > 0 ? ` · ${mainCount}主 ${suppCount}补` : ''}`}
            >
              S{segId}
              {mainCount > 0 && (
                <span className="text-[9px] px-1 rounded-full bg-success/15 text-success font-medium">
                  {mainCount}
                </span>
              )}
              {suppCount > 0 && (
                <span className="text-[9px] px-1 rounded-full bg-purple/15 text-purple font-medium">
                  {suppCount}
                </span>
              )}
            </button>
          )
        })}
      </div>

      <button
        onClick={onToggleCollapse}
        className="shrink-0 px-2 text-muted-foreground hover:text-foreground"
        title="折叠段落导航"
      >
        <ChevronUp size={14} />
      </button>
    </div>
  )
}
