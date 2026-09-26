import { useState } from 'react'
import { useAppStore } from '../store/useAppStore'
import type { View } from '../types'

const NAV_ITEMS: { view: View; label: string }[] = [
  { view: 'characters', label: 'Characters' },
  { view: 'memory', label: 'Memory' },
  { view: 'skills', label: 'Skills' },
  { view: 'mcp', label: 'MCP' },
  { view: 'channels', label: 'Channels' },
]

const itemClass = (active: boolean) =>
  `flex w-full items-center px-3 py-2 text-left text-sm ${
    active ? 'bg-neutral-800 text-neutral-100' : 'text-neutral-400 hover:bg-neutral-800/50'
  }`

export default function Sidebar() {
  const { activeView, activeConversationId, conversations, setActiveView, selectConversation, newConversation, deleteConversation, renameConversation } =
    useAppStore()
  const [query, setQuery] = useState('')
  const visibleConversations = conversations.filter((conversation) =>
    conversation.title.toLowerCase().includes(query.trim().toLowerCase()),
  )

  const removeConversation = async (id: string, title: string) => {
    if (window.confirm(`删除会话「${title}」及其全部消息？`)) await deleteConversation(id)
  }

  const rename = async (id: string, title: string) => {
    const nextTitle = window.prompt('会话名称', title)?.trim()
    if (nextTitle && nextTitle !== title) await renameConversation(id, nextTitle)
  }

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-neutral-800 bg-neutral-900">
      <button
        onClick={newConversation}
        className="m-3 rounded-lg bg-neutral-100 px-3 py-2 text-sm font-medium text-neutral-900 hover:bg-white"
      >
        New Chat
      </button>

      <nav className="flex-1 overflow-y-auto">
        <div className="px-3 py-2 text-xs uppercase tracking-wide text-neutral-500">Chats</div>
        <div className="px-3 pb-2">
          <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="搜索会话" placeholder="搜索会话" className="w-full rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-200 outline-none focus:border-neutral-500" />
        </div>
        {visibleConversations.map((c) => (
          <div key={c.id} className="group relative">
            <button
              onClick={() => void rename(c.id, c.title)}
              title="重命名会话"
              aria-label={`重命名会话 ${c.title}`}
              className="absolute right-7 top-1/2 -translate-y-1/2 rounded px-1 text-xs text-neutral-500 opacity-0 hover:bg-neutral-800 hover:text-neutral-200 focus-visible:opacity-100 group-hover:opacity-100"
            >
              ✎
            </button>
            <button
              onClick={() => selectConversation(c.id)}
              className={`${itemClass(activeView === 'chat' && c.id === activeConversationId)} pr-14`}
            >
              <span className="mr-2">{c.channel === 'qq' ? '💬' : '🖥'}</span>
              <span className="truncate">{c.title}</span>
            </button>
            <button
              onClick={() => removeConversation(c.id, c.title)}
              title="删除会话"
              aria-label={`删除会话 ${c.title}`}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-1 text-neutral-500 opacity-0 hover:bg-red-950 hover:text-red-300 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-700 group-hover:opacity-100"
            >
              ×
            </button>
          </div>
        ))}

        <div className="mt-3 border-t border-neutral-800" />
        {NAV_ITEMS.map((item) => (
          <button key={item.view} onClick={() => setActiveView(item.view)} className={itemClass(activeView === item.view)}>
            {item.label}
          </button>
        ))}

        <div className="mt-3 border-t border-neutral-800" />
        <button onClick={() => setActiveView('settings')} className={itemClass(activeView === 'settings')}>
          Settings
        </button>
      </nav>
    </aside>
  )
}
