import { useAppStore } from '../store/useAppStore'

const STEP_LABELS: Record<string, string> = {
  load_context: 'Load Context',
  call_llm: 'Call LLM',
  execute_tool: 'Execute Tool',
  finalize: 'Finalize',
}

export default function AgentRunPanel() {
  const agentSteps = useAppStore((s) => s.agentSteps)
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-l border-neutral-800 bg-neutral-900">
      <header className="border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">Agent Run</h2>
      </header>
      <ul className="flex-1 space-y-1 overflow-y-auto p-3">
        {agentSteps.length === 0 ? (
          <p className="px-2 py-1.5 text-sm text-neutral-600">发送消息后显示 Agent 步骤。</p>
        ) : (
          agentSteps.map((step, i) => (
            <li key={`${step.name}-${i}`} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-neutral-300">
              <span className={step.status === 'done' ? 'text-emerald-400' : 'text-neutral-600'}>
                {step.status === 'done' ? '✓' : '○'}
              </span>
              {STEP_LABELS[step.name] ?? step.name}
            </li>
          ))
        )}
      </ul>
    </aside>
  )
}
