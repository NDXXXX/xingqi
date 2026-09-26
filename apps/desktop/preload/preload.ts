import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('api', {
  getBackendHealth: () => ipcRenderer.invoke('backend:health'),
})
