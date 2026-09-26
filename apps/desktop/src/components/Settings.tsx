import { mockSettingsCategories } from '../data/mock'

export default function Settings() {
  return (
    <section className="flex h-full flex-col">
      <header className="border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">Settings</h2>
      </header>
      <ul className="flex-1 space-y-0.5 overflow-y-auto p-3">
        {mockSettingsCategories.map((category) => (
          <li
            key={category}
            className="flex items-center justify-between rounded-md px-3 py-2 text-sm text-neutral-300 hover:bg-neutral-800/50"
          >
            {category}
            <span className="text-neutral-600">›</span>
          </li>
        ))}
      </ul>
      <p className="border-t border-neutral-800 px-4 py-3 text-xs text-neutral-500">
        Phase 2 — 静态占位，配置项将在后续 Phase 实现。
      </p>
    </section>
  )
}
