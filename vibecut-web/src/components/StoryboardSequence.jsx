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
function ShotCard({ shot, index, expanded, onToggle, onPreview, onAddToTimeline, onSelectCandidate, isActive }) {
  return (
    <div className={cn(
      'rounded-lg border transition-all',
      isActive ? 'border-purple/50 bg-purple/5' : 'border-border/30 bg-card/30 hover:border-purple/20'
    )}>
      {/* Header */}
      <button onClick={() => onToggle(index)} className="w-full flex items-center gap-2 px-3 py-2 text-left">
        <span className={cn(
          'text-[10px] font-mono font-bold shrink-0 px-1 py-0.5 rounded',
          shot.priority === 'KEY' ? 'bg-purple/20 text-purple' :
          shot.priority === 'BRIDGE' ? 'bg-blue/20 text-blue-400' :
          'bg-muted text-muted-foreground'
        )}>
          {shot.priority === 'KEY' ? 'KEY' : shot.priority === 'BRIDGE' ? 'BRG' : 'MOOD'}
        </span>
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

          {/* ★ 备选镜头列表 — 可点击直接选择 */}
          {shot.alternatives?.length > 0 && (
            <div className="space-y-1 mt-1.5 pt-1.5 border-t border-border/10">
              <span className="text-[10px] text-muted-foreground">备选镜头 ({shot.alternatives.length}个):</span>
              {shot.alternatives.map((alt, j) => (
                <button
                  key={j}
                  onClick={() => onSelectCandidate(index, j)}
                  className="w-full text-left px-2 py-1.5 rounded text-[10px] bg-card/50 hover:bg-purple/10 hover:text-purple transition-colors flex items-start gap-1.5"
                >
                  <span className="text-purple/60 font-mono shrink-0 mt-0.5">#{j + 2}</span>
                  <span className="flex-1 leading-snug">
                    EP{alt.ep} [{alt.start?.toFixed(0)}s] {alt.visual_summary?.substring(0, 60)}
                  </span>
                  {alt.match_score != null && (
                    <span className="text-muted-foreground/50 shrink-0">+{alt.match_score}</span>
                  )}
                </button>
              ))}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-1.5">
            <button onClick={() => onPreview(shot)}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-purple/10 text-purple hover:bg-purple/20 transition-colors">
              <Play size={10} />预览
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
  const [reasoning, setReasoning] = useState(null)  // v8.2: Agent推理过程
  const [showReasoning, setShowReasoning] = useState(true)  // 默认展开推理

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
      const segments = context.segments || []
      const seg = segments.find(s => s.seg_id === context.sid)
      const segSentences = (seg?.narration_text || '').split(/[。！？]/).filter(s => s.trim())

      const idx = segments.findIndex(s => s.seg_id === context.sid)

      let prevHighlight = ''
      let nextHighlight = ''
      const focusEpisodes = new Set()
      if (idx >= 0) {
        for (let i = idx - 1; i >= 0; i--) {
          if (segments[i]?.highlight_text) {
            prevHighlight = segments[i].highlight_text
            break
          }
        }
        for (let i = idx + 1; i < segments.length; i++) {
          if (segments[i]?.highlight_text) {
            nextHighlight = segments[i].highlight_text
            break
          }
        }
        for (const s of segments) {
          const em = s.episode_marker
          if (em?.episode) focusEpisodes.add(em.episode)
        }
      }

      const resp = await fetch(`/storyboard_suggest?task=${taskId || ''}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          narration: context.narration,
          segment_context: { seg_id: context.sid, sentences: segSentences },
          cover: context.cover || '',
          prev_highlight: prevHighlight,
          next_highlight: nextHighlight,
          focus_episodes: [...focusEpisodes],
        })
      })
      const data = await resp.json()

      // v8: 解析 PRIMARY/SECONDARY 主辅镜头 + 导演手法
      if (data.shots?.length > 0) {
        const structured = data.shots.map((shot, i) => {
          // v8: primary + secondary structure
          const pri = shot.primary || shot
          const priBest = pri.candidates?.[0] || {}
          const priQuery = pri.query || {}
          const secs = (shot.secondary || []).map(sec => {
            const sBest = sec.candidates?.[0] || {}
            return {
              label: sec.purpose || '',
              description: sBest.visual_summary || '',
              ep: sBest.ep, start: sBest.start, end: sBest.end,
              shot_size: sBest.shot_size || '',
              emotional_tone: sBest.emotional_tone || '',
              intensity: sBest.intensity || 0,
              characters: sBest.characters || [],
              location: sBest.location || '',
              match_score: sBest.match_score || 0,
              shot_role: sec.shot_role || 'SECONDARY',
              alternatives: (sec.candidates || []).slice(1),
            }
          })
          return {
            label: pri.purpose || `镜头${i + 1}`,
            description: priBest.visual_summary || '',
            ep: priBest.ep,
            start: priBest.start,
            end: priBest.end,
            shot_size: priBest.shot_size || '',
            emotional_tone: priBest.emotional_tone || '',
            intensity: priBest.intensity || 0,
            characters: priBest.characters || [],
            location: priBest.location || '',
            match_score: priBest.match_score || 0,
            priority: priQuery.priority || 'KEY',
            beat_index: priQuery.beat_index != null ? priQuery.beat_index : i,
            director_technique: shot.director_technique || '',
            technique_hint: shot.technique_hint || '',
            // 备选候选
            alternatives: (pri.candidates || []).slice(1),
            // v8: secondary shots
            secondary: secs,
          }
        })
        setShots(structured)
        if (structured.length > 0) setExpandedIdx(0)

        // v8.2: 提取推理过程
        const reasonData = data.reasoning
        if (reasonData) {
          const steps = []
          // Step 1: 锚定
          if (reasonData.anchor?.focus_episodes?.length) {
            steps.push(`🎯 锚定标的剧集: EP${reasonData.anchor.focus_episodes.join(', EP')}`)
            steps.push(`   来源: ${reasonData.anchor.source}`)
          }
          // Step 2: 节拍拆解
          if (reasonData.beats?.length) {
            const vCount = reasonData.beats.filter(b => b.has_visual).length
            const cCount = reasonData.beats.filter(b => !b.has_visual).length
            steps.push(`📐 叙事节拍: ${reasonData.beats.length}个 (${vCount}画面化 + ${cCount}留白)`)
            reasonData.beats.forEach(b => {
              const icon = b.has_visual ? '🎬' : '📝'
              steps.push(`   ${icon} [${b.type}] ${b.text}`)
            })
          }
          // Step 3: 匹配推理
          if (reasonData.shots_matching?.length) {
            reasonData.shots_matching.forEach((sm, i) => {
              const top = sm.top3_candidates?.[0]
              steps.push(`🔍 PRIMARY "${sm.primary_purpose}" → EP${top?.ep} score=${top?.score}`)
              steps.push(`   查询: chars=${sm.query?.characters?.join(',')} shot=${sm.query?.shot_size} emotion=${sm.query?.emotional_tone?.join(',')}`)
              steps.push(`   搜索策略: ${sm.search_strategy}`)
              sm.top3_candidates?.forEach((c, j) => {
                steps.push(`   ${j === 0 ? '▶' : ' '} [${c.rank}] EP${c.ep} score=${c.score} — ${c.why}`)
              })
              sm.secondary_reasoning?.forEach(sec => {
                steps.push(`   +${sec.role}: ${sec.purpose} ${sec.search_scope} → EP${sec.top_candidate?.ep}`)
              })
            })
          }
          // Step 4: 统计
          if (reasonData.statistics) {
            const s = reasonData.statistics
            steps.push(`📊 总结: ${s.total_beats}节拍 → ${s.primary_shots}组PRIMARY + ${s.secondary_shots}SECONDARY | 锚定命中 ${s.anchor_hit_rate}`)
          }
          setReasoning({ steps, raw: reasonData })
        }
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

  // v8: 直接从备选列表中选择某个候选镜头
  const handleSelectCandidate = (shotIndex, altIndex) => {
    setShots(prev => {
      const next = [...prev]
      const shot = next[shotIndex]
      if (!shot?.alternatives || altIndex >= shot.alternatives.length) return prev
      const selected = shot.alternatives[altIndex]
      // 把当前选择的移到备选末尾
      const currentAsAlt = {
        ep: shot.ep, start: shot.start, end: shot.end,
        visual_summary: shot.description,
        shot_size: shot.shot_size, emotional_tone: shot.emotional_tone,
        intensity: shot.intensity, characters: shot.characters,
        location: shot.location, match_score: shot.match_score,
      }
      const remaining = [...shot.alternatives]
      remaining.splice(altIndex, 1)
      next[shotIndex] = {
        ...shot,
        ep: selected.ep, start: selected.start, end: selected.end,
        description: selected.visual_summary || '',
        shot_size: selected.shot_size || '', emotional_tone: selected.emotional_tone || '',
        intensity: selected.intensity || 0,
        characters: selected.characters || [],
        location: selected.location || '',
        match_score: selected.match_score || 0,
        alternatives: [...remaining, currentAsAlt],
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
        {/* v8.2: Agent推理过程 */}
        {reasoning && (
          <div className="rounded-lg border border-purple/20 bg-purple/[0.03] overflow-hidden">
            <button
              onClick={() => setShowReasoning(!showReasoning)}
              className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-purple/[0.06] transition-colors"
            >
              <Sparkles size={12} className="text-purple/70" />
              <span className="text-[11px] font-medium text-purple/80">导演推理过程</span>
              <span className="text-[10px] text-muted-foreground ml-auto">
                {reasoning.steps?.length || 0} 步
              </span>
              <ChevronDown className={cn('size-3 text-muted-foreground transition-transform', showReasoning && 'rotate-180')} />
            </button>
            {showReasoning && (
              <div className="px-3 pb-3 pt-0 border-t border-purple/10">
                <div className="mt-2 space-y-0.5 font-mono text-[10px] text-foreground/60 leading-relaxed max-h-[300px] overflow-y-auto">
                  {(reasoning.steps || []).map((step, i) => {
                    // 识别步骤类型给不同颜色
                    const isHeader = step.startsWith('🎯') || step.startsWith('📐') || step.startsWith('🔍') || step.startsWith('📊')
                    const isSub = step.startsWith('   ')
                    const cls = isHeader ? 'text-purple/80 mt-1.5 font-semibold' :
                               isSub ? 'text-foreground/40' :
                               'text-foreground/60'
                    return <div key={i} className={cls}>{step}</div>
                  })}
                </div>
              </div>
            )}
          </div>
        )}
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
            onPreview={handlePreview} onSelectCandidate={handleSelectCandidate}
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
