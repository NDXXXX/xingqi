import { useEffect, useState } from 'react'
import { api } from './api/client'
import AgentRunPanel from './components/AgentRunPanel'
import Characters from './components/Characters'
import Chat from './components/Chat'
import Mcp from './components/Mcp'
import Memory from './components/Memory'
import Placeholder from './components/Placeholder'
import Skills from './components/Skills'
import Settings from './components/Settings'
import Sidebar from './components/Sidebar'
import { useAppStore } from './store/useAppStore'

const PLACEHOLDER_TITLES: Record<string, string> = {
  channels: 'Channels',
}

function MainView() {
  const activeView = useAppStore((s) => s.activeView)
  if (activeView === 'chat') return <Chat />
  if (activeView === 'characters') return <Characters />
  if (activeView === 'memory') return <Memory />
  if (activeView === 'skills') return <Skills />
  if (activeView === 'mcp') return <Mcp />
  if (activeView === 'settings') return <Settings />
  return <Placeholder title={PLACEHOLDER_TITLES[activeView]} />
}

function BackendStatus() {
  const [ok, setOk] = useState<boolean | null>(null)
  useEffect(() => {
    let cancelled = false
    let attempts = 0
    const check = async () => {
      try {
        await api.health()
        if (!cancelled) setOk(true)
      } catch {
        if (cancelled) return
        attempts += 1
        // 后端由主进程异步拉起，启动需 ~1s，轮询直到就绪。
        if (attempts < 15) setTimeout(check, 1000)
        else setOk(false)
      }
    }
    check()
    return () => {
      cancelled = true
    }
  }, [])
  return (
    <span className="flex items-center gap-1.5 text-xs text-neutral-400">
      <span className={`h-2 w-2 rounded-full ${ok === null ? 'bg-neutral-600' : ok ? 'bg-emerald-400' : 'bg-red-400'}`} />
      {ok === null ? 'Backend…' : ok ? 'Backend ok' : 'Backend down'}
    </span>
  )
}

export default function App() {
  const setActiveView = useAppStore((s) => s.setActiveView)
  const init = useAppStore((s) => s.init)

  useEffect(() => {
    init()
  }, [init])

  return (
    <div className="flex h-screen flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <h1 className="text-sm font-semibold">Desktop AI Companion</h1>
        <div className="flex items-center gap-4">
          <BackendStatus />
          <button onClick={() => setActiveView('settings')} className="text-sm text-neutral-400 hover:text-neutral-100">
            Settings
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1">
          <MainView />
        </main>
        <AgentRunPanel />
      </div>
    </div>
  )
}
