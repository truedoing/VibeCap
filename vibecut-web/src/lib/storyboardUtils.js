/**
 * 分镜脚本（storyboard.json）→ 时间轴数据 工具
 *
 * 把扣子/WorkBuddy 产出的全局分镜脚本翻译成 timelineBuilder 能吃的 picks。
 * 关键：扣子的 timecode（in_point）是准的，scene_id 是幻觉 → 直接用 timecode 铺轨。
 */

/* "00:03:40" → 秒 */
export function tcToSec(tc) {
  if (tc == null || tc === '') return null
  if (typeof tc === 'number') return tc
  const parts = String(tc).split(':').map(Number)
  if (parts.some(isNaN)) return null
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  return parts[0]
}

/* 从 source_file "都挺好 21_1080p.mp4" 提取 ep=21 */
export function epFromSourceFile(sourceFile) {
  if (!sourceFile) return null
  const m = String(sourceFile).match(/(\d+)[_\s-]*1080p/)
  if (m) return parseInt(m[1])
  const m2 = String(sourceFile).match(/[eE][pP]?(\d+)/)
  return m2 ? parseInt(m2[1]) : null
}

/* 顶层 source_files 反查：文件名 → ep */
export function buildSourceFileToEp(sourceFiles) {
  const map = {}
  if (sourceFiles) {
    for (const [k, v] of Object.entries(sourceFiles)) {
      const ep = String(k).replace(/^ep/i, '')
      if (/^\d+$/.test(ep)) map[v] = parseInt(ep)
    }
  }
  return map
}

/* 解析单个 shot 的源画面（ep + startSec + endSec），无源返回 null */
export function resolveShotSource(shot, sourceFileToEp = {}) {
  const ep = epFromSourceFile(shot.source_file) ?? sourceFileToEp[shot.source_file]
  const startSec = tcToSec(shot.in_point)
  if (ep == null || startSec == null) return null
  const dur = shot.duration_sec
    ?? (shot.out_point ? (tcToSec(shot.out_point) ?? startSec + 5) - startSec : 5)
  return { ep, startSec, endSec: startSec + Math.max(1, dur) }
}

/**
 * 把 storyboard.json 翻译成 picks 结构。
 *
 * picks 契约（timelineBuilder.buildProjectFromProxyPicks 消费）：
 *   { "<seg_id>_0": { main: [{ep, sourceStartSec, sourceEndSec}], supp: [...] } }
 *
 * 分轨规则（纯段类型驱动，不是 shot_type）：
 *   - narration 段（解说）：所有镜头 → supp 轨（静音，配旁白音频）
 *   - dialogue 段（台词）：所有镜头 → main 轨（带原声，台词画面）
 *
 * 关键：seg_id = seq - 1（storyboard 的 seq 从 1 开始，segments/narration 的 seg_id 从 0 开始）
 *
 * 返回 { picks, stats, segType, segDurMap }
 *   segType: { seg_id: 'narration' | 'dialogue' }
 *   segDurMap: { seg_id: 画面估算时长(秒) }  // narration 段会被音频真实时长覆盖
 */
export function buildPicksFromStoryboard(storyboard) {
  if (!storyboard?.segments?.length) {
    return { picks: {}, stats: { totalShots: 0, placedShots: 0, skippedShots: 0 }, segType: {}, segDurMap: {} }
  }

  const sourceFileToEp = buildSourceFileToEp(storyboard.source_files)
  const picks = {}
  const segType = {}
  const segDurMap = {}
  let placed = 0, skipped = 0, total = 0

  for (const seg of storyboard.segments) {
    const segId = (seg.seq ?? 1) - 1  // seq(1-based) → seg_id(0-based)
    const segKind = seg.type === 'dialogue' ? 'dialogue' : 'narration'
    segType[segId] = segKind

    const shots = seg.shot_sequence || []
    const mainList = []
    const suppList = []

    for (const shot of shots) {
      total++
      const src = resolveShotSource(shot, sourceFileToEp)
      if (!src) { skipped++; continue }
      const ref = { ep: src.ep, sourceStartSec: src.startSec, sourceEndSec: src.endSec }

      // 纯段类型分轨：dialogue 段所有镜头进原声轨，narration 段所有镜头进静音补充轨
      if (segKind === 'dialogue') {
        mainList.push(ref)
      } else {
        suppList.push(ref)
      }
    }

    // 画面估算时长（shot 的 duration_sec 之和）
    const segDur = shots.reduce((n, s) => n + (s.duration_sec || 0), 0)
    segDurMap[segId] = segDur

    if (mainList.length || suppList.length) {
      picks[`${segId}_0`] = { main: mainList, supp: suppList }
      placed += mainList.length + suppList.length
    }
  }

  return {
    picks,
    stats: { totalShots: total, placedShots: placed, skippedShots: skipped },
    segType,
    segDurMap,
  }
}
