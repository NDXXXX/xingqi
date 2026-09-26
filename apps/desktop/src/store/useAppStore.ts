import { create } from 'zustand'
import { api } from '../api/client'
import type { AgentStep, Conversation, Message, Provider, View } from '../types'

interface AppState {
  activeView: View
  activeConversationId: string | null
  conversations: Conversation[]
  providers: Provider[]
  messagesByConversation: Record<string, Message[]>
  streaming: boolean
  streamText: string
  agentSteps: AgentStep[]
  error: string | null

  init: () => Promise<void>
  reloadConversations: () => Promise<void>
  setActiveView: (view: View) => void
  selectConversation: (id: string) => Promise<void>
  newConversation: () => Promise<void>
  sendMessage: (text: string, providerId: string | null, model: string | null) => Promise<void>
  clearError: () => void
}

export const useAppStore = create<AppState>((set, get) => ({
  activeView: 'chat',
  activeConversationId: null,
  conversations: [],
  providers: [],
  messagesByConversation: {},
  streaming: false,
  streamText: '',
  agentSteps: [],
  error: null,

  init: async () => {
    const [conversations, providers] = await Promise.all([api.listConversations(), api.listProviders()])
    set({ conversations, providers })
  },

  reloadConversations: async () => {
    const conversations = await api.listConversations()
    set({ conversations })
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

  sendMessage: async (text, providerId, model) => {
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

    const tempUser: Message = {
      id: `tmp-${Date.now()}`,
      conversation_id: conversationId,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    set((s) => ({
      messagesByConversation: {
        ...s.messagesByConversation,
        [conversationId]: [...(s.messagesByConversation[conversationId] ?? []), tempUser],
      },
      streaming: true,
      streamText: '',
      agentSteps: [],
      error: null,
    }))

    try {
      const result = await api.chatStream(
        { conversation_id: conversationId, message: content, provider_id: providerId, model },
        (chunk) => set((s) => ({ streamText: s.streamText + chunk })),
        (step) => set((s) => ({ agentSteps: [...s.agentSteps, { name: step.name, status: step.status as AgentStep['status'] }] })),
      )
      set((s) => ({
        messagesByConversation: {
          ...s.messagesByConversation,
          [conversationId]: [
            ...(s.messagesByConversation[conversationId] ?? []).filter((m) => m.id !== tempUser.id),
            result.user_message,
            result.assistant_message,
          ],
        },
        streaming: false,
        streamText: '',
      }))
      await get().reloadConversations()
    } catch (e) {
      set({ streaming: false, streamText: '', error: e instanceof Error ? e.message : String(e) })
    }
  },

  clearError: () => set({ error: null }),
}))
