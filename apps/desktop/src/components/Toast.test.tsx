import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import Toast from './Toast'

describe('Toast', () => {
  it('shows API errors and dismisses them automatically', () => {
    vi.useFakeTimers()
    render(<Toast />)

    act(() => {
      window.dispatchEvent(new CustomEvent('companion:api-error', { detail: '连接失败' }))
    })
    expect(screen.getByRole('alert')).toHaveTextContent('连接失败')

    act(() => vi.advanceTimersByTime(5000))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    vi.useRealTimers()
  })
})
