export type View =
  | 'chat'
  | 'characters'
  | 'memory'
  | 'skills'
  | 'mcp'
  | 'channels'
  | 'settings'

export interface Message {
  id: string
  conversation_id: string
  role: string
  content: string
  created_at: string
}

export interface Conversation {
  id: string
  title: string
  character_id: string | null
  channel: string
  external_user_id: string | null
  model_id: string | null
  created_at: string
  updated_at: string
}

export interface ModelConfig {
  id: string
  model_name: string
  display_name: string
  supports_tools: boolean
  supports_streaming: boolean
  enabled: boolean
}

export interface Provider {
  id: string
  name: string
  provider_type: string
  base_url: string | null
  enabled: boolean
  configured: boolean
  models: ModelConfig[]
}

export interface AgentStep {
  name: string
  status: 'done' | 'running'
}

export interface Character {
  id: string
  name: string
  avatar: string | null
  description: string | null
  personality: string | null
  background: string | null
  speaking_style: string | null
  system_prompt: string | null
  default_model_id: string | null
  created_at: string
  updated_at: string
}

export type CharacterPayload = {
  name: string
  avatar?: string | null
  description?: string | null
  personality?: string | null
  background?: string | null
  speaking_style?: string | null
  system_prompt?: string | null
  default_model_id?: string | null
}

export interface Memory {
  id: string
  user_id: string | null
  type: string
  content: string
  importance: number
  created_at: string
  updated_at: string
}

export type MemoryPayload = {
  type: string
  content: string
  importance?: number
}

export interface Skill {
  name: string
  description: string
  content: string
  path: string
}
