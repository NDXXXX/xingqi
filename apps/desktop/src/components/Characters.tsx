import { useState } from 'react'
import type { ChangeEvent, ReactNode } from 'react'
import { useAppStore } from '../store/useAppStore'
import type { Character } from '../types'

type FormState = {
  name: string
  description: string
  personality: string
  background: string
  speaking_style: string
  system_prompt: string
}

const EMPTY: FormState = {
  name: '',
  description: '',
  personality: '',
  background: '',
  speaking_style: '',
  system_prompt: '',
}

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

function toForm(c: Character): FormState {
  return {
    name: c.name,
    description: c.description ?? '',
    personality: c.personality ?? '',
    background: c.background ?? '',
    speaking_style: c.speaking_style ?? '',
    system_prompt: c.system_prompt ?? '',
  }
}

export default function Characters() {
  const { characters, createCharacter, updateCharacter, deleteCharacter } = useAppStore()
  const [open, setOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY)

  const startNew = () => {
    setEditingId(null)
    setForm(EMPTY)
    setOpen(true)
  }
  const startEdit = (c: Character) => {
    setEditingId(c.id)
    setForm(toForm(c))
    setOpen(true)
  }
  const close = () => {
    setOpen(false)
    setEditingId(null)
    setForm(EMPTY)
  }

  const set =
    (k: keyof FormState) => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async () => {
    if (!form.name.trim()) return
    if (editingId) await updateCharacter(editingId, form)
    else await createCharacter(form)
    close()
  }

  const remove = async (c: Character) => {
    if (window.confirm(`删除角色「${c.name}」？`)) await deleteCharacter(c.id)
  }

  return (
    <section className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">Characters</h2>
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
            <h3 className="text-sm font-medium text-neutral-200">{editingId ? '编辑角色' : '新建角色'}</h3>
            <Field label="名字（必填）">
              <input value={form.name} onChange={set('name')} className={inputClass} placeholder="Luna" />
            </Field>
            <Field label="描述">
              <textarea value={form.description} onChange={set('description')} rows={2} className={inputClass} />
            </Field>
            <Field label="性格">
              <textarea value={form.personality} onChange={set('personality')} rows={2} className={inputClass} />
            </Field>
            <Field label="背景">
              <textarea value={form.background} onChange={set('background')} rows={2} className={inputClass} />
            </Field>
            <Field label="说话风格">
              <textarea value={form.speaking_style} onChange={set('speaking_style')} rows={2} className={inputClass} />
            </Field>
            <Field label="自定义 System Prompt（可选，优先于上面字段）">
              <textarea value={form.system_prompt} onChange={set('system_prompt')} rows={3} className={inputClass} />
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
                disabled={!form.name.trim()}
                className="rounded-lg bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
              >
                保存
              </button>
            </div>
          </form>
        )}

        {characters.length === 0 && !open ? (
          <p className="pt-8 text-center text-sm text-neutral-500">还没有角色，点「New」创建一个。</p>
        ) : (
          characters.map((c) => (
            <div
              key={c.id}
              className="flex items-start justify-between rounded-lg border border-neutral-800 bg-neutral-900 p-3"
            >
              <div className="min-w-0">
                <div className="text-sm font-medium text-neutral-100">{c.name}</div>
                {c.description && <div className="mt-1 text-sm text-neutral-400">{c.description}</div>}
              </div>
              <div className="ml-4 flex shrink-0 gap-2">
                <button
                  onClick={() => startEdit(c)}
                  className="rounded-lg border border-neutral-700 px-2 py-1 text-sm text-neutral-300 hover:bg-neutral-800"
                >
                  编辑
                </button>
                <button
                  onClick={() => remove(c)}
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
