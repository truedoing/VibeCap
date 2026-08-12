// ═══════════════════════════════════════════════
// VibeCut 统一数据模型
// 贯穿 编剧台 → 分镜台 → 剪映导出 的单一数据源
// ═══════════════════════════════════════════════

const STORAGE_KEY = 'vibecut-project'
const FPS = 25
const STAGE = { width: 1920, height: 1080 }

export function createProject(name = '未命名项目') {
  return {
    id: 'vibecut_' + Date.now(), name, fps: FPS, stage: STAGE,
    createdAt: Date.now(), updatedAt: Date.now(),
    segments: [],
    picks: {},
    timeline: null,
    mediaCache: null,
    elahTrackCache: null,
    elahMediaCache: null,
    projectType: null,
    taskName: '',
    workDir: '',
    proxyMode: false,
  }
}

export function loadProject() {
  try { const raw = localStorage.getItem(STORAGE_KEY); return raw ? JSON.parse(raw) : null } catch { return null }
}
export function saveProject(project) {
  if (!project) return
  project.updatedAt = Date.now()
  localStorage.setItem(STORAGE_KEY, JSON.stringify(project))
}

export function getSentencePicks(project, sid) {
  if (!project?.picks) return { main: [], supp: [] }
  const bySeq = {}
  for (const [key, p] of Object.entries(project.picks)) {
    const [sidStr, seqStr] = key.split('_')
    if (parseInt(sidStr) === sid) bySeq[parseInt(seqStr)] = p
  }
  const seqs = Object.keys(bySeq).map(Number).sort((a, b) => a - b)
  return { main: seqs.map(s => bySeq[s].main || []).flat(), supp: seqs.map(s => bySeq[s].supp || []).flat(), bySeq, seqs }
}
export function addPick(project, sid, seq, type, clipRef) {
  const next = { ...project, picks: { ...project.picks }, timeline: null, mediaCache: null }
  const key = `${sid}_${seq}`
  next.picks[key] = next.picks[key] ? { main: [...(next.picks[key].main || [])], supp: [...(next.picks[key].supp || [])] } : { main: [], supp: [] }
  const idx = next.picks[key][type].findIndex(c => c.ep === clipRef.ep && ((clipRef.sourceStartSec !== undefined && c.sourceStartSec === clipRef.sourceStartSec) || (clipRef.start !== undefined && c.start === clipRef.start) || (clipRef.file && c.file === clipRef.file)))
  if (idx >= 0) next.picks[key][type][idx] = { ...next.picks[key][type][idx], ...clipRef }
  else next.picks[key][type].push(clipRef)
  saveProject(next)
  return next
}
export function removePick(project, sid, seq, type, idx) {
  const next = { ...project, picks: { ...project.picks }, timeline: null, mediaCache: null }
  const key = `${sid}_${seq}`
  if (next.picks[key]?.[type]) {
    next.picks[key] = { main: [...(next.picks[key].main || [])], supp: [...(next.picks[key].supp || [])] }
    next.picks[key][type].splice(idx, 1)
    if (next.picks[key].main.length === 0 && next.picks[key].supp.length === 0) delete next.picks[key]
  }
  saveProject(next)
  return next
}
export function saveTimelineCache(project, elahProject, mediaState, prefix = '') {
  const cacheKey = prefix ? `${prefix}_timeline` : 'timeline'
  const mediaKey = prefix ? `${prefix}_mediaCache` : 'mediaCache'
  const next = { ...project, [cacheKey]: elahProject, [mediaKey]: mediaState }
  saveProject(next)
  return next
}
export function getClipStats(project) {
  const picks = project?.picks || {}
  let main = 0, supp = 0
  for (const p of Object.values(picks)) { main += (p.main || []).filter(m => m.file).length; supp += (p.supp || []).filter(s => s.file).length }
  return { main, supp, total: main + supp, sentences: Object.keys(picks).length }
}
export function clipRefKey(ref) { return `${ref.ep}_${ref.start}` }

export function toCapCutDraft(project) {
  const timeline = project?.timeline
  if (!timeline) return null
  const tracks = timeline.tracks || []
  const clips = []
  for (const track of tracks) {
    for (const clip of (track.clips || [])) {
      if (!clip.file) continue
      const segIdMatch = clip.file.match(/_S(\d+)/)
      clips.push({
        seg_id: segIdMatch ? parseInt(segIdMatch[1]) : -1,
        track_type: track.type || 'video',
        track_id: track.id, clip_id: clip.id,
        file: clip.file, ep: clip.ep,
        source_start: clip.sourceStartSec || 0, source_end: clip.sourceEndSec || 0,
        timeline_in: clip.timelineIn / FPS, timeline_out: clip.timelineOut / FPS,
      })
    }
  }
  return { project: project.name || '', fps: FPS, tracks: tracks.length, clips }
}
export function collectVibeClips(elahProject, fps = FPS) {
  if (!elahProject?.tracks) return []
  const clips = []
  for (const track of elahProject.tracks) {
    for (const clip of (track.clips || [])) {
      if (!clip.file) continue
      const epMatch = clip.file.match(/_(\d+)_540p/)
      clips.push({
        track_id: track.id, clip_id: clip.id, file: clip.file,
        ep: epMatch ? parseInt(epMatch[1]) : 0,
        sourceStartSec: clip.sourceStartSec || 0, sourceEndSec: clip.sourceEndSec || 0,
        timelineIn: (clip.timelineIn || 0) / fps, timelineOut: (clip.timelineOut || 0) / fps,
      })
    }
  }
  return clips
}
export function requestVibeExport(taskId, clips) {
  return fetch('/export/extract_clips', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task: taskId, clips: clips.filter(c => c.file) }),
  }).then(r => r.json())
}
export function toCapCutDraftFromExtracted(elahProject, extractedClips, projectName = 'VibeCut Export') {
  if (!elahProject?.tracks || !extractedClips) return null
  const ecMap = {}
  for (const ec of extractedClips) ecMap[ec.clip_id] = ec
  const materials = {}, trackSegments = {}
  let materialIdx = 0, segIdx = 0
  for (const track of elahProject.tracks) {
    const segments = []
    for (const clip of (track.clips || [])) {
      if (!clip.file) continue
      const ec = ecMap[clip.id]
      if (!ec || !ec.extracted_path) continue
      const matId = `mat_${materialIdx++}`
      materials[matId] = { path: ec.extracted_path, duration: (ec.extracted_duration || 0) * 1000000 }
      const sourceDuration = ((clip.sourceEndSec || 0) - (clip.sourceStartSec || 0)) * 1000000
      segments.push({ id: `seg_${segIdx++}`, material_id: matId, source_timerange: { start: 0, duration: sourceDuration }, target_timerange: { start: (clip.timelineIn || 0) / FPS * 1000000, duration: Math.min(sourceDuration, ((clip.timelineOut || 0) - (clip.timelineIn || 0)) / FPS * 1000000) } })
    }
    if (segments.length > 0) trackSegments[track.id] = segments
  }
  return { draft_name: projectName, materials, tracks: Object.entries(trackSegments).map(([tid, segs]) => ({ id: tid, type: 'video', segments: segs })) }
}
export function framesToSec(frames, fps = FPS) { return frames / fps }
export function framesToMicrosec(frames, fps = FPS) { return (frames / fps) * 1000000 }
