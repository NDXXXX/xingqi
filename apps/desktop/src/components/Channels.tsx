import { useState } from 'react'
import { useAppStore } from '../store/useAppStore'

const inputClass =
  'w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500'

export default function ChannelsPage() {
  const { channels, connectChannel, disconnectChannel } = useAppStore()
  const [wsUrl, setWsUrl] = useState('')
  const [accessToken, setAccessToken] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!wsUrl.trim()) return
    setError(null)
    try {
      await connectChannel('qq', wsUrl.trim(), accessToken.trim() || null)
      setWsUrl('')
      setAccessToken('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <section className="flex h-full flex-col">
      <header className="border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">Channels</h2>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <form
          className="space-y-2 rounded-lg border border-neutral-800 bg-neutral-900 p-4"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <h3 className="text-sm font-medium text-neutral-200">连接 QQ（OneBot v11 反向 WebSocket）</h3>
          <input value={wsUrl} onChange={(e) => setWsUrl(e.target.value)} placeholder="ws://127.0.0.1:3001" className={inputClass} />
          <input value={accessToken} onChange={(e) => setAccessToken(e.target.value)} placeholder="Access Token（可选）" className={inputClass} />
          {error && <p className="text-sm text-red-300">{error}</p>}
          <div className="flex justify-end">
            <button type="submit" disabled={!wsUrl.trim()} className="rounded-lg bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white disabled:opacity-50">
              连接
            </button>
          </div>
        </form>

        {channels.length === 0 ? (
          <p className="pt-4 text-center text-sm text-neutral-500">暂无可用的渠道。</p>
        ) : (
          channels.map((c) => (
            <div key={c.channel} className="flex items-center justify-between rounded-lg border border-neutral-800 bg-neutral-900 p-3">
              <div className="flex items-center gap-2 text-sm font-medium text-neutral-100">
                <span className={`h-2 w-2 rounded-full ${c.connected ? 'bg-emerald-400' : 'bg-neutral-600'}`} />
                {c.channel === 'qq' ? 'QQ' : c.channel}
              </div>
              {c.connected && (
                <button onClick={() => disconnectChannel(c.channel)} className="rounded-lg border border-neutral-700 px-2 py-1 text-sm text-neutral-300 hover:bg-red-900/40">
                  断开
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </section>
  )
}
