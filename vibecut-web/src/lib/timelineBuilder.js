/**
 * 从 proxy picks 构建 Elah Project
 * 替代 Timeline.jsx 中的 buildProjectFromPicks，使用代理视频 + 时间引用
 *
 * v0.11: proxy 命名由 manifest 统一管理, 不再硬编码文件名
 */
import { generateId, secondsToFrames } from '@elah/editor'
import { resolveClipSource, proxyUrlForEpisode } from './proxyEngine'

const FPS = 25
const STAGE = { width: 1920, height: 1080 }

function thumbnailUrl(filePath) {
  if (!filePath) return undefined
  return undefined
}

/** 从 manifest 查找 proxy 文件名 (v0.11: 替代硬编码 proxyFileName) */
function proxyFileForEp(ep, manifest) {
  if (!manifest?.proxies) return null
  const p = manifest.proxies.find(x => x.ep === ep)
  return p?.file || null
}

// 视频/音频 clipId 配对（联动编辑）
const linkedPairs = new Map()

export function linkClipPair(videoClipId, audioClipId) {
  linkedPairs.set(videoClipId, audioClipId)
  linkedPairs.set(audioClipId, videoClipId)
}

export function unlinkClipPair(clipId) {
  const partner = linkedPairs.get(clipId)
  if (partner) {
    linkedPairs.delete(partner)
    linkedPairs.delete(clipId)
  }
}

export function getLinkedPairs() {
  return linkedPairs
}

export function clearLinkedPairs() {
  linkedPairs.clear()
}

/**
 * 从 picks 构建 Elah Project
 * picks = { "sid_seq": { main: [ClipRef], supp: [ClipRef] } }
 * ClipRef = { ep, sourceStartSec, sourceEndSec }
 *
 * clipRegistry 记录 clipId → {ep, sourceStartSec, sourceEndSec} 供导出阶段使用
 */
export function buildProjectFromProxyPicks(picks, proxyManifest, extraTracks = [], options = {}) {
  // v0.11: options.mode = 'drama' (4轨) | 'interview' (2轨)
  const mode = options.mode || 'drama'
  const isInterview = mode === 'interview'

  const tracks = []
  const clips = {}
  const mediaList = []
  const clipRegistry = {}

  const mainVideoId = generateId()
  const mainAudioId = generateId()
  const suppId = isInterview ? null : generateId()
  const narrId = isInterview ? null : generateId()

  const mainVideoClips = []
  const mainAudioClips = []
  const suppClips = []
  const narrClips = []

  // v0.13: narrDurations 支持外部注入（Drama 自动建轨）
  const NARR_DURATIONS = options.narrDurations || (isInterview ? {} : {})
  // v1.4: segDurations 权威段总时长（含停顿），覆盖段偏移计算（音频为骨架）
  const SEG_DURATIONS = options.segDurations || null
  // v1.4: taskName 用于旁白音频 URL 带 task 参数（后端按 task 定位 work_dir）
  const TASK_Q = options.taskName ? `?task=${encodeURIComponent(options.taskName)}` : ''

  const entries = Object.entries(picks).sort((a, b) => {
    const [sa] = a[0].split('_').map(Number)
    const [sb] = b[0].split('_').map(Number)
    return sa - sb
  })

  // 第 1 遍: 统计每段高亮 + 补充时长
  const segHighlight = {}
  const segSupp = {}
  for (const [key, p] of entries) {
    const [sidStr] = key.split('_')
    const sid = parseInt(sidStr)
    if (!segHighlight[sid]) segHighlight[sid] = 0
    if (!segSupp[sid]) segSupp[sid] = 0
    if (p.main?.length) {
      p.main.forEach(m => {
        const dur = m.sourceEndSec !== undefined
          ? (m.sourceEndSec - m.sourceStartSec)
          : (m.duration || (m.end - m.start) || 3)
        segHighlight[sid] += dur
      })
    }
    if (p.supp?.length) {
      p.supp.forEach(s => {
        const dur = s.sourceEndSec !== undefined
          ? (s.sourceEndSec - s.sourceStartSec)
          : (s.duration || (s.end - s.start) || 2)
        segSupp[sid] += dur
      })
    }
  }

  // 计算每段偏移
  const segOffsets = {}
  let cursor = 0
  const maxSid = Math.max(...Object.keys(picks).map(k => parseInt(k.split('_')[0])), 8)
  for (let sid = 0; sid <= maxSid; sid++) {
    segOffsets[sid] = cursor
    const hl = segHighlight[sid] || 0
    const supp = segSupp[sid] || 0
    const narr = NARR_DURATIONS[sid] || 0
    // 权威段时长优先（音频为骨架）；否则退回 hl + max(supp, narr)
    const segDur = SEG_DURATIONS ? (SEG_DURATIONS[sid] ?? 0) : 0
    cursor += segDur > 0 ? segDur : (hl + Math.max(supp, narr))
  }

  // 第 2 遍: 放置 clip
  const segCursors = {}
  for (const [key, p] of entries) {
    const [sidStr, seqStr] = key.split('_')
    const sid = parseInt(sidStr)
    const segStart = secondsToFrames(segOffsets[sid] || 0, FPS)
    const hlDur = secondsToFrames(segHighlight[sid] || 0, FPS)
    const narrStart = segStart + hlDur

    if (!segCursors[sid]) {
      segCursors[sid] = { audioFrames: segStart, suppFrames: narrStart }
    }
    const cur = segCursors[sid]

    // ── 主镜头：使用代理视频 ──
    if (p.main?.length) {
      p.main.forEach((m, mi) => {
        const resolved = resolveClipSource(m)
        const durFrames = resolved.sourceDurationFrames
        const proxyFile = proxyFileForEp(m.ep, proxyManifest)
        const src = proxyFile ? `/proxies/${proxyFile}` : (m.src || '')

        const vClipId = generateId(); const vAssetId = generateId()
        mediaList.push({
          assetId: vAssetId, src, name: `S${sid} EP${m.ep} 主`,
          kind: 'video', durationSec: resolved.durationSec, thumbnailUrl: thumbnailUrl()
        })
        mainVideoClips.push({
          id: vClipId, trackId: mainVideoId, type: 'video', assetId: vAssetId,
          name: `S${sid} EP${m.ep}`, src,
          startFrame: cur.audioFrames, durationFrames: durFrames,
          sourceStartFrame: resolved.sourceStartFrame,
          sourceDurationFrames: resolved.sourceDurationFrames,
          volume: 1, opacity: 1, locked: false, disabled: false,
        })
        clipRegistry[vClipId] = { ep: m.ep, sourceStartSec: resolved.sourceStartSec, sourceEndSec: resolved.sourceEndSec }

        const aClipId = generateId(); const aAssetId = generateId()
        mediaList.push({
          assetId: aAssetId, src, name: `S${sid} EP${m.ep} 原声`,
          kind: 'audio', durationSec: resolved.durationSec,
        })
        mainAudioClips.push({
          id: aClipId, trackId: mainAudioId, type: 'audio', assetId: aAssetId,
          name: `S${sid} EP${m.ep}`, src,
          startFrame: cur.audioFrames, durationFrames: durFrames,
          sourceStartFrame: resolved.sourceStartFrame,
          sourceDurationFrames: resolved.sourceDurationFrames,
          volume: 1, locked: false, disabled: false,
        })
        linkClipPair(vClipId, aClipId)

        cur.audioFrames += durFrames
      })
    }

    // ── 补充轨 ──
    if (p.supp?.length) {
      p.supp.forEach((s, si) => {
        const resolved = resolveClipSource(s)
        const durFrames = resolved.sourceDurationFrames
        const proxyFile = proxyFileForEp(s.ep, proxyManifest)
        const src = proxyFile ? `/proxies/${proxyFile}` : (s.src || '')

        const clipId = generateId(); const assetId = generateId()
        mediaList.push({
          assetId, src, name: `S${sid} EP${s.ep} 补`,
          kind: 'video', durationSec: resolved.durationSec, thumbnailUrl: thumbnailUrl()
        })
        suppClips.push({
          id: clipId, trackId: suppId, type: 'video', assetId,
          name: `S${sid} EP${s.ep}`, src,
          startFrame: cur.suppFrames, durationFrames: durFrames,
          sourceStartFrame: resolved.sourceStartFrame,
          sourceDurationFrames: resolved.sourceDurationFrames,
          volume: 0, opacity: 1, locked: false, disabled: false,
        })
        clipRegistry[clipId] = { ep: s.ep, sourceStartSec: resolved.sourceStartSec, sourceEndSec: resolved.sourceEndSec }

        cur.suppFrames += durFrames
      })
    }
  }

  // ── 旁白音轨 ──
  const maxNarrSid = Math.max(...Object.keys(picks).map(k => parseInt(k.split('_')[0])), 8)
  for (let sid = 0; sid <= maxNarrSid; sid++) {
    const dur = NARR_DURATIONS[sid]
    if (!dur) continue
    // 旁白起点 = 段起点（解说画面在 supp 轨与旁白并行，不是 main 轨之后）
    const narrStart = secondsToFrames(segOffsets[sid] || 0, FPS)
    const src = `/tts_segments/narr_${String(sid).padStart(3, '0')}.wav${TASK_Q}`
    const durFrames = secondsToFrames(dur, FPS)
    const clipId = generateId(); const assetId = generateId()
    mediaList.push({ assetId, src, name: `解说 seg_${sid}`, kind: 'audio', durationSec: dur })
    narrClips.push({
      id: clipId, trackId: narrId, type: 'audio', assetId,
      name: `解说 seg_${sid}`, src,
      startFrame: narrStart, durationFrames: durFrames,
      sourceStartFrame: 0, sourceDurationFrames: durFrames,
      volume: 1, locked: false, disabled: false,
    })
  }

  // ── 组装轨道 (v0.11: interview模式仅主镜头+音频) ──
  if (!isInterview && suppClips.length > 0) {
    tracks.push({ id: suppId, name: '补充镜头', kind: 'video', order: 0, height: 44, locked: false, disabled: false, muted: true, solo: false })
    clips[suppId] = suppClips
  }
  if (mainVideoClips.length > 0) {
    tracks.push({ id: mainVideoId, name: '原声主镜头', kind: 'video', order: 2, height: 52, locked: false, disabled: false, muted: false, solo: false, volume: 1 })
    clips[mainVideoId] = mainVideoClips
  }
  if (mainAudioClips.length > 0) {
    tracks.push({ id: mainAudioId, name: '原声主镜头 音频', kind: 'audio', order: 0, height: 44, locked: false, disabled: false, muted: false, solo: false })
    clips[mainAudioId] = mainAudioClips
  }
  if (!isInterview && narrClips.length > 0) {
    tracks.push({ id: narrId, name: '旁白 TTS', kind: 'audio', order: 1, height: 44, locked: false, disabled: false, muted: false, solo: false })
    clips[narrId] = narrClips
  }

  // 自定义额外轨道
  for (const et of extraTracks) {
    tracks.push({ id: et.id, name: et.name, kind: et.kind || 'audio', order: tracks.length, height: 44, locked: false, disabled: false, muted: false, solo: false })
    clips[et.id] = []
  }

  const totalFrames = cursor * FPS
  return {
    project: {
      id: 'vibecut-timeline-v2',
      fps: FPS,
      stage: STAGE,
      tracks,
      clips,
      transitions: [],
      version: 1,
      masterVolume: 1,
    },
    mediaList,
    clipRegistry,
    trackIds: { mainVideo: mainVideoId, mainAudio: mainAudioId, supp: suppId, narr: narrId },
  }
}

/**
 * v0.11: proxy 文件名统一由 manifest 管理, 客户端不再硬编码
 */
