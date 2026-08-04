/**
 * 视频/音频 clip 联动 Hook
 * 从 Timeline.jsx 提取，供 VibeEdit 复用
 *
 * 当视频 clip 被移动/裁剪/删除时，关联的音频 clip 自动同步。
 * 使用 engine.batch() 保证双方操作为同一个 undo 步。
 */
import { useEffect, useRef } from 'react'
import { useTimelineEngine } from '@elah/editor'
import { getLinkedPairs, linkClipPair, unlinkClipPair } from '../lib/timelineBuilder'

const SYNC_KEYS = ['startFrame', 'durationFrames', 'sourceStartFrame', 'sourceDurationFrames']

function partnerOf(engine, clipId) {
  const pairs = getLinkedPairs()
  const pid = pairs.get(clipId)
  if (!pid) return null
  const info = engine.findClip(pid)
  if (!info) {
    unlinkClipPair(clipId)
    return null
  }
  return { id: pid, trackId: info.trackId }
}

/**
 * Monkey-patch engine 方法，实现视频/音频联动
 * 必须在 EditorProvider 内部使用（通过 useTimelineEngine）
 */
export function installLinkedClips(engine) {
  if (!engine || engine.__linkedClipsInstalled) return
  engine.__linkedClipsInstalled = true

  const origUpdateClip = engine.updateClip.bind(engine)
  const origMoveClip = engine.moveClip.bind(engine)
  const origTrimClip = engine.trimClip.bind(engine)
  const origRemoveClip = engine.removeClip.bind(engine)
  const origSplitClip = engine.splitClip.bind(engine)
  const origPreviewClip = engine.previewClip.bind(engine)

  engine.moveClip = function (clipId, fromTrackId, toTrackId, startFrame) {
    const p = partnerOf(engine, clipId)
    if (!p) return origMoveClip(clipId, fromTrackId, toTrackId, startFrame)
    engine.batch(() => {
      origMoveClip(clipId, fromTrackId, toTrackId, startFrame)
      origMoveClip(p.id, p.trackId, p.trackId, startFrame)
    })
  }

  engine.trimClip = function (clipId, trackId, startFrame, durationFrames) {
    const p = partnerOf(engine, clipId)
    if (!p) return origTrimClip(clipId, trackId, startFrame, durationFrames)
    engine.batch(() => {
      origTrimClip(clipId, trackId, startFrame, durationFrames)
      origTrimClip(p.id, p.trackId, startFrame, durationFrames)
    })
  }

  engine.previewClip = function (clipId, trackId, updates) {
    origPreviewClip(clipId, trackId, updates)
    const p = partnerOf(engine, clipId)
    if (p) {
      const sync = {}
      for (const k of SYNC_KEYS) {
        if (k in updates) sync[k] = updates[k]
      }
      if (Object.keys(sync).length > 0) {
        origPreviewClip(p.id, p.trackId, sync)
      }
    }
  }

  engine.updateClip = function (clipId, trackId, updates) {
    const p = partnerOf(engine, clipId)
    if (!p) return origUpdateClip(clipId, trackId, updates)
    const sync = {}
    for (const k of SYNC_KEYS) {
      if (k in updates) sync[k] = updates[k]
    }
    if (Object.keys(sync).length === 0) {
      return origUpdateClip(clipId, trackId, updates)
    }
    engine.batch(() => {
      origUpdateClip(clipId, trackId, updates)
      origUpdateClip(p.id, p.trackId, sync)
    })
  }

  engine.removeClip = function (clipId, trackId) {
    const p = partnerOf(engine, clipId)
    if (!p) return origRemoveClip(clipId, trackId)
    engine.batch(() => {
      origRemoveClip(clipId, trackId)
      origRemoveClip(p.id, p.trackId)
    })
    unlinkClipPair(clipId)
  }

  engine.splitClip = function (clipId, trackId, atFrame) {
    const p = partnerOf(engine, clipId)
    if (!p) return origSplitClip(clipId, trackId, atFrame)
    let vR = null, aR = null
    engine.batch(() => {
      vR = origSplitClip(clipId, trackId, atFrame)
      aR = origSplitClip(p.id, p.trackId, atFrame)
    })
    if (vR && aR) {
      unlinkClipPair(clipId)
      unlinkClipPair(p.id)
      linkClipPair(vR[0], aR[0])
      linkClipPair(vR[1], aR[1])
    }
    return vR
  }
}

/**
 * React 组件：在挂载时安装联动逻辑
 */
export default function ClipLinker() {
  const engine = useTimelineEngine()
  const installed = useRef(false)

  useEffect(() => {
    if (installed.current) return
    installed.current = true
    installLinkedClips(engine)
  }, [engine])

  return null
}
