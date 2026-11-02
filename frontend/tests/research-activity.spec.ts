import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'

const dateKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`
async function activityFixture(page: Page) {
  const scenarios = [
    { language: 1 }, { language: 15 }, { language: 150 },
    { reading: 1, notes: 1 }, { reading: 3, notes: 5 }, { reading: 6, notes: 12 },
    { imports: 500 }, { reading: 2, notes: 4, language: 38, search: 3, imports: 1 },
  ]
  const today = new Date()
  const days = scenarios.map((counts, index) => {
    const date = new Date(today); date.setDate(date.getDate()-index)
    const day = { date: dateKey(date), reading: 0, notes: 0, language: 0, search: 0, imports: 0, paper_ids: [], ...counts }
    return { ...day, total: day.reading+day.notes+day.language+day.search+day.imports }
  }).reverse()
  await page.route('**/api/activity?*',route=>route.fulfill({json:{ days, total: days.reduce((sum,d)=>sum+d.total,0), streak:8, active_days_30:8 }}))
  await page.goto('/')
  await expect(page.locator('.research-activity-grid')).toBeVisible()
  const cell = (ago: number, locale = 'zh-CN') => page.getByTestId('research-activity-day').filter({hasText: new Intl.DateTimeFormat(locale,{year:'numeric',month:'short',day:'numeric'}).format(new Date(today.getFullYear(),today.getMonth(),today.getDate()-ago))})
  return { cell }
}

test('frequent translations and bulk imports stay light while reading and notes build intensity', async ({ page }) => {
  const { cell } = await activityFixture(page)
  for (const index of [0,1,2,6]) await expect(cell(index)).toHaveClass(/activity-level-1\b/)
  await expect(cell(3)).toHaveClass(/activity-level-2\b/)
  await expect(cell(4)).toHaveClass(/activity-level-3\b/)
  await expect(cell(5)).toHaveClass(/activity-level-4\b/)
  await expect(page.locator('.research-activity-stats').last()).toContainText('阅读记录')
})

test('day previews show original counts, support focus and Escape, and stay within the screen', async ({ page }) => {
  const { cell } = await activityFixture(page)
  const target = cell(7)
  await expect(target).not.toHaveAttribute('title')
  await target.hover()
  const preview = page.getByRole('tooltip')
  await expect(preview).toBeVisible()
  await expect(preview.locator('[data-kind="reading"]')).toContainText('2')
  await expect(preview.locator('[data-kind="notes"]')).toContainText('4')
  await expect(preview.locator('[data-kind="language"]')).toContainText('38')
  await expect(preview.locator('[data-kind="search"]')).toContainText('3')
  await expect(preview.locator('[data-kind="imports"]')).toContainText('1')
  const color = await preview.evaluate(el=>getComputedStyle(el).backgroundColor)
  expect(color).not.toBe('rgb(255, 255, 255)')
  await preview.hover()
  await page.waitForTimeout(200)
  await expect(preview).toBeVisible()
  await page.screenshot({path:'test-artifacts/research-activity-preview-light.png',animations:'disabled'})
  await page.keyboard.press('Escape')
  await expect(preview).not.toBeVisible()
  await target.focus()
  await expect(preview).toBeVisible()
  await expect(target).toHaveAttribute('aria-describedby',await preview.getAttribute('id')??'')
  await target.hover()
  await page.mouse.move(20,20)
  await page.waitForTimeout(200)
  await expect(preview).toBeVisible()
  await target.hover()
  await target.evaluate(el => el.blur())
  await page.waitForTimeout(200)
  await expect(preview).toBeVisible()
  await page.mouse.move(20,20)
  await expect(preview).not.toBeVisible()
  await target.focus()
  await expect(preview).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(preview).not.toBeVisible()

  await page.setViewportSize({width:1080,height:800})
  await page.locator('html').evaluate(el=>el.classList.add('theme-dark'))
  await cell(0).hover()
  await expect(preview).toBeInViewport({ratio:1})
  await page.screenshot({path:'test-artifacts/research-activity-preview-dark.png',animations:'disabled'})
  await page.locator('.research-activity-scroll').evaluate(el=>{el.scrollLeft=el.scrollWidth})
  await cell(2).focus()
  await expect(preview).toBeInViewport({ratio:1})
  await page.keyboard.press('Escape')
  await cell(20).focus()
  await expect(preview).toContainText('没有研究记录')
  await page.setViewportSize({width:390,height:650})
  await cell(0).focus()
  await expect(preview).toBeInViewport({ratio:1})
  await page.screenshot({path:'test-artifacts/research-activity-preview-mobile.png',animations:'disabled'})
  await page.evaluate(()=>localStorage.setItem('riw-language','en-US'))
  await page.reload()
  await cell(7,'en-US').hover()
  await expect(preview).toContainText('Reading')
  await expect(preview).toBeInViewport({ratio:1})
})

test('day preview content remains reachable in a short viewport', async ({ page }) => {
  await page.setViewportSize({width:390,height:200})
  const { cell } = await activityFixture(page)
  await cell(7).focus()
  const preview = page.getByRole('tooltip')
  await expect(preview).toBeInViewport({ratio:1})
  const content = preview.locator('.activity-preview-content')
  await expect(content).toBeVisible()
  expect(await content.evaluate(el => el.scrollHeight)).toBeGreaterThan(await content.evaluate(el => el.clientHeight))
  await page.keyboard.press('End')
  await expect.poll(() => content.evaluate(el => el.scrollTop)).toBeGreaterThan(0)
  await expect(content.locator('footer')).toBeInViewport({ratio:1})
})

test('research activity heatmap exposes levels and filters the library by day', async ({ page, request }) => {
  const papers = await (await request.get('/api/papers?limit=200')).json()
  const paper = papers.items[0]
  expect(paper).toBeTruthy()
  const response = await request.post('/api/activity', { data: { kind: 'reading', paper_id: paper.id } })
  expect(response.status()).toBe(201)

  await page.goto('/')
  await expect(page.locator('.research-activity')).toBeVisible()
  await expect(page.locator('[data-testid="research-activity-day"]')).toHaveCount(371)
  const activeDay = page.locator('[data-testid="research-activity-day"]:not(.activity-level-0)')
  await expect(activeDay).not.toHaveCount(0)

  const before = await page.locator('.paper-row').count()
  await activeDay.first().click()
  await expect(page.locator('.activity-clear')).toBeVisible()
  await expect(page.locator('.research-activity-selection')).toBeVisible()
  const filtered = await page.locator('.paper-row').count()
  expect(filtered).toBeGreaterThan(0)
  expect(filtered).toBeLessThanOrEqual(before)
  expect(before).toBeGreaterThan(1)
  await page.getByRole('button', { name: /清除日期筛选|Clear date filter/ }).click()
  await expect(page.locator('.paper-row')).toHaveCount(before)
})
