/**
 * 源定位器 — 可视化整集代理视频 + AI 搜索标记 + 选区管理
 *
 * 交互：
 * - 点击/拖动进度条 → scrub 预览
 * - 热键 I/O 设置入点/出点
 * - 点击 AI 标记 → 自动设入出点
 * - [添加到主时间轴] 按钮提交选区
 */
import { useState, useRef, useCallback } from 'react'
import { ChevronDown, ChevronUp, Plus } from 'lucide-react'
import { cn } from '../lib/utils'

const COLORS = ['#22c55e', '#3b82f6', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4']

export default function SourceLocator({
  episodes, markers, inSec, outSec, activeEp,
  onScrub, onSetIn, onSetOut, onAddToTimeline, onSelectMarker,
  collapsed, onToggleCollapse,
}) {
  const barRef = useRef(null)
  const [hoveredMarker, setHoveredMarker] = useState(null)

  // ALL hooks before any early returns
  const clientXToSec = useCallback((clientX, epDur) => {
    const rect = barRef.current?.getBoundingClientRect()
    if (!rect || !epDur) return 0
    const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    return pct * epDur
  }, [])

  // No episodes → show placeholder
  if (!episodes?.length) {
    return (
      <div className="flex items-center justify-center border-t border-border/50 bg-card/20 text-[10px] text-muted-foreground"
        style={{ height: collapsed ? 24 : 120, flexShrink: 0 }}>
        暂无代理文件，请先生成代理视频
      </div>
    )
  }

  // Collapsed
  if (collapsed) {
    return (
      <div className="flex items-center px-3 border-t border-border/50 bg-card/30"
        style={{ height: 24, flexShrink: 0, cursor: 'pointer' }} onClick={onToggleCollapse}>
        <ChevronDown size={12} className="text-muted-foreground mr-1" />
        <span className="text-[10px] text-muted-foreground">源定位器</span>
        {markers?.length > 0 && <span className="text-[9px] text-warning ml-1">{markers.length} 标记</span>}
      </div>
    )
  }

  return (
    <div className="border-t border-border/50 bg-card/20 overflow-hidden flex flex-col"
      style={{ height: 120, flexShrink: 0 }}>
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-3 py-1 shrink-0" style={{ minHeight: 20 }}>
        <span className="text-[10px] text-muted-foreground flex items-center gap-2">
          源定位器
          {markers?.length > 0 && (
            <span className="text-[9px] px-1 rounded bg-warning/15 text-warning">{markers.length} 标记</span>
          )}
        </span>
        <div className="flex items-center gap-2">
          {inSec != null && outSec != null && outSec > inSec && (
            <button onClick={() => onAddToTimeline(activeEp, inSec, outSec)}
              className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-success/15 text-success hover:bg-success/25 transition-colors">
              <Plus size={10} /> 添加到主时间轴
            </button>
          )}
          <button onClick={onToggleCollapse} className="text-muted-foreground hover:text-foreground">
            <ChevronUp size={12} />
          </button>
        </div>
      </div>

      {/* 剧集条 */}
      <div ref={barRef} className="flex-1 px-3 pb-1 flex flex-col gap-1 overflow-hidden">
        {episodes.map((epData, epIdx) => {
          const dur = epData.durationSec
          const isActive = epData.ep === activeEp
          return (
            <EpisodeBar key={epData.ep}
              epData={epData} isActive={isActive} dur={dur}
              markers={(markers || []).filter(m => m.ep === epData.ep)}
              inSec={isActive ? inSec : null}
              outSec={isActive ? outSec : null}
              color={COLORS[epIdx % COLORS.length]}
              clientXToSec={(x) => clientXToSec(x, dur)}
              onScrub={(sec) => onScrub(epData.ep, sec)}
              onSetIn={(sec) => onSetIn(epData.ep, sec)}
              onSetOut={(sec) => onSetOut(epData.ep, sec)}
              onSelectMarker={onSelectMarker}
              hoveredMarker={hoveredMarker}
              setHoveredMarker={setHoveredMarker}
            />
          )
        })}
      </div>

      {/* 底部提示 */}
      <div className="flex items-center gap-3 px-3 py-0.5 text-[9px] text-muted-foreground/50 shrink-0">
        <span>点击/拖动 bar → scrub</span>
        <span>I/O 热键 → 入/出点</span>
        <span>滚轮 → 缩放</span>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════
// 单集横条
// ═══════════════════════════════════════
function EpisodeBar({
  epData, isActive, dur, markers, inSec, outSec, color,
  clientXToSec, onScrub, onSetIn, onSetOut, onSelectMarker,
  hoveredMarker, setHoveredMarker,
}) {
  const barRef = useRef(null)

  const handleMouseDown = (e) => {
    if (e.target.closest('[data-marker]')) return
    const sec = clientXToSec(e.clientX)
    onScrub(sec)
    const onMove = (ev) => { onScrub(clientXToSec(ev.clientX)) }
    const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  const formatTime = (s) => {
    const m = Math.floor(s / 60)
    const sec = Math.floor(s % 60)
    return `${m}:${String(sec).padStart(2, '0')}`
  }

  return (
    <div className="flex items-center gap-2" style={{ height: 28 }}>
      <span className={cn('text-[10px] font-mono shrink-0 w-8 text-right',
        isActive ? 'text-foreground font-bold' : 'text-muted-foreground')}
        style={{ color: isActive ? color : undefined }}>
        EP{epData.ep}
      </span>

      <div ref={barRef} className="flex-1 h-full relative rounded-sm overflow-hidden cursor-crosshair"
        style={{ background: 'rgba(255,255,255,0.04)' }}
        onMouseDown={handleMouseDown}>

        {/* 选区高亮 */}
        {isActive && inSec != null && outSec != null && outSec > inSec && (
          <div className="absolute inset-y-0 rounded-sm" style={{
            left: `${(inSec / dur) * 100}%`,
            width: `${((outSec - inSec) / dur) * 100}%`,
            background: `${color}22`, border: `1px solid ${color}66`,
          }} />
        )}

        {/* AI 标记 */}
        {markers.map((m, i) => (
          <div key={m.id} data-marker
            className="absolute inset-y-0 cursor-pointer transition-opacity"
            style={{
              left: `${(m.startSec / dur) * 100}%`,
              width: `${Math.max(0.3, ((m.endSec - m.startSec) / dur) * 100)}%`,
              background: `${m.color || COLORS[i % COLORS.length]}66`,
              borderLeft: `2px solid ${m.color || COLORS[i % COLORS.length]}`,
              opacity: hoveredMarker === m.id ? 1 : 0.7,
            }}
            onClick={(e) => { e.stopPropagation(); onSelectMarker(m) }}
            onMouseEnter={() => setHoveredMarker(m.id)}
            onMouseLeave={() => setHoveredMarker(null)}
            title={`EP${m.ep} ${m.startSec}s-${m.endSec}s · ${m.score?.toFixed(1)}分`}>
            {(m.endSec - m.startSec) / dur > 0.03 && (
              <span className="absolute inset-0 flex items-center justify-center text-[7px] text-white/70 truncate px-1 pointer-events-none">
                {m.label || `${m.startSec}s`}
              </span>
            )}
          </div>
        ))}

        {/* 播放头 */}
        {isActive && inSec != null && (
          <div className="absolute inset-y-0 w-0.5 bg-white z-10 pointer-events-none"
            style={{ left: `${(inSec / dur) * 100}%` }} />
        )}
      </div>

      <span className="text-[9px] text-muted-foreground font-mono shrink-0 w-10 text-left">
        {formatTime(dur)}
      </span>
    </div>
  )
}

// ═══════════════════════════════════════
// 选区信息条
// ═══════════════════════════════════════
export function SelectionInfo({ ep, inSec, outSec, onClear, onAdd }) {
  if (inSec == null || outSec == null || outSec <= inSec) return null
  const dur = outSec - inSec
  const format = (s) => { const m = Math.floor(s/60); const sec = Math.floor(s%60); return `${m}:${String(sec).padStart(2,'0')}` }
  return (
    <div className="flex items-center gap-2 px-3 py-1 text-[10px] border-t border-border/30 bg-card/30 shrink-0">
      <span className="text-muted-foreground">选区: <span className="text-foreground font-mono">EP{ep}</span></span>
      <span className="text-warning font-mono">{format(inSec)} – {format(outSec)}</span>
      <span className="text-muted-foreground">({dur.toFixed(1)}s)</span>
      <div className="flex-1" />
      <button onClick={onClear} className="text-muted-foreground hover:text-foreground">清除</button>
      {onAdd && (
        <button onClick={onAdd} className="flex items-center gap-1 px-2 py-0.5 rounded bg-success/15 text-success hover:bg-success/25">
          <Plus size={10} /> 添加到主时间轴
        </button>
      )}
    </div>
  )
}
