/**
 * 分镜序列面板 v3 — 导演Agent 输出
 * 显示分镜方案: 每镜 = 叙事目的 + 匹配源素材
 * Phase 1: 调用 /storyboard_suggest 获取匹配结果
 */
import { useState, useEffect, useCallback } from 'react'
import { Sparkles, Play, Replace, Plus, ChevronDown } from 'lucide-react'
import { cn } from '../lib/utils'
import { font } from '../styles/theme'

/* ── 单镜卡片 ── */
function ShotCard({ shot, index, expanded, onToggle, onPreview, onReplace, onAddToTimeline, isActive }) {
  return (
    <div className={cn(
      'rounded-lg border transition-all',
      isActive ? 'border-purple/50 bg-purple/5' : 'border-border/30 bg-card/30 hover:border-purple/20'
    )}>
      {/* Header */}
      <button onClick={() => onToggle(index)} className="w-full flex items-center gap-2 px-3 py-2 text-left">
        <span className="text-[11px] font-mono font-bold text-purple shrink-0">镜{index + 1}</span>
        <span className="text-[11px] text-foreground/70 truncate flex-1">
          {shot.label || shot.description?.substring(0, 30) || '未命名'}
        </span>
        <ChevronDown className={cn('size-3 text-muted-foreground transition-transform', expanded && 'rotate-180')} />
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-3 pb-2.5 space-y-2 border-t border-border/20 pt-2">
          {/* Shot metadata */}
          <div className="flex items-center gap-2 flex-wrap text-[10px] text-muted-foreground">
            {shot.ep != null && <span className="px-1.5 py-0.5 rounded bg-purple/10 text-purple font-mono">EP{shot.ep}</span>}
            {shot.start != null && (
              <span className="font-mono">{shot.start?.toFixed(0)}s – {shot.end?.toFixed(0)}s</span>
            )}
            {shot.shot_size && <span className="text-foreground/50">{shot.shot_size}</span>}
            {shot.emotional_tone && <span className="text-foreground/50">{shot.emotional_tone}</span>}
          </div>

          {/* Description */}
          <p className="text-[11px] text-foreground/70 leading-relaxed">
            {shot.description || shot.asr || ''}
          </p>

          {/* Actions */}
          <div className="flex items-center gap-1.5">
            <button onClick={() => onPreview(shot)}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-purple/10 text-purple hover:bg-purple/20 transition-colors">
              <Play size={10} />预览
            </button>
            <button onClick={() => onReplace(index)}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-card border border-border/50 text-muted-foreground hover:border-purple/30 hover:text-purple transition-colors">
              <Replace size={10} />替换
            </button>
            <button onClick={() => onAddToTimeline(shot)}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors ml-auto">
              <Plus size={10} />加入时间线
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── 主组件 ── */
export default function StoryboardSequence({ context, proxyManifest, onAddToProgram, taskId }) {
  const [shots, setShots] = useState([])
  const [loading, setLoading] = useState(false)
  const [expandedIdx, setExpandedIdx] = useState(null)
  const [error, setError] = useState(null)

  // 策划分镜触发 — 依赖 trigger 确保每次点击都执行
  useEffect(() => {
    if (context?.trigger == null || context.trigger === 0) return
    fetchStoryboard()
  }, [context?.trigger])

  const fetchStoryboard = useCallback(async () => {
    if (!context?.narration) return
    setLoading(true)
    setError(null)
    setShots([])
    setExpandedIdx(null)

    try {
      const seg = (context.segments || []).find(s => s.seg_id === context.sid)
      const segSentences = (seg?.narration_text || '').split(/[。！？]/).filter(s => s.trim())
      const resp = await fetch(`/storyboard_suggest?task=${taskId || ''}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          narration: context.narration,
          segment_context: { seg_id: context.sid, sentences: segSentences },
          cover: context.cover || '',
        })
      })
      const data = await resp.json()

      // v4: 优先使用结构化 shots 数据，降级解析文本 suggestions
      if (data.shots?.length > 0) {
        const structured = data.shots.map((shot, i) => {
          const best = shot.candidates?.[0] || {}
          return {
            label: shot.purpose || `镜头${i + 1}`,
            description: best.visual_summary || '',
            ep: best.ep,
            start: best.start,
            end: best.end,
            shot_size: best.shot_size || '',
            emotional_tone: best.emotional_tone || '',
            intensity: best.intensity || 0,
            characters: best.characters || [],
            location: best.location || '',
            match_score: best.match_score || 0,
            // 备选候选
            alternatives: (shot.candidates || []).slice(1),
          }
        })
        setShots(structured)
        if (structured.length > 0) setExpandedIdx(0)
      } else if (data.suggestions?.length > 0) {
        // v3 降级：文本解析
        const list = data.suggestions.map(s => s.replace(/^镜头\d+[：:]\s*/, ''))
        const parsed = list.map(parseShotText)
        setShots(parsed)
        if (parsed.length > 0) setExpandedIdx(0)
      }
    } catch (e) {
      setError('分镜生成失败，请重试')
    } finally {
      setLoading(false)
    }
  }, [context, taskId])

  // 解析 "EP27 [340s] 苏明玉质问... | ASR: "你怎么..." " → {ep, start, description, asr}
  const parseShotText = (text) => {
    const shot = { raw: text, description: text }
    const epMatch = text.match(/EP(\d+)/)
    if (epMatch) shot.ep = parseInt(epMatch[1])
    const timeMatch = text.match(/\[(\d+)s\]/)
    if (timeMatch) {
      shot.start = parseFloat(timeMatch[1])
      shot.end = shot.start + 8
    }
    // 提取时间范围
    const rangeMatch = text.match(/\[(\d+)s-(\d+)s\]/)
    if (rangeMatch) {
      shot.start = parseFloat(rangeMatch[1])
      shot.end = parseFloat(rangeMatch[2])
    }
    const asrMatch = text.match(/\| ASR:\s*"([^"]*)"/)
    if (asrMatch) shot.asr = asrMatch[1]
    // 去掉 ASR 部分作为纯描述
    shot.description = text.replace(/\s*\| ASR:\s*"[^"]*"/, '')
    return shot
  }

  const handlePreview = (shot) => {
    if (shot.ep != null && window.__sourceLoadEpisode) {
      window.__sourceLoadEpisode(shot.ep, shot.start || 0, shot.end || (shot.start + 8))
    }
  }

  const handleReplace = (index) => {
    setShots(prev => {
      const next = [...prev]
      const shot = next[index]
      if (shot?.alternatives?.length > 0) {
        const alt = shot.alternatives[0]
        const remaining = shot.alternatives.slice(1)
        // 当前选择的移到备选末尾
        const currentAsAlt = {
          ep: shot.ep, start: shot.start, end: shot.end,
          visual_summary: shot.description,
          shot_size: shot.shot_size, emotional_tone: shot.emotional_tone,
          intensity: shot.intensity, characters: shot.characters,
          location: shot.location, match_score: shot.match_score,
        }
        next[index] = {
          ...shot,
          ep: alt.ep, start: alt.start, end: alt.end,
          description: alt.visual_summary || '',
          shot_size: alt.shot_size || '', emotional_tone: alt.emotional_tone || '',
          intensity: alt.intensity || 0,
          characters: alt.characters || [],
          location: alt.location || '',
          match_score: alt.match_score || 0,
          alternatives: [...remaining, currentAsAlt],
        }
      }
      return next
    })
  }

  const handleAddToTimeline = (shot) => {
    if (shot.ep == null) return
    const FPS = 25
    const inFrames = Math.round((shot.start || 0) * FPS)
    const outFrames = Math.round((shot.end || (shot.start + 8)) * FPS)
    onAddToProgram?.(shot.ep, inFrames, outFrames, 'main')
  }

  const hasShots = shots.length > 0
  const showEmpty = !loading && !hasShots && !error

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border/50 shrink-0">
        <Sparkles size={13} className="text-purple" />
        <span className="text-xs font-medium text-foreground">分镜序列</span>
        {context?.sid != null && (
          <span className="text-[10px] text-purple/70 font-mono ml-auto">S{context.sid}</span>
        )}
        <button
          onClick={fetchStoryboard}
          disabled={loading || context?.sid == null}
          className={cn(
            'text-[10px] px-2 py-0.5 rounded-md transition-colors',
            loading
              ? 'bg-purple/10 text-purple/50 cursor-wait'
              : 'bg-purple/15 text-purple hover:bg-purple/25'
          )}
        >
          {loading ? '策划中...' : hasShots ? '重新策划' : '策划分镜'}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1.5">
        {loading && (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <div className="flex gap-1">
              <span className="w-2 h-2 rounded-full bg-purple/40 animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-2 h-2 rounded-full bg-purple/40 animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-2 h-2 rounded-full bg-purple/40 animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
            <span className="text-[11px] text-muted-foreground">导演正在策划分镜...</span>
          </div>
        )}

        {showEmpty && (
          <div className="flex flex-col items-center justify-center py-12 gap-2 text-center">
            <Sparkles size={24} className="text-purple/30" />
            <p className="text-xs text-muted-foreground">
              {context?.sid != null ? '点击「策划分镜」为当前段生成分镜方案' : '先在左侧选择一个解说段落'}
            </p>
          </div>
        )}

        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-[11px] text-red-400">
            {error}
            <button onClick={fetchStoryboard} className="ml-2 underline hover:text-red-300">重试</button>
          </div>
        )}

        {hasShots && shots.map((shot, i) => (
          <ShotCard key={i} shot={shot} index={i}
            expanded={expandedIdx === i} isActive={expandedIdx === i}
            onToggle={setExpandedIdx}
            onPreview={handlePreview} onReplace={handleReplace}
            onAddToTimeline={handleAddToTimeline} />
        ))}

        {hasShots && (
          <button
            onClick={() => shots.forEach(s => handleAddToTimeline(s))}
            className="w-full mt-2 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-medium hover:bg-emerald-500/20 transition-colors"
          >
            全部加入时间线
          </button>
        )}
      </div>
    </div>
  )
}
