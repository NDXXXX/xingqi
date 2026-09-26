/// <reference types="vite/client" />

interface BackendHealth {
  ok: boolean
  detail: string
}

interface Window {
  api: {
    getBackendHealth: () => Promise<BackendHealth>
    getBackendToken: () => Promise<string>
  }
}
