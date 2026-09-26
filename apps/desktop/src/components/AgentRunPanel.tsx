import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAppStore } from '../store/useAppStore'
import type { AgentRun } from '../types'

const STEP_LABELS: Record<string, string> = {
  load_context: 'Load Context',
  call_llm: 'Call LLM',
  execute_tool: 'Execute Tool',
  finalize: 'Finalize',
}

export default function AgentRunPanel() {
  const agentSteps = useAppStore((s) => s.agentSteps)
  const activeConversationId = useAppStore((s) => s.activeConversationId)
  const streaming = useAppStore((s) => s.streaming)
  const [latestRun, setLatestRun] = useState<AgentRun | null>(null)

  useEffect(() => {
    if (!activeConversationId || streaming) return
    void api.listAgentRuns(activeConversationId)
      .then((runs) => setLatestRun(runs[0] ?? null))
      .catch(() => setLatestRun(null))
  }, [activeConversationId, streaming])

  const savedSteps = !streaming && latestRun
    ? latestRun.steps.map((step) => ({
        type: step.step_type,
        name: step.name,
        status: step.status,
        input: step.input_json ? JSON.parse(step.input_json) : undefined,
        output: step.output_json ? JSON.parse(step.output_json) : undefined,
        error: step.error,
      }))
    : []
  const steps = streaming ? agentSteps : savedSteps.length > 0 ? savedSteps : agentSteps
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-l border-neutral-800 bg-neutral-900">
      <header className="border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">Agent Run</h2>
      </header>
      {latestRun && !streaming && (
        <div className="border-b border-neutral-800 px-4 py-2 text-xs text-neutral-500">
          <span className={latestRun.status === 'completed' ? 'text-emerald-400' : latestRun.status === 'failed' ? 'text-red-400' : 'text-amber-400'}>{latestRun.status}</span>
          {latestRun.duration_ms !== null && <span> · {latestRun.duration_ms} ms</span>}
          <span className="mt-1 block truncate" title={latestRun.model_id}>{latestRun.model_id}</span>
          {latestRun.error && <span role="alert" className="mt-1 block text-red-300">{latestRun.error}</span>}
        </div>
      )}
      <ul className="flex-1 space-y-1 overflow-y-auto p-3">
        {steps.length === 0 ? (
          <p className="px-2 py-1.5 text-sm text-neutral-600">发送消息后显示 Agent 步骤。</p>
        ) : (
          steps.map((step, i) => (
            <li key={`${step.name}-${i}`} className="rounded-md px-2 py-1.5 text-sm text-neutral-300">
              <div className="flex items-center gap-2">
                <span className={step.status === 'completed' ? 'text-emerald-400' : step.status === 'failed' ? 'text-red-400' : 'text-neutral-600'}>
                  {step.status === 'completed' ? '✓' : step.status === 'failed' ? '×' : '○'}
                </span>
                {step.type === 'tool' ? `Tool · ${step.name}` : STEP_LABELS[step.name] ?? step.name}
              </div>
              {step.type === 'tool' && step.input !== undefined && (
                <pre className="mt-1 overflow-x-auto whitespace-pre-wrap pl-5 text-[11px] text-neutral-500">{JSON.stringify(step.input, null, 2)}</pre>
              )}
              {step.error && <p className="mt-1 pl-5 text-xs text-red-300">{step.error}</p>}
              {step.type === 'tool' && step.output !== undefined && (
                <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap pl-5 text-[11px] text-neutral-600">{typeof step.output === 'string' ? step.output : JSON.stringify(step.output, null, 2)}</pre>
              )}
            </li>
          ))
        )}
      </ul>
    </aside>
  )
}
