/**
 * 搜索面板：ChatPanel 的包装器
 * 嵌入 VibeEdit 左侧栏，提供搜索 + 拖拽入轨能力
 */
import { useState, useCallback } from 'react'
import ChatPanel from './ChatPanel'
import { proxyUrlForEpisode } from '../lib/proxyEngine'

export default function SearchPanel({ context, onPreview, onDragToTimeline, proxyManifest, collapsed, onToggleCollapse }) {
  const [searchResults, setSearchResults] = useState([])

  const handleSearch = useCallback((results) => {
    setSearchResults(results)
  }, [])

  const handlePreview = useCallback((result) => {
    // 通知父组件预览该搜索结果
    onPreview?.(result)
  }, [onPreview])

  // 传递给 ChatPanel，添加拖拽能力
  const handleDragStart = useCallback((e, result) => {
    const proxyUrl = proxyUrlForEpisode(result.ep, proxyManifest)
    const durSec = (result.end || result.sourceEndSec || 0) - (result.start || result.sourceStartSec || 0)

    const dragData = {
      kind: 'vibecap-clip',
      ep: result.ep,
      sourceStartSec: result.sourceStartSec ?? result.start ?? 0,
      sourceEndSec: result.sourceEndSec ?? result.end ?? (result.start ?? 0) + 10,
      durationSec: durSec,
      description: result.description || result.asr || '',
      proxyUrl: proxyUrl || '',
    }

    e.dataTransfer.setData('application/x-vibecap-clip', JSON.stringify(dragData))
    e.dataTransfer.effectAllowed = 'copy'
  }, [proxyManifest])

  if (collapsed) {
    return (
      <div
        className="border-r border-border/50 bg-card/30 flex items-center justify-center"
        style={{ width: 36, cursor: 'pointer' }}
        onClick={onToggleCollapse}
        title="展开搜索面板"
      >
        <span className="text-[10px] text-muted-foreground" style={{ writingMode: 'vertical-rl' }}>
          搜索
        </span>
      </div>
    )
  }

  return (
    <div
      className="flex flex-col border-r border-border/50 overflow-hidden"
      style={{ width: 280, minWidth: 200 }}
    >
      {/* 可拖拽的宽度调整手柄 */}
      <div className="relative">
        <button
          onClick={onToggleCollapse}
          className="absolute right-2 top-2 z-10 text-[10px] text-muted-foreground hover:text-foreground px-1.5 py-0.5 rounded bg-card/80"
          title="折叠搜索面板"
        >
          ◀
        </button>
      </div>

      <ChatPanel
        context={context}
        onPreview={handlePreview}
        onSearch={handleSearch}
        onPick={null}
      />

      {/* 搜索结果拖拽提示 */}
      {searchResults.length > 0 && (
        <div className="px-3 py-1.5 border-t border-border/50 bg-card/30 text-[10px] text-muted-foreground text-center">
          拖拽结果卡片到时间轴即可添加镜头
        </div>
      )}
    </div>
  )
}
