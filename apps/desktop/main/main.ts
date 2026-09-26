import { app, BrowserWindow, ipcMain } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const SERVER_PORT = process.env.SERVER_PORT ?? '8001'
const BACKEND_URL = `http://127.0.0.1:${SERVER_PORT}`

let backendProcess: ChildProcess | null = null
let mainWindow: BrowserWindow | null = null

// 开发态 app.getAppPath() 为 apps/desktop，后端位于 apps/server。
function serverDir(): string {
  return path.resolve(app.getAppPath(), '..', 'server')
}

function backendPython(): string {
  const venvPython = path.join(serverDir(), '.venv', 'bin', 'python')
  if (fs.existsSync(venvPython)) return venvPython
  return 'python3'
}

function startBackend(): void {
  const cwd = serverDir()
  backendProcess = spawn(backendPython(), ['main.py'], {
    cwd,
    env: { ...process.env, SERVER_PORT },
    stdio: 'pipe',
  })
  backendProcess.stdout?.on('data', (d) => console.log('[backend]', d.toString().trimEnd()))
  backendProcess.stderr?.on('data', (d) => console.error('[backend]', d.toString().trimEnd()))
  backendProcess.on('exit', (code) => console.log(`[backend] exited with code ${code}`))
}

function stopBackend(): void {
  backendProcess?.kill()
  backendProcess = null
}

async function checkBackendHealth(): Promise<{ ok: boolean; detail: string }> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/health`)
    return { ok: res.ok, detail: String(res.status) }
  } catch {
    return { ok: false, detail: 'unreachable' }
  }
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(app.getAppPath(), 'out', 'preload', 'index.js'),
    },
  })

  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(path.join(app.getAppPath(), 'out', 'renderer', 'index.html'))
  }
}

app.whenReady().then(() => {
  startBackend()
  ipcMain.handle('backend:health', checkBackendHealth)
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('will-quit', stopBackend)
