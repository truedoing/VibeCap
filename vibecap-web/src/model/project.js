// ═══════════════════════════════════════════════
// VibeCut 统一数据模型
// 贯穿 匹配台 → 剪辑台 → 剪映导出 的单一数据源
// ═══════════════════════════════════════════════

const STORAGE_KEY = 'vibecap-project'
const FPS = 25
const STAGE = { width: 1920, height: 1080 }

// ── 工厂函数：创建空项目 ──
export function createProject(name = '未命名项目') {
  return {
    id: 'vibecap_' + Date.now(),
    name,
    fps: FPS,
    stage: STAGE,
    createdAt: Date.now(),
    updatedAt: Date.now(),

    // 解说文案（从 segments.json 加载）
    segments: [],

    // ── 素材选择 picks ──
    // { "sid_seq": { main: [ClipRef], supp: [ClipRef] } }
    // ClipRef = { ep, start, end, file, duration }
    picks: {},

    // ── 时间线编辑（从 Elah 导出/导入） ──
    // Elah Project 对象，含 tracks/clips/transitions
    timeline: null,

    // ── 媒体库缓存 ──
    // { assets: {...}, order: [...] }
    mediaCache: null,
  }
}

// ── localStorage 读写 ──
export function loadProject() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch (e) { /* ignore */ }
  return createProject()
}

export function saveProject(project) {
  project.updatedAt = Date.now()
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(project))
  } catch (e) { /* ignore */ }
}

// ── picks 操作 ──
export function getSentencePicks(project, sid, seq) {
  const key = `${sid}_${seq}`
  return project.picks[key] || { main: [], supp: [] }
}

export function addPick(project, sid, seq, type, clipRef) {
  const key = `${sid}_${seq}`
  if (!project.picks[key]) project.picks[key] = { main: [], supp: [] }
  // 同 ep+start 则更新（保留新的 file），否则追加
  const idx = project.picks[key][type].findIndex(c => c.ep === clipRef.ep && c.start === clipRef.start)
  if (idx >= 0) {
    project.picks[key][type][idx] = { ...project.picks[key][type][idx], ...clipRef }
  } else {
    project.picks[key][type].push(clipRef)
  }
  // 素材变了，清除时间线缓存让剪辑台重建
  project.timeline = null
  project.mediaCache = null
  saveProject(project)
}

export function removePick(project, sid, seq, type, idx) {
  const key = `${sid}_${seq}`
  if (project.picks[key]?.[type]) {
    project.picks[key][type].splice(idx, 1)
    if (project.picks[key].main.length === 0 && project.picks[key].supp.length === 0) {
      delete project.picks[key]
    }
  }
  // 清除时间线缓存（素材变了）
  project.timeline = null
  project.mediaCache = null
  saveProject(project)
}

// ── 时间线缓存 ──
export function saveTimelineCache(project, elahProject, mediaState) {
  project.timeline = elahProject
  project.mediaCache = mediaState
  //
  saveProject(project)
}

// ── 统计 ──
export function getClipStats(project) {
  let mainCount = 0, suppCount = 0
  for (const p of Object.values(project.picks)) {
    mainCount += p.main?.length || 0
    suppCount += p.supp?.length || 0
  }
  return { mainCount, suppCount, total: mainCount + suppCount, sentenceCount: Object.keys(project.picks).length }
}

// ── clipRef 辅助 ──
export function clipRefKey(ref) {
  return `${ref.ep}_${ref.start}`
}

// ═══════════════════════════════════════════════
// 剪映草稿导出（CapCut Draft Format）
// ═══════════════════════════════════════════════

/**
 * 将 Elah timeline 转换为剪映草稿 JSON 结构
 * 剪映草稿规范：https://github.com/Jianying-Draft
 */
export function toCapCutDraft(project) {
  const allTracks = []
  const allMaterials = {}
  let materialSeq = 0

  if (!project.timeline || !project.timeline.tracks) {
    return null
  }

  for (const track of project.timeline.tracks) {
    const clips = project.timeline.clips[track.id] || []
    if (clips.length === 0) continue

    const segments = clips.map(clip => {
      // 注册素材
      const materialId = `material_${++materialSeq}`
      if (clip.src) {
        allMaterials[materialId] = {
          id: materialId,
          path: clip.src.replace(/^\/clips\//, '').replace(/^\//, ''),
          type: clip.type === 'audio' ? 'audio' : 'video',
          duration: framesToSec(clip.durationFrames, project.fps),
        }
      }

      return {
        id: clip.id,
        material_id: materialId,
        target_timerange: {
          start: framesToMicrosec(clip.startFrame, project.fps),
          duration: framesToMicrosec(clip.durationFrames, project.fps),
        },
        source_timerange: {
          start: framesToMicrosec(clip.sourceStartFrame, project.fps),
          duration: framesToMicrosec(clip.sourceDurationFrames, project.fps),
        },
        speed: 1.0,
        volume: clip.volume ?? 1,
        clip: {
          transform: clip.transform || { x: 0, y: 0, scale: 1, rotation: 0, anchor: { x: 0, y: 0 } },
          opacity: clip.opacity ?? 1,
        },
      }
    })

    allTracks.push({
      id: track.id,
      type: track.kind === 'audio' ? 'audio' : 'video',
      name: track.name,
      is_muted: track.muted,
      segments,
    })
  }

  // 计算总时长
  const totalFrames = Object.values(project.timeline.clips || {}).flat().reduce(
    (max, c) => Math.max(max, c.startFrame + c.durationFrames), 0
  )

  return {
    draft_name: project.name,
    draft_id: project.id,
    draft_version: 1,
    draft_root_path: '',
    draft_fps: project.fps,
    draft_resolution: project.stage,
    draft_total_duration: framesToMicrosec(totalFrames, project.fps),
    draft_materials: Object.values(allMaterials),
    draft_tracks: allTracks,
    draft_cover: '',
    created_at: project.createdAt,
    updated_at: project.updatedAt,
  }
}

// ── 单位转换 ──
function framesToSec(frames, fps) {
  return frames / fps
}

function framesToMicrosec(frames, fps) {
  return Math.round((frames / fps) * 1_000_000)
}

// ═══════════════════════════════════════════════
// Vibe 导出（代理模式 → 1080p 提取 → 剪映草稿）
// ═══════════════════════════════════════════════

/**
 * 从 Elah project 收集所有需要导出的 clip 引用
 * 代理模式下 clip.src 是 /proxies/xxx.mp4，需从 sourceStartFrame/sourceDurationFrames 反推时间
 */
export function collectVibeClips(elahProject, fps = 25) {
  if (!elahProject?.tracks) return []

  const clips = []
  for (const track of elahProject.tracks) {
    const trackClips = elahProject.clips[track.id] || []
    for (const clip of trackClips) {
      if (clip.type === 'text' || clip.type === 'shape' || clip.type === 'freehand') continue

      // 从 src 中解析 ep（代理文件命名: 都挺好_27_540p.mp4）
      let ep = null
      const srcMatch = clip.src?.match(/_(\d+)_540p/)
      if (srcMatch) ep = parseInt(srcMatch[1])

      const sourceStartSec = framesToSec(clip.sourceStartFrame || 0, fps)
      const sourceEndSec = sourceStartSec + framesToSec(clip.sourceDurationFrames || 1, fps)

      if (ep) {
        clips.push({
          ep,
          start: sourceStartSec,
          end: sourceEndSec,
          outputName: `${clip.name?.replace(/[^a-zA-Z0-9一-鿿]/g, '_') || 'clip'}.mp4`,
          trackName: track.name,
          trackKind: track.kind,
          startFrame: clip.startFrame,
          durationFrames: clip.durationFrames,
          clipId: clip.id,
        })
      }
    }
  }

  // 按时间轴位置排序
  clips.sort((a, b) => a.startFrame - b.startFrame)
  return clips
}

/**
 * 调用后端提取 1080p 片段
 */
export async function requestVibeExport(taskId, clips) {
  const resp = await fetch(`/export/extract_clips?task=${taskId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task: taskId, clips }),
  })
  return await resp.json()
}

/**
 * 从 Vibe model 的 Elah project 生成剪映草稿
 * 使用提取后的 1080p clip 路径
 */
export function toCapCutDraftFromExtracted(elahProject, extractedClips, projectName = 'vibecap-export') {
  const allTracks = []
  const allMaterials = {}
  let materialSeq = 0

  // 构建 clipId → extractedUrl 的映射
  const extractedMap = {}
  for (const ec of extractedClips) {
    if (ec.clipId) extractedMap[ec.clipId] = ec.url
  }

  for (const track of elahProject.tracks) {
    const trackClips = elahProject.clips[track.id] || []
    if (trackClips.length === 0) continue

    const segments = trackClips.map(clip => {
      const materialId = `material_${++materialSeq}`
      const exportedPath = extractedMap[clip.id] || clip.src
      const cleanPath = exportedPath.replace(/^\/export_clips\//, '').replace(/^\/clips\//, '').replace(/^\//, '')

      allMaterials[materialId] = {
        id: materialId,
        path: cleanPath,
        type: clip.type === 'audio' ? 'audio' : 'video',
        duration: framesToSec(clip.durationFrames, FPS),
      }

      return {
        id: clip.id,
        material_id: materialId,
        target_timerange: {
          start: framesToMicrosec(clip.startFrame, FPS),
          duration: framesToMicrosec(clip.durationFrames, FPS),
        },
        source_timerange: {
          start: 0,
          duration: framesToMicrosec(clip.durationFrames, FPS),
        },
        speed: 1.0,
        volume: clip.volume ?? 1,
        clip: {
          transform: clip.transform || { x: 0, y: 0, scale: 1, rotation: 0, anchor: { x: 0, y: 0 } },
          opacity: clip.opacity ?? 1,
        },
      }
    })

    allTracks.push({
      id: track.id,
      type: track.kind === 'audio' ? 'audio' : 'video',
      name: track.name,
      is_muted: track.muted,
      segments,
    })
  }

  const totalFrames = Object.values(elahProject.clips || {}).flat().reduce(
    (max, c) => Math.max(max, c.startFrame + c.durationFrames), 0
  )

  return {
    draft_name: projectName,
    draft_id: `vibe_${Date.now()}`,
    draft_version: 1,
    draft_root_path: '',
    draft_fps: FPS,
    draft_resolution: { width: 1920, height: 1080 },
    draft_total_duration: framesToMicrosec(totalFrames, FPS),
    draft_materials: Object.values(allMaterials),
    draft_tracks: allTracks,
    draft_cover: '',
    created_at: Date.now(),
    updated_at: Date.now(),
  }
}
