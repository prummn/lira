import { test, expect } from '@playwright/test'

test('sign in with ChatGPT, show quota and save a subscription without an API key', async ({ page }) => {
  let account = { available: true, authenticated: false, pending: false, email: null as string|null,
    plan: null as string|null, limits: [] as object[], login_url: null as string|null }
  let profiles: object[] = []
  let signedIn = false
  await page.route('**/api/settings/profiles', async route => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      expect(body.provider_kind).toBe('codex')
      expect(body.api_key).toBeNull()
      expect(body.base_url).toBe('https://chatgpt.com')
      const saved = { ...body, id: 'codex-fixture', api_key_configured: false }
      profiles = [saved]
      await route.fulfill({ status: 201, json: saved })
    } else await route.fulfill({ json: { profiles, active_id: profiles.length ? 'codex-fixture' : null, fallback_ids: [], auto_fallback: false } })
  })
  await page.route('**/api/settings/codex', async route => {
    if (signedIn) account = { ...account, authenticated: true, pending: false, email: 'reader@example.com', plan: 'plus', login_url: null,
      limits: [{ name: 'primary', used_percent: 25, window_minutes: 300, resets_at: 1800000000 }] }
    await route.fulfill({ json: account })
  })
  await page.route('**/api/settings/codex/login', async route => {
    account = { ...account, pending: route.request().method() !== 'DELETE', login_url: 'https://auth.openai.com/authorize?fixture=1' }
    await route.fulfill({ json: account })
  })
  await page.route('**/api/settings/codex/logout', async route => {
    signedIn = false
    account = { ...account, authenticated: false, email: null, plan: null, limits: [] }
    await route.fulfill({ json: account })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('combobox', { name: '连接方式', exact: true }).selectOption('codex', { timeout: 8000 })
  await expect(page.getByRole('textbox', { name: 'API key', exact: true })).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: '模型 API 地址', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '登录 ChatGPT', exact: true }).click()
  const link = page.getByRole('link', { name: '前往官方页面登录', exact: true })
  await expect(link).toHaveAttribute('href', /^https:\/\/auth.openai.com\//)
  await expect(page.getByRole('button', { name: '取消登录', exact: true })).toBeVisible()
  signedIn = true
  await expect(page.getByText('reader@example.com', { exact: true })).toBeVisible({ timeout: 10000 })
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '25')
  await page.getByRole('textbox', { name: '配置名称', exact: true }).fill('ChatGPT subscription')
  await page.getByRole('button', { name: '仅保存', exact: true }).click()
  await expect(page.locator('.model-profile-row').filter({ hasText: 'ChatGPT subscription' })).toContainText('Codex 订阅')
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '登录 ChatGPT', exact: true })).toBeVisible()
})

test('missing CLI explains what to install and API connections remain editable', async ({ page }) => {
  await page.route('**/api/settings/profiles', route => route.fulfill({ json: { profiles: [], active_id: null, fallback_ids: [], auto_fallback: false } }))
  await page.route('**/api/settings/codex', route => route.fulfill({ json: { available: false, authenticated: false, pending: false, email: null, plan: null, limits: [], login_url: null, error: '未找到官方 Codex CLI' } }))
  await page.goto('/')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('combobox', { name: '连接方式', exact: true }).selectOption('codex', { timeout: 8000 })
  await expect(page.getByText('npm install -g @openai/codex', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '登录 ChatGPT', exact: true })).toBeDisabled()
  await page.getByRole('combobox', { name: '连接方式', exact: true }).selectOption('api')
  await expect(page.getByRole('textbox', { name: 'API key', exact: true })).toBeVisible()
})

test('a temporary account service failure offers refresh without asking for another login', async ({ page }) => {
  let recovered = false
  await page.route('**/api/settings/profiles', route => route.fulfill({ json: { profiles: [], active_id: null, fallback_ids: [], auto_fallback: false } }))
  await page.route('**/api/settings/codex', route => route.fulfill({ json: recovered
    ? { available: true, authenticated: true, pending: false, email: 'reader@example.com', plan: 'plus', limits: [], login_url: null }
    : { available: true, authenticated: false, pending: false, email: null, plan: null, limits: [], login_url: null, error: 'Codex 账户服务响应超时，请刷新后重试', error_code: 'transport_timeout', retryable: true } }))
  await page.goto('/')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('combobox', { name: '连接方式', exact: true }).selectOption('codex')
  await expect(page.getByRole('alert')).toContainText('Codex 账户服务响应超时')
  await expect(page.getByRole('button', { name: '登录 ChatGPT', exact: true })).toHaveCount(0)
  recovered = true
  await page.getByRole('button', { name: '刷新账户与额度', exact: true }).click()
  await expect(page.getByText('reader@example.com', { exact: true })).toBeVisible()
})
