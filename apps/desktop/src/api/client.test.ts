import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('chatStream', () => {
  it('parses run, step, text and done events', async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"run","run_id":"run-1"}\n\n'))
        controller.enqueue(encoder.encode('data: {"type":"step","name":"call_llm","status":"completed"}\n\n'))
        controller.enqueue(encoder.encode('data: {"type":"chunk","text":"你"}\n\n'))
        controller.enqueue(encoder.encode('data: {"type":"chunk","text":"好"}\n\n'))
        controller.enqueue(encoder.encode('data: {"type":"done","conversation_id":"c1","user_message":{"id":"u1"},"assistant_message":{"id":"a1"}}\n\n'))
        controller.close()
      },
    })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(stream, { status: 200 }))
    const chunks: string[] = []
    const steps: string[] = []
    let runId = ''

    const result = await api.chatStream(
      { conversation_id: 'c1', message: 'hi', provider_id: 'p1', model: 'm1' },
      (chunk) => chunks.push(chunk),
      (step) => steps.push(step.name),
      undefined,
      (id) => { runId = id },
    )

    expect(runId).toBe('run-1')
    expect(chunks).toEqual(['你', '好'])
    expect(steps).toEqual(['call_llm'])
    expect(result.conversation_id).toBe('c1')
  })

  it('reads the standard API error response', async () => {
    const listener = vi.fn()
    window.addEventListener('companion:api-error', listener)
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({ error: { message: '配置无效' } }),
      { status: 400, headers: { 'Content-Type': 'application/json' } },
    ))

    await expect(api.listProviders()).rejects.toThrow('配置无效')
    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener('companion:api-error', listener)
  })
})
