import type { AgentRun, Channel, Character, CharacterPayload, Conversation, DefaultModel, McpServer, Memory, MemoryPayload, Message, ModelConfig, ModelConfigPayload, ModelConfigUpdatePayload, Provider, ProviderPayload, ProviderTestResult, ProviderUpdatePayload, Skill } from '../types'

const BACKEND_URL = 'http://127.0.0.1:8001'
let backendToken: Promise<string> | null = null

async function withAuth(headers?: HeadersInit): Promise<Headers> {
  const result = new Headers(headers)
  if (typeof window !== 'undefined' && window.api?.getBackendToken) {
    backendToken ??= window.api.getBackendToken()
    const token = await backendToken
    if (token) result.set('X-Companion-Token', token)
  }
  return result
}

function reportApiError(message: string): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent<string>('companion:api-error', { detail: message }))
  }
}

export interface ChatRequest {
  conversation_id: string | null
  message: string
  provider_id: string | null
  model: string | null
  regenerate?: boolean
}

export interface ChatResult {
  conversation_id: string
  user_message: Message
  assistant_message: Message
}

async function request<T>(path: string, init?: RequestInit, silent = false): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      headers: await withAuth(init?.headers),
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (!silent) reportApiError(message)
    throw error
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = body.error?.message ?? body.detail ?? detail
    } catch {
      /* 忽略非 JSON 响应体 */
    }
    if (!silent) reportApiError(detail)
    throw new Error(detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; service: string }>('/api/health', undefined, true),
  listConversations: () => request<Conversation[]>('/api/conversations'),
  createConversation: (title: string) =>
    request<Conversation>('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, channel: 'desktop' }),
    }),
  deleteConversation: (id: string) => request<void>(`/api/conversations/${id}`, { method: 'DELETE' }),
  renameConversation: (id: string, title: string) =>
    request<Conversation>(`/api/conversations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }),
  listMessages: (conversationId: string) =>
    request<Message[]>(`/api/conversations/${conversationId}/messages`),
  listProviders: () => request<Provider[]>('/api/providers'),
  createProvider: (body: ProviderPayload) =>
    request<Provider>('/api/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateProvider: (id: string, body: ProviderUpdatePayload) =>
    request<Provider>(`/api/providers/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteProvider: (id: string) => request<void>(`/api/providers/${id}`, { method: 'DELETE' }),
  testProvider: (id: string) => request<ProviderTestResult>(`/api/providers/${id}/test`, { method: 'POST' }),
  createModel: (providerId: string, body: ModelConfigPayload) =>
    request<ModelConfig>(`/api/providers/${providerId}/models`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateModel: (providerId: string, modelId: string, body: ModelConfigUpdatePayload) =>
    request<ModelConfig>(`/api/providers/${providerId}/models/${modelId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteModel: (providerId: string, modelId: string) =>
    request<void>(`/api/providers/${providerId}/models/${modelId}`, { method: 'DELETE' }),
  getDefaultModel: () => request<DefaultModel>('/api/settings/default-model'),
  setDefaultModel: (body: DefaultModel) =>
    request<DefaultModel>('/api/settings/default-model', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  cancelRun: (id: string) => request<{ id: string; status: string }>(`/api/agent/runs/${id}`, { method: 'DELETE' }),
  listAgentRuns: (conversationId: string) => request<AgentRun[]>(`/api/agent/conversations/${conversationId}/runs`),

  listCharacters: () => request<Character[]>('/api/characters'),
  createCharacter: (body: CharacterPayload) =>
    request<Character>('/api/characters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateCharacter: (id: string, body: CharacterPayload) =>
    request<Character>(`/api/characters/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteCharacter: (id: string) => request<void>(`/api/characters/${id}`, { method: 'DELETE' }),
  patchConversation: (id: string, characterId: string | null) =>
    request<Conversation>(`/api/conversations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_id: characterId }),
    }),

  listMemories: () => request<Memory[]>('/api/memories'),
  createMemory: (body: MemoryPayload) =>
    request<Memory>('/api/memories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateMemory: (id: string, body: MemoryPayload) =>
    request<Memory>(`/api/memories/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteMemory: (id: string) => request<void>(`/api/memories/${id}`, { method: 'DELETE' }),

  listSkills: () => request<Skill[]>('/api/skills'),
  reloadSkills: () => request<Skill[]>('/api/skills/reload', { method: 'POST' }),

  listMcp: () => request<McpServer[]>('/api/mcp'),
  connectMcp: (body: { name: string; command: string; args: string[] }) =>
    request<McpServer[]>('/api/mcp/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  disconnectMcp: (name: string) =>
    request<McpServer[]>('/api/mcp/disconnect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  listChannels: () => request<Channel[]>('/api/channels'),
  connectChannel: (channel: string, body: { ws_url: string; access_token?: string | null }) =>
    request<Channel[]>(`/api/channels/${channel}/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  disconnectChannel: (channel: string) =>
    request<Channel[]>(`/api/channels/${channel}/disconnect`, { method: 'POST' }),

  async chatStream(
    body: ChatRequest,
    onChunk: (text: string) => void,
    onStep?: (step: { type: 'step' | 'tool'; name: string; status: string; input?: unknown; output?: unknown; error?: string | null }) => void,
    signal?: AbortSignal,
    onRun?: (runId: string) => void,
  ): Promise<ChatResult> {
    const res = await fetch(`${BACKEND_URL}/api/chat/stream`, {
      method: 'POST',
      headers: await withAuth({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      signal,
    })
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try {
        const errorBody = await res.json()
        detail = errorBody.error?.message ?? errorBody.detail ?? detail
      } catch {
        /* 忽略非 JSON 响应体 */
      }
      reportApiError(detail)
      throw new Error(detail)
    }
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let result: ChatResult | null = null
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const event = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        for (const line of event.split('\n')) {
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6))
          if (data.type === 'chunk') onChunk(data.text)
          else if (data.type === 'run') onRun?.(data.run_id)
          else if (data.type === 'step' || data.type === 'tool') onStep?.(data)
          else if (data.type === 'done')
            result = {
              conversation_id: data.conversation_id,
              user_message: data.user_message,
              assistant_message: data.assistant_message,
            }
          else if (data.type === 'error') {
            reportApiError(data.detail)
            throw new Error(data.detail)
          }
        }
      }
    }
    if (!result) throw new Error('流结束但未收到 done')
    return result
  },
}
