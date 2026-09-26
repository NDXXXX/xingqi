import { useEffect, useState } from 'react'
import { api } from './api/client'
import AgentRunPanel from './components/AgentRunPanel'
import Channels from './components/Channels'
import Characters from './components/Characters'
import Chat from './components/Chat'
import Mcp from './components/Mcp'
import Memory from './components/Memory'
import Skills from './components/Skills'
import Settings from './components/Settings'
import Sidebar from './components/Sidebar'
import Toast from './components/Toast'
import { useAppStore } from './store/useAppStore'

function MainView() {
  const activeView = useAppStore((s) => s.activeView)
  if (activeView === 'chat') return <Chat />
  if (activeView === 'characters') return <Characters />
  if (activeView === 'memory') return <Memory />
  if (activeView === 'skills') return <Skills />
  if (activeView === 'mcp') return <Mcp />
  if (activeView === 'channels') return <Channels />
  if (activeView === 'settings') return <Settings />
  return null
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
  const reloadConversations = useAppStore((s) => s.reloadConversations)
  const [mobileSidebar, setMobileSidebar] = useState(false)
  const [mobileRuns, setMobileRuns] = useState(false)

  useEffect(() => {
    let cancelled = false
    let retryTimer: number | undefined
    const load = async (attempt = 1) => {
      try {
        await init()
      } catch {
        if (!cancelled && attempt < 15) retryTimer = window.setTimeout(() => load(attempt + 1), 1000)
      }
    }
    void load()
    return () => {
      cancelled = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
    }
  }, [init])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void reloadConversations().catch(() => {
        // BackendStatus 单独展示断线状态；轮询失败时保留当前数据。
      })
    }, 3000)
    return () => window.clearInterval(timer)
  }, [reloadConversations])

  return (
    <div className="flex h-screen flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setMobileSidebar(true)} aria-label="打开导航" className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 lg:hidden">☰</button>
          <h1 className="text-sm font-semibold">Desktop AI Companion</h1>
        </div>
        <div className="flex items-center gap-4">
          <button type="button" onClick={() => setMobileRuns(true)} className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 xl:hidden">Agent</button>
          <BackendStatus />
          <button onClick={() => setActiveView('settings')} className="text-sm text-neutral-400 hover:text-neutral-100">
            Settings
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="hidden lg:block"><Sidebar /></div>
        <main className="min-w-0 flex-1">
          <MainView />
        </main>
        <div className="hidden xl:block"><AgentRunPanel /></div>
      </div>

      {mobileSidebar && (
        <div className="fixed inset-0 z-50 bg-black/60 lg:hidden" onClick={() => setMobileSidebar(false)}>
          <div role="dialog" aria-modal="true" aria-label="导航" className="relative h-full w-64" onClick={(event) => event.stopPropagation()}>
            <Sidebar />
            <button type="button" onClick={() => setMobileSidebar(false)} aria-label="关闭导航" className="absolute right-2 top-2 rounded px-2 py-1 text-neutral-400 hover:bg-neutral-800">×</button>
          </div>
        </div>
      )}
      {mobileRuns && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/60 xl:hidden" onClick={() => setMobileRuns(false)}>
          <div role="dialog" aria-modal="true" aria-label="Agent Run" className="relative h-full" onClick={(event) => event.stopPropagation()}>
            <AgentRunPanel />
            <button type="button" onClick={() => setMobileRuns(false)} aria-label="关闭 Agent Run" className="absolute right-2 top-2 rounded px-2 py-1 text-neutral-400 hover:bg-neutral-800">×</button>
          </div>
        </div>
      )}
      <Toast />
    </div>
  )
}
