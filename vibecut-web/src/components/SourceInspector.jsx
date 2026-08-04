/**
 * 源检视器 — PR 风格时间轴
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { proxyUrlForEpisode, proxyInfoForEpisode } from '../lib/proxyEngine'

const FPS = 25
const COLORS = ['#22c55e', '#3b82f6', '#f59e0b', '#a855f7', '#ef4444']

function tc(s) {
  if (!s && s !== 0) return '—'
  const m = Math.floor(s / 60), h = Math.floor(m / 60)
  const mm = m % 60, ss = Math.floor(s % 60)
  return h > 0 ? `${h}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}` : `${mm}:${String(ss).padStart(2, '0')}`
}

export default function SourceInspector({ proxyManifest, onAddToProgram, timelineFrame }) {
  const videoRef = useRef(null)
  const barRef = useRef(null)
  const tlFrameRef = useRef(timelineFrame)
  tlFrameRef.current = timelineFrame
  const [ep, setEp] = useState(null)
  const [dur, setDur] = useState(0)
  const [markers, setMarkers] = useState([])
  const [pos, setPos] = useState(0)
  const [selIn, setSelIn] = useState(null)
  const [selOut, setSelOut] = useState(null)
  const [scrubbing, setScrubbing] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState(0)

  const [loading, setLoading] = useState(false)

  useEffect(() => {
    window.__sourceLoadEpisode = (e, startTime = 0, endTime = 0) => {
      let st = startTime
      if (!startTime && tlFrameRef.current > 0) st = tlFrameRef.current / FPS
      setEp(e); setDur(0); setMarkers([]); setPos(0)
      setSelIn(endTime > st ? st : null)
      setSelOut(endTime > st ? endTime : null)
      setZoom(1)
      const url = proxyUrlForEpisode(e, proxyManifest)
      setOffset(url ? Math.max(0, st - 30) : 0)  // 非代理视频不从大偏移开始
      window.__sourceIO = endTime > st ? { in: st, out: endTime } : {}
      if (!videoRef.current) return
      const vid = videoRef.current
      if (url) {
        setLoading(true)
        const info = proxyInfoForEpisode(e, proxyManifest)
        if (info) setDur(info.duration_sec)
        // 强制重载（同源切换时浏览器不触发 loadeddata）
        vid.src = ''
        requestAnimationFrame(() => {
          vid.src = url
          vid.currentTime = st
          const onReady = () => { setLoading(false); vid.removeEventListener('loadeddata', onReady) }
          vid.addEventListener('loadeddata', onReady)
        })
      } else {
        fetch(`/preview_video?ep=${e}&t=${st}&task=Task7029`).then(r => r.json()).then(d => {
          if (d?.url && videoRef.current) { videoRef.current.src = d.url; setDur(d.end ? d.end - d.start : 60); setLoading(false) }
        }).catch(() => { setLoading(false) })
      }
    }
    window.__sourceSetMarkers = (results) => {
      setMarkers(results.map((r, i) => ({
        id: `m${Date.now()}-${i}`, ep: r.ep,
        startSec: r.sourceStartSec ?? r.start ?? 0, endSec: r.sourceEndSec ?? r.end ?? (r.start ?? 0) + 10,
        color: COLORS[i % COLORS.length], label: (r.description || r.asr || '').substring(0, 16),
      })))
    }
    return () => { delete window.__sourceLoadEpisode; delete window.__sourceSetMarkers }
  }, [proxyManifest])

  useEffect(() => {
    const v = videoRef.current; if (!v) return
    const t = () => {
      if (scrubbing) return
      const ct = v.currentTime
      setPos(ct)
      // 自动跟随：播放头超出可视范围 80% 时平移
      const r = dur / zoom  // 可视范围
      if (ct > offset + r * 0.8) setOffset(Math.max(0, Math.min(dur - r, ct - r * 0.3)))
      if (ct < offset + r * 0.1) setOffset(Math.max(0, ct - r * 0.3))
    }
    const id = setInterval(t, 100); return () => clearInterval(id)
  }, [scrubbing, dur, zoom, offset])

  useEffect(() => {
    const k = (e) => {
      if (!videoRef.current || !ep) return
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
      const t = videoRef.current.currentTime
      if (e.key === 'i' || e.key === 'I') { e.preventDefault(); setSelIn(t); window.__sourceIO = { in: t, out: selOut } }
      if (e.key === 'o' || e.key === 'O') { e.preventDefault(); setSelOut(t); window.__sourceIO = { in: selIn, out: t } }
    }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [ep, selIn, selOut])

  // Row1 scrub
  const x2t = useCallback((x) => {
    const r = barRef.current?.getBoundingClientRect(); if (!r || !dur) return 0
    return Math.max(0, Math.min(dur, ((x - r.left) / r.width) * dur / zoom + offset))
  }, [dur, zoom, offset])
  const scrub = useCallback((e) => {
    if (e.target.closest('[data-marker]')) return
    const v = videoRef.current; if (!v) return
    v.currentTime = x2t(e.clientX); setScrubbing(true)
    const m = (ev) => { v.currentTime = x2t(ev.clientX) }
    const u = () => { setScrubbing(false); document.removeEventListener('mousemove', m); document.removeEventListener('mouseup', u) }
    document.addEventListener('mousemove', m); document.addEventListener('mouseup', u)
  }, [x2t])

  const add = () => {
    const io = window.__sourceIO; const s = io?.in ?? 0; const o = io?.out ?? s + 10
    if (ep && o > s) onAddToProgram(ep, Math.round(s * FPS), Math.round(o * FPS), 'main')
  }
  const addSupp = () => {
    const io = window.__sourceIO; const s = io?.in ?? 0; const o = io?.out ?? s + 10
    if (ep && o > s) onAddToProgram(ep, Math.round(s * FPS), Math.round(o * FPS), 'supp')
  }

  const viewStart = offset
  const viewEnd = offset + dur / zoom
  const viewLen = dur / zoom

  // 缩放滚动条计算
  const zoomBarRef = useRef(null)
  const scrollStart = (e, what) => {
    e.preventDefault(); e.stopPropagation()
    const w = zoomBarRef.current.getBoundingClientRect().width
    const sx = e.clientX
    const startOff = offset; const startZoom = zoom; const startCenter = offset + dur/zoom/2
    const mv = (ev) => {
      const dx = (ev.clientX - sx) / w * dur
      if (what === 'left' || what === 'right') {
        // 对称缩放：两端向中心同步移动（捏合效果）
        const newLen = dur / startZoom + (what === 'left' ? -dx * 2 : dx * 2)
        const z = Math.max(1, Math.min(20, dur / Math.max(1, newLen)))
        setZoom(z)
        setOffset(Math.max(0, Math.min(dur - dur/z, startCenter - dur/z/2)))
      } else {
        // 平移
        setOffset(Math.max(0, Math.min(dur - dur/zoom, startOff + dx)))
      }
    }
    const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up) }
    document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up)
  }

  return (
    <div style={{ display:'flex', flexDirection:'column', flex:1, minHeight:0, borderTop:'1px solid #232938' }}>
      {/* 预览 */}
      <div style={{ flex:2, minHeight:60, position:'relative', background:'#000', borderBottom:'1px solid #232938', cursor:'pointer' }}
        onClick={() => { const v=videoRef.current; if(v) v.paused ? v.play().catch(()=>{}) : v.pause() }}>
        <video id="source-video" ref={videoRef} style={{ width:'100%', height:'100%', objectFit:'contain', pointerEvents:'none' }} />
        {loading && (
          <div style={{ position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center', background:'rgba(0,0,0,0.6)', zIndex:10 }}>
            <div style={{ display:'flex', alignItems:'center', gap:6, color:'#9ca3af', fontSize:11 }}>
              <div style={{ width:16, height:16, border:'2px solid #6b7280', borderTopColor:'#22c55e', borderRadius:'50%', animation:'spin 0.6s linear infinite' }} />
              加载中...
            </div>
          </div>
        )}
      </div>

      <div style={{ flexShrink:0, display:'flex', flexDirection:'column', padding:'2px 6px', gap:2, height:86 }}>
        {/* Row1: 35px 刻度+标记 */}
        <div style={{ height:35, flexShrink:0, position:'relative' }}>
          <div style={{ position:'absolute', top:0, left:0, right:0, height:12, display:'flex', justifyContent:'space-between', alignItems:'flex-end', pointerEvents:'none' }}>
            {Array.from({length:5}).map((_,i) => {
              const ts = viewStart + (viewEnd-viewStart)*(i/4)
              return <span key={i} style={{ fontSize:9, color:'rgba(255,255,255,0.4)', fontFamily:'monospace', lineHeight:1, fontWeight:500 }}>{tc(ts)}</span>
            })}
          </div>
          <div ref={barRef} onMouseDown={scrub}
            style={{ position:'absolute', top:12, left:0, right:0, bottom:0, borderRadius:2, background:'rgba(255,255,255,0.05)', cursor:'crosshair' }}>
            {selIn != null && selOut != null && selOut > selIn && (
              <div style={{ position:'absolute', top:0, bottom:0, left:`${((selIn-viewStart)/viewLen*100)}%`, width:`${((selOut-selIn)/viewLen*100)}%`, background:'rgba(34,197,94,0.15)', borderLeft:'2px solid #22c55e', borderRight:'2px solid #22c55e' }} />
            )}
            {selIn != null && <div style={{ position:'absolute', top:0, bottom:0, width:2, background:'#22c55e', zIndex:6, left:`${((selIn-viewStart)/viewLen*100)}%` }} />}
            {selOut != null && <div style={{ position:'absolute', top:0, bottom:0, width:2, background:'#ef4444', zIndex:6, left:`${((selOut-viewStart)/viewLen*100)}%` }} />}
            {markers.map(m => { const l=((m.startSec-viewStart)/viewLen*100); const w=Math.max(1,((m.endSec-m.startSec)/viewLen*100))
              return <div key={m.id} data-marker onClick={() => { const v=videoRef.current; if(v){v.currentTime=m.startSec;v.play().catch(()=>{})} }}
                style={{ position:'absolute', top:2, bottom:2, borderRadius:2, left:`${l}%`, width:`${w}%`, background:`${m.color}44`, borderLeft:`1px solid ${m.color}`, cursor:'pointer' }}
                title={`${Math.floor(m.startSec)}s-${Math.floor(m.endSec)}s`} />
            })}
            {ep && dur > 0 && <div style={{ position:'absolute', top:0, bottom:0, width:2, background:'#fbbf24', zIndex:10, pointerEvents:'none', left:`${((pos-viewStart)/viewLen*100)}%`, transition: scrubbing ? 'none' : 'left 0.05s linear', boxShadow:'0 0 4px rgba(251,191,36,0.6)' }} />}
          </div>
        </div>

        {/* Row2: 12px 缩放/滚动合一 (PR 风格) */}
        <div ref={zoomBarRef} style={{ height:12, flexShrink:0, position:'relative', background:'rgba(255,255,255,0.06)', borderRadius:2 }}>
          {dur > 0 && (
            <div style={{ position:'absolute', top:2, bottom:2, borderRadius:1,
              left:`${(viewStart/dur)*100}%`, width:`${(1/zoom)*100}%`,
              background:'rgba(255,255,255,0.12)', cursor:'grab' }}
              onMouseDown={(e) => scrollStart(e, 'center')}>
              <div style={{ position:'absolute', left:0, top:-2, bottom:-2, width:6, cursor:'col-resize', background:'rgba(255,255,255,0.4)', borderRadius:2 }}
                onMouseDown={(e) => scrollStart(e, 'left')} />
              <div style={{ position:'absolute', right:0, top:-2, bottom:-2, width:6, cursor:'col-resize', background:'rgba(255,255,255,0.4)', borderRadius:2 }}
                onMouseDown={(e) => scrollStart(e, 'right')} />
            </div>
          )}
        </div>

        {/* Row3: 25px 操作区 */}
        <div style={{ display:'flex', alignItems:'center', gap:5, fontSize:10, color:'#9ca3af', height:25, flexShrink:0 }}>
          <button onClick={() => { const v=videoRef.current; if(v){setSelIn(v.currentTime);window.__sourceIO={...window.__sourceIO,in:v.currentTime}} }}
            style={{ minWidth:28, height:22, fontSize:13, borderRadius:3, background:'rgba(34,197,94,0.15)', color:'#22c55e', border:'none', cursor:'pointer', fontWeight:600, display:'flex', alignItems:'center', justifyContent:'center' }} title="入点 (I)">{'{'}</button>
          <button onClick={() => { const v=videoRef.current; if(v){setSelOut(v.currentTime);window.__sourceIO={...window.__sourceIO,out:v.currentTime}} }}
            style={{ minWidth:28, height:22, fontSize:13, borderRadius:3, background:'rgba(239,68,68,0.15)', color:'#ef4444', border:'none', cursor:'pointer', fontWeight:600, display:'flex', alignItems:'center', justifyContent:'center' }} title="出点 (O)">{'}'}</button>
          <span style={{ color:'#374151', margin:'0 2px', fontSize:14, lineHeight:'22px' }}>|</span>
          <button onClick={() => { const v=videoRef.current; if(v) v.paused?v.play().catch(()=>{}):v.pause() }}
            style={{ minWidth:28, height:22, fontSize:13, borderRadius:3, background:'rgba(255,255,255,0.12)', color:'#e5e7eb', border:'none', cursor:'pointer', display:'flex', alignItems:'center', justifyContent:'center' }} title="播放/暂停">
            {videoRef.current?.paused ? '▶' : '⏸'}
          </button>
          <button onClick={() => { const v=videoRef.current; if(v) v.muted=!v.muted }}
            style={{ minWidth:28, height:22, fontSize:13, borderRadius:3, background:'rgba(255,255,255,0.06)', color:videoRef.current?.muted?'#ef4444':'#9ca3af', border:'none', cursor:'pointer', display:'flex', alignItems:'center', justifyContent:'center' }} title="静音">
            🔊
          </button>
          <span style={{ color:'#374151', margin:'0 2px', fontSize:14, lineHeight:'22px' }}>|</span>
          <button onClick={add} title="插入片段到主镜头轨道"
            style={{ padding:'0 10px', height:22, fontSize:10, borderRadius:3, background:'rgba(34,197,94,0.18)', color:'#22c55e', border:'none', cursor:'pointer', fontWeight:500 }}>
            ↓ 插入clip
          </button>
          <button onClick={addSupp} title="插入片段到补充镜头轨道"
            style={{ padding:'0 10px', height:22, fontSize:10, borderRadius:3, background:'rgba(168,85,247,0.18)', color:'#a855f7', border:'none', cursor:'pointer', fontWeight:500 }}>
            ↓ 补
          </button>
          <div style={{ flex:1 }} />
          <span style={{ fontFamily:'monospace', color:'#e5e7eb', fontSize:11 }}>{tc(pos)}{dur>0?` / ${tc(dur)}`:''}</span>
          {selIn!=null&&selOut!=null&&selOut>selIn&&<span style={{ fontSize:9, color:'#4ade80' }}>{(selOut-selIn).toFixed(1)}s</span>}
          <span style={{ color:'#6b7280', fontSize:9 }}>{ep?`EP${ep}`:''}</span>
        </div>
        <div style={{ height:4, flexShrink:0 }} />
      </div>
    </div>
  )
}
