import { _electron as electron, expect, test } from '@playwright/test'
import { mkdtemp, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

test('launches Electron, reaches the backend, and restores a conversation', async () => {
  const dataDir = await mkdtemp(path.join(os.tmpdir(), 'companion-e2e-'))
  const appDir = path.resolve(__dirname, '..')
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      ([key, value]) => key !== 'ELECTRON_RUN_AS_NODE' && value !== undefined,
    ),
  ) as Record<string, string>
  env.COMPANION_E2E_DATA_DIR = dataDir

  const launch = () => electron.launch({ args: [appDir], env })
  let app = await launch()
  try {
    let page = await app.firstWindow()
    await expect(page.getByRole('heading', { name: 'Desktop AI Companion' })).toBeVisible()
    await expect(page.getByText('Backend ok')).toBeVisible({ timeout: 30_000 })
    await page.getByRole('button', { name: 'New Chat' }).click()
    await expect(page.locator('aside').first().getByText('New Chat')).toHaveCount(2)

    await app.close()
    app = await launch()
    page = await app.firstWindow()
    await expect(page.getByText('Backend ok')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('aside').first().getByText('New Chat')).toHaveCount(2)
  } finally {
    await app.close().catch(() => undefined)
    await rm(dataDir, { recursive: true, force: true })
  }
})
