import { useNavigate } from 'react-router-dom'
import { useProject } from '../context/ProjectContext'
import { Film, Mic, ChevronRight } from 'lucide-react'
import { useState, useEffect } from 'react'

const NARR_DURATIONS = { 0: 26, 1: 24, 2: 12, 3: 5, 4: 15, 5: 56, 6: 18, 7: 18, 8: 45 }

export default function TaskOverview() {
  const { project, seriesId, taskId } = useProject()
  const nav = useNavigate()
  const [segments, setSegments] = useState([])

  useEffect(() => {
    fetch(`/segments.json?task=${taskId}`)
      .then(r => r.json())
      .then(data => setSegments(data.segments || data))
      .catch(() => setSegments([]))
  }, [taskId])

  const picks = project?.picks || {}

  // 按 seg_id 分组统计 picks
  const pickStats = {}
  for (const [key, p] of Object.entries(picks)) {
    const [sidStr] = key.split('_')
    const sid = parseInt(sidStr)
    if (!pickStats[sid]) pickStats[sid] = { main: 0, supp: 0 }
    pickStats[sid].main += (p.main || []).filter(m => m.file).length
    pickStats[sid].supp += (p.supp || []).filter(s => s.file).length
  }

  const totalMain = Object.values(pickStats).reduce((s, v) => s + v.main, 0)
  const totalSupp = Object.values(pickStats).reduce((s, v) => s + v.supp, 0)
  const totalTTS = Object.values(NARR_DURATIONS).reduce((s, v) => s + v, 0)

  return (
    <div className="flex-1 flex flex-col overflow-auto bg-background">
      <div className="max-w-3xl mx-auto w-full p-6">
        {/* 任务概览卡片 */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center gap-2 mb-1">
              <Film size={14} className="text-blue-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">主镜头</span>
            </div>
            <span className="text-2xl font-bold text-foreground">{totalMain}</span>
            <span className="text-xs text-muted-foreground ml-1">个</span>
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center gap-2 mb-1">
              <Film size={14} className="text-purple-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">补充镜头</span>
            </div>
            <span className="text-2xl font-bold text-foreground">{totalSupp}</span>
            <span className="text-xs text-muted-foreground ml-1">个</span>
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center gap-2 mb-1">
              <Mic size={14} className="text-green-400" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">解说音频</span>
            </div>
            <span className="text-2xl font-bold text-foreground">{totalTTS}</span>
            <span className="text-xs text-muted-foreground ml-1">秒</span>
          </div>
        </div>

        {/* 分段列表 */}
        <h3 className="text-sm font-medium text-foreground mb-3">解说分段</h3>
        {segments.length === 0 ? (
          <p className="text-xs text-muted-foreground py-8 text-center">加载中...</p>
        ) : (
          <div className="space-y-1">
            {segments.map((seg, i) => {
              const stats = pickStats[seg.seg_id] || { main: 0, supp: 0 }
              const narrDur = NARR_DURATIONS[seg.seg_id] || 0
              const sentences = seg.sentences || seg.narration || []
              const done = stats.main > 0 || stats.supp > 0

              return (
                <button
                  key={seg.seg_id}
                  onClick={() => nav(`/${seriesId}/${taskId}/planning?sid=${seg.seg_id}`)}
                  className="w-full flex items-center gap-3 px-4 py-3 rounded-lg border border-border bg-card hover:bg-accent/50 transition-colors text-left"
                >
                  {/* 序号 */}
                  <span className="text-xs font-mono text-muted-foreground w-8 shrink-0">
                    S{seg.seg_id}
                  </span>

                  {/* 预览文本 */}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-foreground/80 truncate">
                      {Array.isArray(sentences)
                        ? sentences.map(s => typeof s === 'string' ? s : s.text).join(' ').substring(0, 60) + (sentences.length > 0 ? '...' : '')
                        : String(sentences).substring(0, 60)}
                    </p>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-[10px] text-muted-foreground">
                        {Array.isArray(sentences) ? sentences.length : 0} 句
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        解说 {narrDur}s
                      </span>
                    </div>
                  </div>

                  {/* 选取状态 */}
                  <div className="flex items-center gap-2 shrink-0">
                    {stats.main > 0 && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">
                        {stats.main}主
                      </span>
                    )}
                    {stats.supp > 0 && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400">
                        {stats.supp}补
                      </span>
                    )}
                    {!done && (
                      <span className="text-[10px] text-muted-foreground/50">待选</span>
                    )}
                    <ChevronRight size={14} className="text-muted-foreground/30" />
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
