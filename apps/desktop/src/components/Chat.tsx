import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useAppStore } from '../store/useAppStore'

interface ModelOption {
  providerId: string
  model: string
  label: string
}

export default function Chat() {
  const {
    activeConversationId,
    conversations,
    providers,
    characters,
    messagesByConversation,
    streaming,
    streamText,
    error,
    sendMessage,
    stopGeneration,
    clearError,
    setConversationCharacter,
  } = useAppStore()

  const [input, setInput] = useState('')
  const [selected, setSelected] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  const conversation = conversations.find((c) => c.id === activeConversationId)
  const messages = (activeConversationId && messagesByConversation[activeConversationId]) || []

  const options = useMemo<ModelOption[]>(
    () =>
      providers
        .filter((p) => p.enabled && p.configured)
        .flatMap((p) => p.models.filter((m) => m.enabled).map((m) => ({ providerId: p.id, model: m.model_name, label: `${p.name} · ${m.display_name}` }))),
    [providers],
  )

  useEffect(() => {
    const preferred = options.find((option) => option.model === conversation?.model_id)
    if (preferred) {
      setSelected(`${preferred.providerId}::${preferred.model}`)
      return
    }
    if (!options.some((option) => `${option.providerId}::${option.model}` === selected)) {
      setSelected(options.length > 0 ? `${options[0].providerId}::${options[0].model}` : '')
    }
  }, [conversation?.id, conversation?.model_id, options, selected])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: streaming ? 'smooth' : 'auto' })
  }, [messages.length, streamText, streaming])

  const canSend = !streaming && options.length > 0

  const currentCharacterId = conversation?.character_id ?? null
  const handleCharacterChange = (value: string) => {
    if (!activeConversationId) return
    setConversationCharacter(activeConversationId, value || null)
  }

  const handleSend = () => {
    const text = input.trim()
    if (!text || !canSend) return
    const [providerId, model] = selected ? selected.split('::') : [null, null]
    clearError()
    sendMessage(text, providerId, model)
    setInput('')
  }

  const handleRegenerate = () => {
    const lastUser = [...messages].reverse().find((message) => message.role === 'user')
    if (!lastUser || streaming || !selected) return
    const [providerId, model] = selected.split('::')
    clearError()
    void sendMessage(lastUser.content, providerId, model, true)
  }

  const renderContent = (content: string, role: string) =>
    role === 'assistant' ? (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" /> }}
      >{content}</ReactMarkdown>
    ) : content

  return (
    <section className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">{conversation?.title ?? 'Chat'}</h2>
        <div className="flex items-center gap-2">
          <button type="button" onClick={handleRegenerate} disabled={streaming || !messages.some((message) => message.role === 'user')} className="rounded-lg border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:bg-neutral-800 disabled:opacity-40">Regenerate</button>
          <select
            value={currentCharacterId ?? ''}
            onChange={(e) => handleCharacterChange(e.target.value)}
            disabled={!activeConversationId}
            title={activeConversationId ? '选择角色' : '先打开或新建一个会话'}
            aria-label="选择角色"
            className="rounded-lg border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-300 disabled:opacity-50"
          >
            <option value="">无角色</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className="group max-w-[80%]">
              <div
                className={`markdown whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                m.role === 'user' ? 'bg-neutral-100 text-neutral-900' : 'bg-neutral-800 text-neutral-200'
              }`}
              >
                {renderContent(m.content, m.role)}
              </div>
              <button
                onClick={() => void navigator.clipboard.writeText(m.content)}
                className={`mt-1 block text-xs text-neutral-500 opacity-0 hover:text-neutral-300 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-500 group-hover:opacity-100 ${m.role === 'user' ? 'ml-auto' : ''}`}
              >
                Copy
              </button>
            </div>
          </div>
        ))}
        {streaming && (
          <div className="flex justify-start">
            <div className="markdown max-w-[80%] whitespace-pre-wrap rounded-lg bg-neutral-800 px-3 py-2 text-sm text-neutral-200">
              {streamText ? <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" /> }}>{streamText}</ReactMarkdown> : '…'}
            </div>
          </div>
        )}
        {!streaming && messages.length === 0 && <p className="pt-8 text-center text-sm text-neutral-500">开始新的对话吧。</p>}
        {error && (
          <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            <span>{error}</span>
            <button type="button" onClick={handleRegenerate} className="rounded border border-red-800 px-2 py-1 text-xs hover:bg-red-900">重试</button>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <footer className="flex items-center gap-2 border-t border-neutral-800 p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="输入消息…"
          aria-label="输入消息"
          className="flex-1 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500"
        />
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          disabled={options.length === 0}
          aria-label="选择模型"
          className="rounded-lg border border-neutral-700 bg-neutral-900 px-2 py-2 text-sm text-neutral-300"
        >
          {options.length === 0 ? (
            <option value="">未配置 Provider</option>
          ) : (
            options.map((o) => (
              <option key={`${o.providerId}::${o.model}`} value={`${o.providerId}::${o.model}`}>
                {o.label}
              </option>
            ))
          )}
        </select>
        <button
          onClick={streaming ? stopGeneration : handleSend}
          disabled={!streaming && !canSend}
          className="rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {streaming ? 'Stop' : 'Send'}
        </button>
      </footer>
    </section>
  )
}
