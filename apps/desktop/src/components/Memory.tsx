import { useState } from 'react'
import type { ChangeEvent, ReactNode } from 'react'
import { useAppStore } from '../store/useAppStore'
import type { Memory, MemoryPayload } from '../types'

const MEMORY_TYPES = ['profile', 'preference', 'goal', 'fact', 'relationship', 'project'] as const

const TYPE_LABELS: Record<string, string> = {
  profile: '身份',
  preference: '偏好',
  goal: '目标',
  fact: '事实',
  relationship: '关系',
  project: '项目',
}

type FormState = {
  type: string
  content: string
  importance: string
}

const EMPTY: FormState = { type: 'fact', content: '', importance: '0.5' }

const inputClass =
  'w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-neutral-500">{label}</span>
      {children}
    </label>
  )
}

function toForm(m: Memory): FormState {
  return { type: m.type, content: m.content, importance: String(m.importance) }
}

export default function MemoryPage() {
  const { memories, createMemory, updateMemory, deleteMemory } = useAppStore()
  const [open, setOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY)

  const startNew = () => {
    setEditingId(null)
    setForm(EMPTY)
    setOpen(true)
  }
  const startEdit = (m: Memory) => {
    setEditingId(m.id)
    setForm(toForm(m))
    setOpen(true)
  }
  const close = () => {
    setOpen(false)
    setEditingId(null)
    setForm(EMPTY)
  }

  const set =
    (k: keyof FormState) => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async () => {
    if (!form.content.trim()) return
    const payload: MemoryPayload = {
      type: form.type,
      content: form.content,
      importance: Number(form.importance) || 0.5,
    }
    if (editingId) await updateMemory(editingId, payload)
    else await createMemory(payload)
    close()
  }

  const remove = async (m: Memory) => {
    if (window.confirm('删除这条记忆？')) await deleteMemory(m.id)
  }

  return (
    <section className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">Memory</h2>
        {!open && (
          <button
            onClick={startNew}
            className="rounded-lg bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white"
          >
            New
          </button>
        )}
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {open && (
          <form
            className="space-y-3 rounded-lg border border-neutral-800 bg-neutral-900 p-4"
            onSubmit={(e) => {
              e.preventDefault()
              submit()
            }}
          >
            <h3 className="text-sm font-medium text-neutral-200">{editingId ? '编辑记忆' : '新建记忆'}</h3>
            <Field label="类型">
              <select value={form.type} onChange={set('type')} className={inputClass}>
                {MEMORY_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {TYPE_LABELS[t]}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="内容（必填）">
              <textarea value={form.content} onChange={set('content')} rows={3} className={inputClass} />
            </Field>
            <Field label="重要性（0-1）">
              <input value={form.importance} onChange={set('importance')} type="number" min="0" max="1" step="0.1" className={inputClass} />
            </Field>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={close}
                className="rounded-lg border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={!form.content.trim()}
                className="rounded-lg bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
              >
                保存
              </button>
            </div>
          </form>
        )}

        {memories.length === 0 && !open ? (
          <p className="pt-8 text-center text-sm text-neutral-500">还没有记忆。聊天时 Agent 会自动提取，或点「New」手动添加。</p>
        ) : (
          memories.map((m) => (
            <div key={m.id} className="flex items-start justify-between rounded-lg border border-neutral-800 bg-neutral-900 p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-neutral-800 px-1.5 py-0.5 text-xs text-neutral-400">{TYPE_LABELS[m.type] ?? m.type}</span>
                  <span className="text-xs text-neutral-600">重要度 {m.importance.toFixed(1)}</span>
                </div>
                <div className="mt-1 text-sm text-neutral-100">{m.content}</div>
              </div>
              <div className="ml-4 flex shrink-0 gap-2">
                <button
                  onClick={() => startEdit(m)}
                  className="rounded-lg border border-neutral-700 px-2 py-1 text-sm text-neutral-300 hover:bg-neutral-800"
                >
                  编辑
                </button>
                <button
                  onClick={() => remove(m)}
                  className="rounded-lg border border-neutral-700 px-2 py-1 text-sm text-neutral-300 hover:bg-red-900/40"
                >
                  删除
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  )
}
