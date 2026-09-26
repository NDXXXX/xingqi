import type { Character, CharacterPayload, Conversation, Memory, MemoryPayload, Message, Provider, Skill } from '../types'

const BACKEND_URL = 'http://127.0.0.1:8001'

export interface ChatRequest {
  conversation_id: string | null
  message: string
  provider_id: string | null
  model: string | null
}

export interface ChatResult {
  conversation_id: string
  user_message: Message
  assistant_message: Message
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, init)
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* 忽略非 JSON 响应体 */
    }
    throw new Error(detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; service: string }>('/api/health'),
  listConversations: () => request<Conversation[]>('/api/conversations'),
  createConversation: (title: string) =>
    request<Conversation>('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, channel: 'desktop' }),
    }),
  listMessages: (conversationId: string) =>
    request<Message[]>(`/api/conversations/${conversationId}/messages`),
  listProviders: () => request<Provider[]>('/api/providers'),

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

  async chatStream(
    body: ChatRequest,
    onChunk: (text: string) => void,
    onStep?: (step: { name: string; status: string }) => void,
  ): Promise<ChatResult> {
    const res = await fetch(`${BACKEND_URL}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try {
        detail = (await res.json()).detail ?? detail
      } catch {
        /* 忽略非 JSON 响应体 */
      }
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
          else if (data.type === 'step') onStep?.({ name: data.name, status: data.status })
          else if (data.type === 'done')
            result = {
              conversation_id: data.conversation_id,
              user_message: data.user_message,
              assistant_message: data.assistant_message,
            }
          else if (data.type === 'error') throw new Error(data.detail)
        }
      }
    }
    if (!result) throw new Error('流结束但未收到 done')
    return result
  },
}
