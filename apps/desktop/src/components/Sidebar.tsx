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
  const { activeView, activeConversationId, conversations, setActiveView, selectConversation, newConversation } =
    useAppStore()

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
        {conversations.map((c) => (
          <button
            key={c.id}
            onClick={() => selectConversation(c.id)}
            className={itemClass(activeView === 'chat' && c.id === activeConversationId)}
          >
            <span className="mr-2">{c.channel === 'qq' ? '💬' : '🖥'}</span>
            {c.title}
          </button>
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
