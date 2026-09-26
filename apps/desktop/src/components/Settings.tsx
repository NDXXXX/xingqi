import { useState } from 'react'
import { api } from '../api/client'
import { useAppStore } from '../store/useAppStore'
import type { Provider, ProviderTestResult, View } from '../types'

const PROVIDER_TYPES = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'minimax', label: 'MiniMax' },
  { value: 'kimi', label: 'Kimi / Moonshot' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
]

const SHORTCUTS: { view: View; label: string; description: string }[] = [
  { view: 'characters', label: 'Characters', description: '角色与提示词' },
  { view: 'memory', label: 'Memory', description: '长期记忆' },
  { view: 'skills', label: 'Skills', description: '本地技能' },
  { view: 'mcp', label: 'MCP', description: '外部工具服务' },
  { view: 'channels', label: 'Channels', description: 'QQ 等消息渠道' },
]

const inputClass =
  'w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500 focus-visible:ring-2 focus-visible:ring-neutral-600'
const secondaryButton =
  'rounded-lg border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:bg-neutral-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-500 disabled:opacity-50'

function ProviderEditor({ provider, close }: { provider: Provider; close: () => void }) {
  const updateProvider = useAppStore((state) => state.updateProvider)
  const [name, setName] = useState(provider.name)
  const [baseUrl, setBaseUrl] = useState(provider.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim()) return
    setSaving(true)
    setError(null)
    try {
      await updateProvider(provider.id, {
        name: name.trim(),
        base_url: baseUrl.trim() || null,
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      })
      close()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      className="mt-3 grid gap-2 border-t border-neutral-800 pt-3 md:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault()
        void submit()
      }}
    >
      <label className="space-y-1 text-xs text-neutral-400">配置名称
        <input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} />
      </label>
      <label className="space-y-1 text-xs text-neutral-400">Base URL
        <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="留空使用默认地址" className={inputClass} />
      </label>
      <label className="space-y-1 text-xs text-neutral-400 md:col-span-2">新 API Key（留空则不修改）
        <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" autoComplete="off" className={inputClass} />
      </label>
      {error && <p role="alert" className="text-sm text-red-300 md:col-span-2">{error}</p>}
      <div className="flex justify-end gap-2 md:col-span-2">
        <button type="button" onClick={close} className={secondaryButton}>取消</button>
        <button type="submit" disabled={saving || !name.trim()} className="rounded-lg bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 disabled:opacity-50">
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
    </form>
  )
}

export default function Settings() {
  const {
    providers, defaultModel, createProvider, updateProvider, deleteProvider,
    createModel, updateModel, deleteModel, setDefaultModel, setActiveView,
  } = useAppStore()
  const [name, setName] = useState('')
  const [providerType, setProviderType] = useState('deepseek')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, ProviderTestResult>>({})
  const [editingId, setEditingId] = useState<string | null>(null)
  const [addingModelFor, setAddingModelFor] = useState<string | null>(null)
  const [modelName, setModelName] = useState('')
  const [modelDisplayName, setModelDisplayName] = useState('')

  const run = async (action: () => Promise<void>) => {
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const submit = async () => {
    if (!name.trim() || !apiKey.trim() || saving) return
    setSaving(true)
    await run(async () => {
      await createProvider({ name: name.trim(), provider_type: providerType, api_key: apiKey.trim(), base_url: baseUrl.trim() || null })
      setName('')
      setApiKey('')
      setBaseUrl('')
    })
    setSaving(false)
  }

  const test = async (id: string) => {
    setTestingId(id)
    try {
      const result = await api.testProvider(id)
      setTestResults((current) => ({ ...current, [id]: result }))
    } catch (e) {
      setTestResults((current) => ({ ...current, [id]: { ok: false, detail: e instanceof Error ? e.message : String(e) } }))
    } finally {
      setTestingId(null)
    }
  }

  const addModel = async (providerId: string) => {
    if (!modelName.trim()) return
    await run(async () => {
      await createModel(providerId, { model_name: modelName.trim(), display_name: modelDisplayName.trim() || modelName.trim() })
      setModelName('')
      setModelDisplayName('')
      setAddingModelFor(null)
    })
  }

  const defaultValue = defaultModel.provider_id && defaultModel.model_id
    ? `${defaultModel.provider_id}::${defaultModel.model_id}`
    : ''

  return (
    <section className="flex h-full flex-col">
      <header className="border-b border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-medium text-neutral-200">Settings</h2>
      </header>
      <div className="flex-1 space-y-6 overflow-y-auto p-4">
        <div>
          <h3 className="text-sm font-medium text-neutral-100">AI Providers</h3>
          <p className="mt-1 text-xs text-neutral-500">API Key 仅保存在系统钥匙串中。</p>

          <form
            className="mt-3 grid gap-2 rounded-lg border border-neutral-800 bg-neutral-900 p-4 md:grid-cols-2"
            onSubmit={(event) => { event.preventDefault(); void submit() }}
          >
            <label className="space-y-1 text-xs text-neutral-400">配置名称 <span className="text-red-300">*</span>
              <input required value={name} onChange={(event) => setName(event.target.value)} placeholder="如 My DeepSeek" className={inputClass} />
            </label>
            <label className="space-y-1 text-xs text-neutral-400">Provider 类型
              <select value={providerType} onChange={(event) => setProviderType(event.target.value)} className={inputClass}>
                {PROVIDER_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-xs text-neutral-400">API Key <span className="text-red-300">*</span>
              <input required value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" autoComplete="off" placeholder="仅保存到系统钥匙串" className={inputClass} />
            </label>
            <label className="space-y-1 text-xs text-neutral-400">Base URL（可选）
              <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="留空使用默认地址" className={inputClass} />
            </label>
            <div className="flex justify-end md:col-span-2">
              <button type="submit" disabled={!name.trim() || !apiKey.trim() || saving} className="rounded-lg bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 disabled:opacity-50">
                {saving ? '保存中…' : '添加 Provider'}
              </button>
            </div>
          </form>

          {error && <p role="alert" className="mt-3 rounded-lg border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</p>}

          <label className="mt-4 block space-y-1 text-xs text-neutral-400">全局默认模型
            <select
              value={defaultValue}
              onChange={(event) => {
                const [providerId, modelId] = event.target.value.split('::')
                void run(() => setDefaultModel({ provider_id: providerId || null, model_id: modelId || null }))
              }}
              className={inputClass}
            >
              <option value="">自动选择</option>
              {providers.filter((provider) => provider.enabled).flatMap((provider) =>
                provider.models.filter((model) => model.enabled).map((model) => (
                  <option key={model.id} value={`${provider.id}::${model.id}`}>{provider.name} · {model.display_name}</option>
                )),
              )}
            </select>
          </label>

          <div className="mt-3 space-y-3">
            {providers.length === 0 ? (
              <p className="rounded-lg border border-dashed border-neutral-800 px-3 py-5 text-center text-sm text-neutral-500">尚未配置 Provider。</p>
            ) : providers.map((provider) => {
              const result = testResults[provider.id]
              return (
                <article key={provider.id} className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-sm font-medium text-neutral-100">
                        <span className={`h-2 w-2 rounded-full ${provider.enabled && provider.configured ? 'bg-emerald-400' : 'bg-neutral-600'}`} />
                        {provider.name}<span className="text-xs font-normal text-neutral-500">{provider.provider_type}</span>
                      </div>
                      {provider.base_url && <p className="mt-1 truncate text-xs text-neutral-500">{provider.base_url}</p>}
                      {result && <p role="status" className={`mt-1 text-xs ${result.ok ? 'text-emerald-400' : 'text-red-300'}`}>{result.ok ? '连接成功' : result.detail}</p>}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" onClick={() => void test(provider.id)} disabled={testingId === provider.id || !provider.configured} className={secondaryButton}>{testingId === provider.id ? '测试中…' : '测试'}</button>
                      <button type="button" onClick={() => void run(() => updateProvider(provider.id, { enabled: !provider.enabled }))} className={secondaryButton}>{provider.enabled ? '停用' : '启用'}</button>
                      <button type="button" onClick={() => setEditingId(editingId === provider.id ? null : provider.id)} className={secondaryButton}>编辑</button>
                      <button type="button" onClick={() => { if (window.confirm(`删除 Provider「${provider.name}」及其模型？`)) void run(() => deleteProvider(provider.id)) }} className={`${secondaryButton} hover:border-red-900 hover:bg-red-950/50 hover:text-red-300`}>删除</button>
                    </div>
                  </div>

                  {editingId === provider.id && <ProviderEditor provider={provider} close={() => setEditingId(null)} />}

                  <div className="mt-3 border-t border-neutral-800 pt-3">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-medium uppercase tracking-wide text-neutral-500">Models</h4>
                      <button type="button" onClick={() => setAddingModelFor(addingModelFor === provider.id ? null : provider.id)} className={secondaryButton}>添加模型</button>
                    </div>
                    <ul className="mt-2 space-y-1">
                      {provider.models.map((model) => (
                        <li key={model.id} className="flex items-center justify-between gap-3 rounded-md bg-neutral-950/70 px-2 py-2">
                          <div className="min-w-0"><span className={`text-sm ${model.enabled ? 'text-neutral-200' : 'text-neutral-600'}`}>{model.display_name}</span><span className="ml-2 text-xs text-neutral-600">{model.model_name}</span></div>
                          <div className="flex shrink-0 gap-2">
                            <button type="button" onClick={() => void run(() => updateModel(provider.id, model.id, { enabled: !model.enabled }))} className={secondaryButton}>{model.enabled ? '停用' : '启用'}</button>
                            <button type="button" onClick={() => { if (window.confirm(`删除模型「${model.display_name}」？`)) void run(() => deleteModel(provider.id, model.id)) }} className={secondaryButton}>删除</button>
                          </div>
                        </li>
                      ))}
                    </ul>

                    {addingModelFor === provider.id && (
                      <form className="mt-2 grid gap-2 rounded-md border border-neutral-800 p-3 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); void addModel(provider.id) }}>
                        <label className="space-y-1 text-xs text-neutral-400">模型名称
                          <input required value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="model-id" className={inputClass} />
                        </label>
                        <label className="space-y-1 text-xs text-neutral-400">显示名称
                          <input value={modelDisplayName} onChange={(event) => setModelDisplayName(event.target.value)} placeholder="留空使用模型名称" className={inputClass} />
                        </label>
                        <div className="flex justify-end gap-2 md:col-span-2">
                          <button type="button" onClick={() => setAddingModelFor(null)} className={secondaryButton}>取消</button>
                          <button type="submit" disabled={!modelName.trim()} className="rounded-lg bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 disabled:opacity-50">保存模型</button>
                        </div>
                      </form>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
        </div>

        <div>
          <h3 className="text-sm font-medium text-neutral-100">功能设置</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {SHORTCUTS.map((item) => (
              <button key={item.view} onClick={() => setActiveView(item.view)} className="flex items-center justify-between rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-left hover:bg-neutral-800/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-500">
                <span><span className="block text-sm text-neutral-200">{item.label}</span><span className="block text-xs text-neutral-500">{item.description}</span></span>
                <span aria-hidden="true" className="text-neutral-600">›</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
