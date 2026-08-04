/**
 * 当前段落镜头管理面板
 * 显示主镜头/补充镜头列表，支持删除操作
 */
import { X, Video, Camera } from 'lucide-react'
import { cn } from '../lib/utils'

export default function PickPanel({ sid, seq, picks, onRemovePick, onAddPick }) {
  const key = sid != null && seq != null ? `${sid}_${seq}` : null
  const currentPicks = key && picks?.[key] ? picks[key] : { main: [], supp: [] }
  const hasMain = currentPicks.main?.length > 0
  const hasSupp = currentPicks.supp?.length > 0
  const isEmpty = !hasMain && !hasSupp

  if (sid == null) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-3">
        <Video size={28} className="text-muted-foreground/30 mb-2" />
        <p className="text-[11px] text-muted-foreground">选择解说段落</p>
        <p className="text-[10px] text-muted-foreground/50 mt-1">点击上方段落或左侧搜索</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* 标题 */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/50 bg-card/30 shrink-0">
        <span className="text-xs font-medium text-foreground">
          S{sid}-{seq} 镜头
        </span>
        <span className="text-[10px] text-muted-foreground">
          {hasMain ? `${currentPicks.main.length}主` : ''}
          {hasMain && hasSupp ? ' · ' : ''}
          {hasSupp ? `${currentPicks.supp.length}补` : ''}
        </span>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto custom-scrollbar px-2 py-2 space-y-2">
        {isEmpty && (
          <div className="text-center py-6">
            <Camera size={22} className="text-muted-foreground/20 mx-auto mb-1.5" />
            <p className="text-[10px] text-muted-foreground/50">搜索并拖拽素材</p>
            <p className="text-[10px] text-muted-foreground/50">到此区域或时间轴</p>
          </div>
        )}

        {/* 主镜头 */}
        {hasMain && currentPicks.main.map((m, i) => (
          <PickCard
            key={`main-${i}`}
            clip={m}
            label="主"
            color="success"
            onRemove={() => onRemovePick(sid, seq, 'main', i)}
          />
        ))}

        {/* 补充镜头 */}
        {hasSupp && currentPicks.supp.map((s, i) => (
          <PickCard
            key={`supp-${i}`}
            clip={s}
            label="补"
            color="purple"
            onRemove={() => onRemovePick(sid, seq, 'supp', i)}
          />
        ))}
      </div>

      {/* 底部操作 */}
      <div className="shrink-0 p-2 border-t border-border/50 bg-card/20">
        <div className="flex gap-1.5">
          <button
            onClick={() => onAddPick?.('main')}
            className="flex-1 text-[10px] px-2 py-1.5 rounded-md border border-success/30 text-success/80 hover:bg-success/5 transition-colors"
          >
            + 主镜头
          </button>
          <button
            onClick={() => onAddPick?.('supp')}
            className="flex-1 text-[10px] px-2 py-1.5 rounded-md border border-purple/30 text-purple/80 hover:bg-purple/5 transition-colors"
          >
            + 补充
          </button>
        </div>
      </div>
    </div>
  )
}

function PickCard({ clip, label, color, onRemove }) {
  const dur = clip.sourceEndSec !== undefined
    ? (clip.sourceEndSec - clip.sourceStartSec).toFixed(1)
    : (clip.duration || '—')

  return (
    <div className={cn(
      'flex items-center gap-2 p-2 rounded-lg border transition-colors group',
      color === 'success'
        ? 'border-success/20 bg-success/[0.03] hover:bg-success/[0.06]'
        : 'border-purple/20 bg-purple/[0.03] hover:bg-purple/[0.06]'
    )}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={cn(
            'text-[9px] px-1 py-0 rounded-sm font-bold',
            color === 'success' ? 'bg-success/15 text-success' : 'bg-purple/15 text-purple'
          )}>{label}</span>
          <span className="text-[10px] text-muted-foreground font-mono">EP{clip.ep}</span>
        </div>
        <p className="text-[10px] text-foreground/70 mt-0.5 truncate">
          {(clip.sourceStartSec ?? clip.start ?? 0).toFixed(0)}s – {(clip.sourceEndSec ?? clip.end ?? 0).toFixed(0)}s
          <span className="text-muted-foreground/50 ml-1">({dur}s)</span>
        </p>
      </div>
      <button
        onClick={onRemove}
        className="shrink-0 text-muted-foreground/0 group-hover:text-muted-foreground hover:text-red-400 transition-all"
        title="移除"
      >
        <X size={14} />
      </button>
    </div>
  )
}
