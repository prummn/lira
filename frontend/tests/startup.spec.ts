import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    return route.fulfill({ json: path === '/api/papers' ? { items: [], total: 0 }
      : path === '/api/collections' ? { items: [] } : null })
  })
})

test('a delayed entry module keeps a visible startup screen, then opens the workspace', async ({ page }) => {
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  await page.route('**/src/main.tsx*', async route => { await held; await route.continue() })
  try {
    await page.goto('/', { waitUntil: 'commit' })
    await expect(page.locator('#lira-startup')).toBeVisible()
    await expect(page.locator('#lira-startup')).toContainText('正在打开文献库')
    await expect(page.locator('.sidebar')).toHaveCount(0)
  } finally { release() }
  await expect(page.locator('.sidebar')).toBeVisible()
  await expect(page.locator('#lira-startup')).toBeHidden()
})

test('a failed entry script offers retry and the retry can recover', async ({ page }) => {
  const abort = (route: import('@playwright/test').Route) => route.abort()
  await page.route('**/src/main.tsx*', abort)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#lira-startup')).toContainText('页面未能打开')
  const retry = page.locator('#lira-startup').getByRole('button', { name: '重新打开' })
  await expect(retry).toBeVisible()
  await page.unroute('**/src/main.tsx*', abort)
  await retry.click()
  await expect(page.locator('.sidebar')).toBeVisible()
  await expect(page.locator('#lira-startup')).toBeHidden()
})

test('an initial render error shows recovery instead of a white page', async ({ page }) => {
  await page.addInitScript(() => { crypto.randomUUID = () => { throw new Error('startup render fixture') } })
  await page.goto('/')
  await expect(page.locator('#lira-startup')).toContainText('页面未能打开')
  await expect(page.locator('#lira-startup').getByRole('button', { name: '重新打开' })).toBeVisible()
})

test('a slow library request leaves navigation and loading feedback available', async ({ page }) => {
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/papers?*', async route => { await held; await route.fulfill({ json: { items: [], total: 0 } }) })
  try {
    await page.goto('/')
    await expect(page.locator('.sidebar')).toBeVisible()
    await expect(page.getByText('正在读取本地文献库…')).toBeVisible()
    await expect(page.locator('#lira-startup')).toBeHidden()
  } finally { release() }
})
