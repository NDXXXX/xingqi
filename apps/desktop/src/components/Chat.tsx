import { useEffect, useMemo, useState } from 'react'
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
    clearError,
    setConversationCharacter,
  } = useAppStore()

  const [input, setInput] = useState('')
  const [selected, setSelected] = useState('')

  const conversation = conversations.find((c) => c.id === activeConversationId)
  const messages = (activeConversationId && messagesByConversation[activeConversationId]) || []

  const options = useMemo<ModelOption[]>(
    () =>
      providers
        .filter((p) => p.enabled && p.configured)
        .flatMap((p) => p.models.map((m) => ({ providerId: p.id, model: m.model_name, label: `${p.name} · ${m.display_name}` }))),
    [providers],
  )

  useEffect(() => {
    if (!selected && options.length > 0) setSelected(`${options[0].providerId}::${options[0].model}`)
  }, [options, selected])

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

  return (
    <section className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">{conversation?.title ?? 'Chat'}</h2>
        <select
          value={currentCharacterId ?? ''}
          onChange={(e) => handleCharacterChange(e.target.value)}
          disabled={!activeConversationId}
          title={activeConversationId ? '选择角色' : '先打开或新建一个会话'}
          className="rounded-lg border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-300 disabled:opacity-50"
        >
          <option value="">无角色</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[80%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                m.role === 'user' ? 'bg-neutral-100 text-neutral-900' : 'bg-neutral-800 text-neutral-200'
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}
        {streaming && (
          <div className="flex justify-start">
            <div className="max-w-[80%] whitespace-pre-wrap rounded-lg bg-neutral-800 px-3 py-2 text-sm text-neutral-200">
              {streamText || '…'}
            </div>
          </div>
        )}
        {!streaming && messages.length === 0 && <p className="pt-8 text-center text-sm text-neutral-500">开始新的对话吧。</p>}
        {error && (
          <div className="rounded-lg border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">{error}</div>
        )}
      </div>

      <footer className="flex items-center gap-2 border-t border-neutral-800 p-3">
        <button className="rounded-lg border border-neutral-700 px-3 py-2 text-neutral-400" title="附加（后续 Phase）">
          +
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="输入消息…"
          className="flex-1 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500"
        />
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          disabled={options.length === 0}
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
          onClick={handleSend}
          disabled={!canSend}
          className="rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          Send
        </button>
      </footer>
    </section>
  )
}
