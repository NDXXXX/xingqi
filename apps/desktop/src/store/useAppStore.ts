import { create } from 'zustand'
import { api } from '../api/client'
import type { AgentStep, Channel, Character, CharacterPayload, Conversation, DefaultModel, McpServer, Memory, MemoryPayload, Message, ModelConfigPayload, ModelConfigUpdatePayload, Provider, ProviderPayload, ProviderUpdatePayload, Skill, View } from '../types'

interface AppState {
  activeView: View
  activeConversationId: string | null
  conversations: Conversation[]
  providers: Provider[]
  defaultModel: DefaultModel
  characters: Character[]
  memories: Memory[]
  skills: Skill[]
  mcpServers: McpServer[]
  channels: Channel[]
  messagesByConversation: Record<string, Message[]>
  streaming: boolean
  streamText: string
  agentSteps: AgentStep[]
  activeRunId: string | null
  error: string | null

  init: () => Promise<void>
  reloadConversations: () => Promise<void>
  setActiveView: (view: View) => void
  selectConversation: (id: string) => Promise<void>
  newConversation: () => Promise<void>
  deleteConversation: (id: string) => Promise<void>
  renameConversation: (id: string, title: string) => Promise<void>
  sendMessage: (text: string, providerId: string | null, model: string | null, regenerate?: boolean) => Promise<void>
  stopGeneration: () => void
  clearError: () => void
  createProvider: (payload: ProviderPayload) => Promise<void>
  updateProvider: (id: string, payload: ProviderUpdatePayload) => Promise<void>
  deleteProvider: (id: string) => Promise<void>
  createModel: (providerId: string, payload: ModelConfigPayload) => Promise<void>
  updateModel: (providerId: string, modelId: string, payload: ModelConfigUpdatePayload) => Promise<void>
  deleteModel: (providerId: string, modelId: string) => Promise<void>
  setDefaultModel: (value: DefaultModel) => Promise<void>
  createCharacter: (payload: CharacterPayload) => Promise<void>
  updateCharacter: (id: string, payload: CharacterPayload) => Promise<void>
  deleteCharacter: (id: string) => Promise<void>
  setConversationCharacter: (conversationId: string, characterId: string | null) => Promise<void>
  createMemory: (payload: MemoryPayload) => Promise<void>
  updateMemory: (id: string, payload: MemoryPayload) => Promise<void>
  deleteMemory: (id: string) => Promise<void>
  reloadSkills: () => Promise<void>
  connectMcp: (name: string, command: string, args: string[]) => Promise<void>
  disconnectMcp: (name: string) => Promise<void>
  connectChannel: (channel: string, wsUrl: string, accessToken?: string | null) => Promise<void>
  disconnectChannel: (channel: string) => Promise<void>
}

let activeChatController: AbortController | null = null

export const useAppStore = create<AppState>((set, get) => ({
  activeView: 'chat',
  activeConversationId: null,
  conversations: [],
  providers: [],
  defaultModel: { provider_id: null, model_id: null },
  characters: [],
  memories: [],
  skills: [],
  mcpServers: [],
  channels: [],
  messagesByConversation: {},
  streaming: false,
  streamText: '',
  agentSteps: [],
  activeRunId: null,
  error: null,

  init: async () => {
    const [conversations, providers, defaultModel, characters, memories, skills, mcpServers, channels] = await Promise.all([
      api.listConversations(),
      api.listProviders(),
      api.getDefaultModel(),
      api.listCharacters(),
      api.listMemories(),
      api.listSkills(),
      api.listMcp(),
      api.listChannels(),
    ])
    set({ conversations, providers, defaultModel, characters, memories, skills, mcpServers, channels })
  },

  reloadConversations: async () => {
    const conversations = await api.listConversations()
    const activeId = get().activeConversationId
    if (activeId && conversations.some((conversation) => conversation.id === activeId)) {
      const messages = await api.listMessages(activeId)
      set((s) => ({
        conversations,
        messagesByConversation: { ...s.messagesByConversation, [activeId]: messages },
      }))
      return
    }
    set({ conversations, activeConversationId: activeId ? null : activeId })
  },

  setActiveView: (activeView) => set({ activeView }),

  selectConversation: async (id) => {
    set({ activeConversationId: id, activeView: 'chat' })
    if (get().messagesByConversation[id] === undefined) {
      const messages = await api.listMessages(id)
      set((s) => ({ messagesByConversation: { ...s.messagesByConversation, [id]: messages } }))
    }
  },

  newConversation: async () => {
    const conversation = await api.createConversation('New Chat')
    set((s) => ({
      conversations: [conversation, ...s.conversations],
      activeConversationId: conversation.id,
      activeView: 'chat',
      messagesByConversation: { ...s.messagesByConversation, [conversation.id]: [] },
    }))
  },

  deleteConversation: async (id) => {
    await api.deleteConversation(id)
    set((s) => {
      const messagesByConversation = { ...s.messagesByConversation }
      delete messagesByConversation[id]
      return {
        conversations: s.conversations.filter((conversation) => conversation.id !== id),
        activeConversationId: s.activeConversationId === id ? null : s.activeConversationId,
        messagesByConversation,
      }
    })
  },

  renameConversation: async (id, title) => {
    const conversation = await api.renameConversation(id, title)
    set((s) => ({ conversations: s.conversations.map((item) => (item.id === id ? conversation : item)) }))
  },

  sendMessage: async (text, providerId, model, regenerate = false) => {
    const content = text.trim()
    if (!content || get().streaming) return
    let conversationId = get().activeConversationId
    if (!conversationId) {
      const conversation = await api.createConversation(content.slice(0, 30) || 'New Chat')
      conversationId = conversation.id
      set((s) => ({
        conversations: [conversation, ...s.conversations],
        activeConversationId: conversation.id,
        activeView: 'chat',
        messagesByConversation: { ...s.messagesByConversation, [conversation.id]: [] },
      }))
    }

    const tempUser: Message | null = regenerate ? null : {
      id: `tmp-${Date.now()}`,
      conversation_id: conversationId,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    set((s) => ({
      messagesByConversation: {
        ...s.messagesByConversation,
        [conversationId]: tempUser
          ? [...(s.messagesByConversation[conversationId] ?? []), tempUser]
          : s.messagesByConversation[conversationId] ?? [],
      },
      streaming: true,
      streamText: '',
      agentSteps: [],
      activeRunId: null,
      error: null,
    }))

    const controller = new AbortController()
    activeChatController = controller
    try {
      const result = await api.chatStream(
        { conversation_id: conversationId, message: content, provider_id: providerId, model, regenerate },
        (chunk) => set((s) => ({ streamText: s.streamText + chunk })),
        (step) => set((s) => ({
          agentSteps: [...s.agentSteps, {
            type: step.type,
            name: step.name,
            status: step.status as AgentStep['status'],
            input: step.input,
            output: step.output,
            error: step.error,
          }],
        })),
        controller.signal,
        (runId) => set({ activeRunId: runId }),
      )
      set((s) => ({
        messagesByConversation: {
          ...s.messagesByConversation,
          [conversationId]: [
            ...(s.messagesByConversation[conversationId] ?? []).filter(
              (m) => m.id !== tempUser?.id && m.id !== result.user_message.id && m.id !== result.assistant_message.id,
            ),
            result.user_message,
            result.assistant_message,
          ],
        },
        streaming: false,
        streamText: '',
        activeRunId: null,
      }))
      await get().reloadConversations()
    } catch (e) {
      const aborted = e instanceof DOMException && e.name === 'AbortError'
      set({
        streaming: false,
        streamText: '',
        error: aborted ? null : e instanceof Error ? e.message : String(e),
        activeRunId: null,
      })
      try {
        const messages = await api.listMessages(conversationId)
        set((s) => ({ messagesByConversation: { ...s.messagesByConversation, [conversationId]: messages } }))
      } catch {
        // 保留原始错误；BackendStatus 会单独展示服务状态。
      }
    } finally {
      if (activeChatController === controller) activeChatController = null
    }
  },

  stopGeneration: () => {
    const runId = get().activeRunId
    if (runId) void api.cancelRun(runId).catch(() => undefined)
    activeChatController?.abort()
  },

  clearError: () => set({ error: null }),

  createProvider: async (payload) => {
    const provider = await api.createProvider(payload)
    set((s) => ({ providers: [...s.providers, provider].sort((a, b) => a.name.localeCompare(b.name)) }))
  },

  updateProvider: async (id, payload) => {
    const provider = await api.updateProvider(id, payload)
    set((s) => ({ providers: s.providers.map((item) => (item.id === id ? provider : item)) }))
  },

  deleteProvider: async (id) => {
    await api.deleteProvider(id)
    set((s) => ({ providers: s.providers.filter((item) => item.id !== id) }))
  },

  createModel: async (providerId, payload) => {
    const model = await api.createModel(providerId, payload)
    set((s) => ({
      providers: s.providers.map((provider) =>
        provider.id === providerId ? { ...provider, models: [...provider.models, model] } : provider,
      ),
    }))
  },

  updateModel: async (providerId, modelId, payload) => {
    const model = await api.updateModel(providerId, modelId, payload)
    set((s) => ({
      providers: s.providers.map((provider) =>
        provider.id === providerId
          ? { ...provider, models: provider.models.map((item) => (item.id === modelId ? model : item)) }
          : provider,
      ),
    }))
  },

  deleteModel: async (providerId, modelId) => {
    await api.deleteModel(providerId, modelId)
    set((s) => ({
      providers: s.providers.map((provider) =>
        provider.id === providerId
          ? { ...provider, models: provider.models.filter((item) => item.id !== modelId) }
          : provider,
      ),
    }))
  },

  setDefaultModel: async (value) => {
    const defaultModel = await api.setDefaultModel(value)
    set({ defaultModel })
  },

  createCharacter: async (payload) => {
    const character = await api.createCharacter(payload)
    set((s) => ({ characters: [...s.characters, character] }))
  },

  updateCharacter: async (id, payload) => {
    const character = await api.updateCharacter(id, payload)
    set((s) => ({ characters: s.characters.map((c) => (c.id === id ? character : c)) }))
  },

  deleteCharacter: async (id) => {
    await api.deleteCharacter(id)
    set((s) => ({ characters: s.characters.filter((c) => c.id !== id) }))
  },

  setConversationCharacter: async (conversationId, characterId) => {
    const conversation = await api.patchConversation(conversationId, characterId)
    set((s) => ({
      conversations: s.conversations.map((c) => (c.id === conversationId ? conversation : c)),
    }))
  },

  createMemory: async (payload) => {
    const memory = await api.createMemory(payload)
    set((s) => ({ memories: [memory, ...s.memories] }))
  },

  updateMemory: async (id, payload) => {
    const memory = await api.updateMemory(id, payload)
    set((s) => ({ memories: s.memories.map((m) => (m.id === id ? memory : m)) }))
  },

  deleteMemory: async (id) => {
    await api.deleteMemory(id)
    set((s) => ({ memories: s.memories.filter((m) => m.id !== id) }))
  },

  reloadSkills: async () => {
    const skills = await api.reloadSkills()
    set({ skills })
  },

  connectMcp: async (name, command, args) => {
    const mcpServers = await api.connectMcp({ name, command, args })
    set({ mcpServers })
  },

  disconnectMcp: async (name) => {
    const mcpServers = await api.disconnectMcp(name)
    set({ mcpServers })
  },

  connectChannel: async (channel, wsUrl, accessToken) => {
    const channels = await api.connectChannel(channel, { ws_url: wsUrl, access_token: accessToken ?? null })
    set({ channels })
  },

  disconnectChannel: async (channel) => {
    const channels = await api.disconnectChannel(channel)
    set({ channels })
  },
}))
