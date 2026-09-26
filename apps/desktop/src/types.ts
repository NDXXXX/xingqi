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
  context_window: number | null
  max_output_tokens: number | null
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

export type ProviderPayload = {
  name: string
  provider_type: string
  api_key: string
  base_url?: string | null
}

export type ProviderUpdatePayload = {
  name?: string
  api_key?: string | null
  base_url?: string | null
  enabled?: boolean
}

export type ModelConfigPayload = {
  model_name: string
  display_name: string
  supports_tools?: boolean
  supports_streaming?: boolean
  enabled?: boolean
  context_window?: number | null
  max_output_tokens?: number | null
}

export type ModelConfigUpdatePayload = Partial<ModelConfigPayload>

export interface DefaultModel {
  provider_id: string | null
  model_id: string | null
}

export interface ProviderTestResult {
  ok: boolean
  detail: string
  reply?: string
}

export interface AgentStep {
  name: string
  status: 'completed' | 'running' | 'failed'
  type?: 'step' | 'tool'
  input?: unknown
  output?: unknown
  error?: string | null
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
  identity_id: string | null
  shared: boolean
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
  shared?: boolean
}

export interface Skill {
  name: string
  description: string
  content: string
  path: string
}

export interface McpServer {
  name: string
  command: string
  args: string[]
  connected: boolean
  tools: string[]
}

export interface Channel {
  channel: string
  connected: boolean
  status: 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'error'
  last_connected_at: string | null
  last_disconnected_at: string | null
  last_error: string | null
  retry_count: number
}

export interface AgentRunStepRecord {
  id: string
  step_type: 'step' | 'tool'
  name: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  input_json: string | null
  output_json: string | null
  started_at: string
  finished_at: string | null
  error: string | null
}

export interface AgentRun {
  id: string
  conversation_id: string
  provider_id: string
  model_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  started_at: string
  finished_at: string | null
  duration_ms: number | null
  prompt_tokens: number | null
  completion_tokens: number | null
  error: string | null
  steps: AgentRunStepRecord[]
}
