import { useState, useRef, useEffect } from 'react'
import { Send, Sparkles } from 'lucide-react'
import { cn } from '../lib/utils'

const CHARS = ["苏大强", "苏明哲", "苏明成", "苏明玉", "明玉", "朱丽", "吴非", "石天冬", "蒙总", "老蒙", "蒙太", "沈浩", "柳青", "赵美兰", "小咪"]

function highlightText(text) {
  if (!text) return ''
  let s = text
  CHARS.forEach(c => { s = s.replaceAll(c, `<span class="char-hl">${c}</span>`) })
  return s
}

function SafeHtml({ text, className }) {
  return <span className={className} dangerouslySetInnerHTML={{ __html: highlightText(text) }} />
}

// 结果卡片
function ResultCard({ result, selected, onClick }) {
  const hasAsr = result.asr && result.asr.length > 5
  return (
    <button
      onClick={() => onClick(result)}
      className={cn(
        'w-full text-left p-3 rounded-xl border transition-all cursor-pointer mb-1.5',
        selected
          ? 'border-purple/40 bg-purple/5 shadow-sm'
          : 'border-border/60 bg-white/5 hover:border-purple/20 hover:bg-purple/[0.03]'
      )}
    >
      <div className="flex items-center gap-2 text-[10px] text-muted-foreground mb-1">
        <span className="px-1.5 py-0.5 rounded-md bg-purple/10 text-purple font-medium">EP{result.ep}</span>
        <span>{result.start?.toFixed(0)}s – {result.end?.toFixed(0)}s</span>
        {hasAsr && <span className="text-[10px] text-warning/70" title="ASR台词匹配">💬 台词</span>}
        <span className="ml-auto text-[10px] text-purple/70 font-medium">{result.score?.toFixed(1)} 分</span>
      </div>
      <p className={cn(
        'text-xs leading-relaxed line-clamp-2',
        hasAsr ? 'text-warning/90 italic' : 'text-foreground/80'
      )}>
        <SafeHtml text={(hasAsr ? result.asr : result.description)?.substring(0, 150)} />
      </p>
    </button>
  )
}

// 打字中动画
function TypingDots() {
  return (
    <div className="flex items-center gap-1 px-4 py-2 text-muted-foreground">
      <div className="flex gap-0.5">
        <span className="w-1.5 h-1.5 rounded-full bg-purple/40 animate-bounce" style={{ animationDelay: '0ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-purple/40 animate-bounce" style={{ animationDelay: '150ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-purple/40 animate-bounce" style={{ animationDelay: '300ms' }} />
      </div>
      <span className="text-[11px] ml-1">小 V 正在搜索素材...</span>
    </div>
  )
}

export default function ChatPanel({ context, onPreview, onPick, onSearch }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [selectedIdx, setSelectedIdx] = useState(null)
  const [suggestions, setSuggestions] = useState(null)  // AI 分镜推荐
  const [epFilter, setEpFilter] = useState(null)  // 按集筛选
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const prevSid = useRef(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  // 点击句子时：台词 → ASR优先搜索，解说词 → AI分镜推荐
  useEffect(() => {
    const key = `${context.sid}_${context.seq}`
    if (context.sid == null || !context.narration || key === prevSid.current) return
    prevSid.current = key
    setMessages([])
    setSuggestions(null)
    setSelectedIdx(null)

    if (context.seq === 'D') {
      // ── 台词：拆解 + ASR 匹配原剧对白 ──
      setLoading(true)
      fetch('/dialogue_match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dialogue: context.narration })
      }).then(r => r.json()).then(d => {
        const lines = d.lines || []
        if (lines.length > 0) {
          const suggestionItems = lines.flatMap(l => {
            const best = l.matches?.[0]
            const confident = l.confident !== false
            return [{
              display: confident && best
                ? `✅「${l.normalized}」→ EP${best.ep} 原台词`
                : `🔍「${l.normalized}」→ 未确认原台词，语义搜索`,
              query: l.normalized,
              confident
            }]
          })
          setMessages([{
            role: 'ai',
            content: '这段台词拆解为以下原剧对白，点击搜索 ~',
            suggestionItems: suggestionItems
          }])
        } else {
          setMessages([{ role: 'ai', content: '没有匹配到原剧台词，换个说法试试？' }])
        }
      }).catch(() => {
        setMessages([{ role: 'ai', content: '台词匹配出错，请重试' }])
      }).finally(() => setLoading(false))
    } else {
      // ── 解说词：AI 分镜推荐 → 自动搜索第一个建议 ──
      fetch(`/storyboard_suggest?task=${context.taskId || ''}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ narration: context.narration })
      }).then(r => r.json()).then(d => {
        const list = (d.suggestions || []).map(s => s.replace(/^镜头\d+[：:]\s*/, ''))
        if (list.length > 0) {
          setSuggestions(list)
          // 自动用第一个建议发起搜索
          const firstQuery = list[0]
          const userMsg = { role: 'user', content: firstQuery }
          const aiPlaceholder = { role: 'ai', content: '小 V 根据分镜方案自动搜索中...', suggestions: list }
          setMessages([userMsg, aiPlaceholder])
          setLoading(true)
          const strategy = context.seq === 'D' ? 'asr_first' : undefined
          const ctx = strategy ? { ...context, strategy } : context
          fetch(`/chat?task=${ctx.taskId || ''}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: [userMsg], context: ctx })
          }).then(r2 => r2.json()).then(data => {
            setMessages([userMsg, {
              role: 'ai',
              content: data.reply || '找到以下匹配素材 ~',
              results: data.results || [],
              suggestions: list,  // 保留建议列表，方便切换
            }])
            setEpFilter(null)
            if (data.results?.length > 0 && onSearch) onSearch(data.results)
          }).catch(() => {
            setMessages([userMsg, { role: 'ai', content: '搜索出错，请重试', suggestions: list }])
          }).finally(() => setLoading(false))
        }
      }).catch(() => {})
    }
  }, [context.sid, context.seq, context.narration])

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return

    // 台词上下文 → ASR 优先策略
    const strategy = context.seq === 'D' ? 'asr_first' : undefined
    const ctx = strategy ? { ...context, strategy } : context

    const userMsg = { role: 'user', content: text }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setInput('')
    setLoading(true)

    try {
      const resp = await fetch(`/chat?task=${ctx.taskId || ''}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: newMessages, context: ctx })
      })
      const data = await resp.json()

      const aiMsg = {
        role: 'ai',
        content: data.reply || '没找到匹配的镜头 ~',
        results: data.results || [],
        action: data.action
      }
      setMessages([...newMessages, aiMsg])
      setEpFilter(null)
      if (data.results?.length > 0 && onSearch) onSearch(data.results)
    } catch (e) {
      setMessages([...newMessages, { role: 'ai', content: '网络出错了，重试一下？' }])
    }
    setLoading(false)
  }

  const hasResults = messages.some(m => m.results?.length > 0)
  const showWelcome = messages.length === 0 && !loading

  return (
    <div className="flex flex-col h-full bg-gradient-to-b from-background to-card/30">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/50 bg-card/50 backdrop-blur">
        <div className="w-7 h-7 rounded-lg bg-purple/15 flex items-center justify-center">
          <Sparkles size={14} className="text-purple" />
        </div>
        <div>
          <p className="text-xs font-semibold text-foreground">小 V</p>
          <p className="text-[10px] text-muted-foreground">AI 剪辑助手</p>
        </div>
        {context.sid != null && (
          <span className="ml-auto text-[10px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
            S{context.sid}-{context.seq}
          </span>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto custom-scrollbar px-4 py-3 space-y-4">
        {/* Welcome */}
        {showWelcome && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-3 py-8">
            <div className="w-16 h-16 rounded-2xl bg-purple/10 flex items-center justify-center">
              <Sparkles size={28} className="text-purple" />
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">你好，我是小 V</p>
              <p className="text-xs text-muted-foreground mt-1">
                {context.sid != null
                  ? '描述你想找的画面，我帮你在原剧中搜索 ~'
                  : '先点击左侧一句解说词，然后告诉我你想找什么样的画面'}
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 justify-center mt-1">
              {['苏大强在老宅翻存折', '蒙总和蒙太办公室争吵', '苏明玉冷漠表情特写'].map(hint => (
                <button key={hint} onClick={() => { setInput(hint); inputRef.current?.focus() }}
                  className="text-[11px] px-2.5 py-1 rounded-full border border-border/60 text-muted-foreground hover:border-purple/30 hover:text-purple transition-colors"
                >{hint}</button>
              ))}
            </div>
          </div>
        )}

        {/* Chat messages */}
        {messages.map((msg, i) => (
          <div key={i} className={cn('flex gap-2.5', msg.role === 'user' ? 'flex-row-reverse' : '')}>
            {/* Avatar */}
            <div className={cn(
              'w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-0.5',
              msg.role === 'user' ? 'bg-primary/15' : 'bg-purple/15'
            )}>
              {msg.role === 'user' ? (
                <span className="text-[10px] font-bold text-primary">你</span>
              ) : (
                <Sparkles size={11} className="text-purple" />
              )}
            </div>

            {/* Bubble */}
            <div className={cn('flex-1 min-w-0', msg.role === 'user' && 'flex flex-col items-end')}>
              {/* Text */}
              {msg.content && (
                <p className={cn(
                  'text-xs leading-relaxed px-3 py-2 rounded-2xl inline-block max-w-[90%]',
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground rounded-tr-sm'
                    : 'bg-card border border-border/50 text-foreground rounded-tl-sm'
                )}>
                  {msg.role === 'user' ? msg.content : <SafeHtml text={msg.content} />}
                </p>
              )}

              {/* 推荐问题（可点击） */}
              {(msg.suggestions?.length > 0 || msg.suggestionItems?.length > 0) && (
                <div className="mt-2 space-y-1.5">
                  {(msg.suggestionItems || msg.suggestions || []).map((s, j) => {
                    const query = typeof s === 'string' ? s : s.query
                    const display = typeof s === 'string' ? s : s.display
                    const isDialogue = msg.suggestionItems?.length > 0
                    return (
                    <button
                      key={j}
                      onClick={async () => {
                        const userMsg = { role: 'user', content: query }
                        const newMsgs = [...messages, userMsg]
                        setMessages(newMsgs)
                        setLoading(true)
                        try {
                          const resp = await fetch('/chat', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ messages: newMsgs, context })
                          })
                          const data = await resp.json()
                          setMessages([...newMsgs, {
                            role: 'ai', content: data.reply || '找到以下素材 ~',
                            results: data.results || []
                          }])
                          setEpFilter(null)
                          if (data.results?.length > 0 && onSearch) onSearch(data.results)
                        } catch (e) {
                          setMessages([...newMsgs, { role: 'ai', content: '网络出错了' }])
                        }
                        setLoading(false)
                      }}
                      className={cn(
                        'w-full text-left px-3 py-2 rounded-xl border transition-all text-xs text-foreground/80 group',
                        isDialogue
                          ? 'border-green/20 bg-green/[0.03] hover:bg-green/[0.06] hover:border-green/40'
                          : 'border-purple/20 bg-purple/[0.03] hover:bg-purple/[0.06] hover:border-purple/40'
                      )}
                    >
                      <span className={cn('mr-2 shrink-0', isDialogue ? 'text-green/70' : 'text-purple/70')}>
                        {isDialogue ? '💬' : '🎬'}
                      </span>
                      <SafeHtml text={display} />
                      <span className="text-[10px] text-muted-foreground/0 group-hover:text-purple/50 transition-colors ml-1 shrink-0">搜索 →</span>
                    </button>
                    )
                  })}
                </div>
              )}

              {/* 搜索结果 */}
              {msg.results?.length > 0 && (
                <div className="mt-2 w-full">
                  {/* 按集筛选 */}
                  {(() => {
                    const eps = [...new Set(msg.results.map(r => r.ep))].sort((a,b) => a-b)
                    return eps.length > 1 ? (
                      <div className="flex gap-1 mb-2 flex-wrap">
                        <button
                          onClick={() => setEpFilter(null)}
                          className={cn(
                            'text-[10px] px-2 py-0.5 rounded-full border transition-colors',
                            epFilter === null ? 'bg-purple/15 border-purple/30 text-purple' : 'border-border text-muted-foreground hover:bg-accent'
                          )}
                        >全部 ({msg.results.length})</button>
                        {eps.map(ep => {
                          const count = msg.results.filter(r => r.ep === ep).length
                          return (
                            <button key={ep}
                              onClick={() => setEpFilter(epFilter === ep ? null : ep)}
                              className={cn(
                                'text-[10px] px-2 py-0.5 rounded-full border transition-colors',
                                epFilter === ep ? 'bg-purple/15 border-purple/30 text-purple' : 'border-border text-muted-foreground hover:bg-accent'
                              )}
                            >EP{ep} ({count})</button>
                          )
                        })}
                      </div>
                    ) : null
                  })()}
                  {/* 结果卡片 */}
                  {msg.results
                    .filter(r => epFilter === null || r.ep === epFilter)
                    .map((r, j) => (
                      <ResultCard
                        key={j}
                        result={r}
                        selected={selectedIdx === j && i === messages.length - 1}
                        onClick={(result) => {
                          setSelectedIdx(j)
                          onPreview?.(result)
                        }}
                      />
                    ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Typing indicator */}
        {loading && <TypingDots />}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-border/50 bg-card/30">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            placeholder={context.sid != null ? '描述你想找的画面...' : '先点击左侧解说词'}
            className="flex-1 bg-background border border-border rounded-xl px-3.5 py-2.5 text-sm outline-none focus:border-purple/40 focus:ring-1 focus:ring-purple/20 transition-all placeholder:text-muted-foreground/50"
            disabled={loading}
          />
          <button onClick={send} disabled={!input.trim() || loading}
            className="w-10 h-10 rounded-xl bg-purple text-white flex items-center justify-center disabled:opacity-30 transition-all hover:bg-purple/90 active:scale-95">
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}
