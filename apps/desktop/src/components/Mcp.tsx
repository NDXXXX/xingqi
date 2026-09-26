import { useState } from 'react'
import { useAppStore } from '../store/useAppStore'

export default function McpPage() {
  const { mcpServers, connectMcp, disconnectMcp } = useAppStore()
  const [name, setName] = useState('')
  const [command, setCommand] = useState('')
  const [args, setArgs] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim() || !command.trim()) return
    const parsedArgs = args.split(/\s+/).filter(Boolean)
    if (!window.confirm(`将启动本地命令：\n\n${command.trim()} ${parsedArgs.join(' ')}\n\n是否继续？`)) return
    setError(null)
    try {
      await connectMcp(name.trim(), command.trim(), parsedArgs)
      setName('')
      setCommand('')
      setArgs('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <section className="flex h-full flex-col">
      <header className="border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">MCP</h2>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <form
          className="space-y-2 rounded-lg border border-neutral-800 bg-neutral-900 p-4"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <h3 className="text-sm font-medium text-neutral-200">连接 MCP 服务器</h3>
          <label className="block text-xs text-neutral-400">名称<input value={name} onChange={(e) => setName(e.target.value)} placeholder="如 filesystem" className="mt-1 w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500" /></label>
          <label className="block text-xs text-neutral-400">命令<input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="如 npx" className="mt-1 w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500" /></label>
          <label className="block text-xs text-neutral-400">参数<input value={args} onChange={(e) => setArgs(e.target.value)} placeholder="空格分隔，如 -y @modelcontextprotocol/server-filesystem" className="mt-1 w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500" /></label>
          {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
          <div className="flex justify-end">
            <button type="submit" disabled={!name.trim() || !command.trim()} className="rounded-lg bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white disabled:opacity-50">
              连接
            </button>
          </div>
        </form>

        {mcpServers.length === 0 ? (
          <p className="pt-4 text-center text-sm text-neutral-500">还没有连接的 MCP 服务器。</p>
        ) : (
          mcpServers.map((s) => (
            <div key={s.name} className="flex items-start justify-between rounded-lg border border-neutral-800 bg-neutral-900 p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm font-medium text-neutral-100">
                  <span className={`h-2 w-2 rounded-full ${s.connected ? 'bg-emerald-400' : 'bg-neutral-600'}`} />
                  {s.name}
                </div>
                <div className="mt-1 text-xs text-neutral-500">{s.command} {s.args.join(' ')}</div>
                {s.tools.length > 0 && <div className="mt-1 text-xs text-neutral-500">工具：{s.tools.join(', ')}</div>}
              </div>
              <button
                onClick={() => s.connected ? disconnectMcp(s.name) : connectMcp(s.name, s.command, s.args)}
                className="ml-4 shrink-0 rounded-lg border border-neutral-700 px-2 py-1 text-sm text-neutral-300 hover:bg-neutral-800"
              >
                {s.connected ? '断开' : '重连'}
              </button>
            </div>
          ))
        )}
      </div>
    </section>
  )
}
