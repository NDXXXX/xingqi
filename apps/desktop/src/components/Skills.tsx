import { useAppStore } from '../store/useAppStore'

export default function SkillsPage() {
  const { skills, reloadSkills } = useAppStore()
  return (
    <section className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">Skills</h2>
        <button
          onClick={reloadSkills}
          className="rounded-lg border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800"
        >
          Reload
        </button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {skills.length === 0 ? (
          <p className="pt-8 text-center text-sm text-neutral-500">
            还没有技能。在 skills/ 目录放置 SKILL.md 后点 Reload。
          </p>
        ) : (
          skills.map((s) => (
            <div key={s.name} className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
              <div className="text-sm font-medium text-neutral-100">{s.name}</div>
              {s.description && <div className="mt-1 text-sm text-neutral-400">{s.description}</div>}
              <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-neutral-500">{s.content}</pre>
            </div>
          ))
        )}
      </div>
    </section>
  )
}
