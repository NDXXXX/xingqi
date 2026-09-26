import { useEffect, useState } from 'react'

export default function Toast() {
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    let timer: number | undefined
    const show = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail
      setMessage(detail)
      if (timer !== undefined) window.clearTimeout(timer)
      timer = window.setTimeout(() => setMessage(null), 5000)
    }
    window.addEventListener('companion:api-error', show)
    return () => {
      window.removeEventListener('companion:api-error', show)
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [])

  if (!message) return null
  return (
    <div role="alert" aria-live="assertive" className="fixed bottom-4 right-4 z-[70] flex max-w-sm items-start gap-3 rounded-lg border border-red-900 bg-red-950 px-4 py-3 text-sm text-red-100 shadow-xl">
      <span>{message}</span>
      <button type="button" onClick={() => setMessage(null)} aria-label="关闭错误提示" className="rounded px-1 text-red-300 hover:bg-red-900">×</button>
    </div>
  )
}
