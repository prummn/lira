import { expect, test } from '@playwright/test'

test('workspace scrolls inside the main content while navigation stays fixed', async ({ page }) => {
  await page.goto('/')
  const shell = page.locator('.page-wrap').first()
  await expect(shell).toBeVisible()
  await expect.poll(() => shell.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true)
  await shell.evaluate(element => { element.scrollTop = element.scrollHeight })
  await expect.poll(() => page.locator('.sidebar').evaluate(element => Math.round(element.getBoundingClientRect().top))).toBe(0)
  await expect.poll(() => page.locator('.topbar').evaluate(element => Math.round(element.getBoundingClientRect().top))).toBe(0)
  await expect.poll(() => page.evaluate(() => document.scrollingElement?.scrollTop ?? 0)).toBe(0)
})

test('modal stays centered in the current viewport while the library is scrolled', async ({ page }) => {
  await page.goto('/')
  const shell = page.locator('.page-wrap').first()
  await shell.evaluate(element => { element.scrollTop = element.scrollHeight })
  await page.locator('.heading-actions').getByRole('button', { name: '新建集合', exact: true }).click()
  const modal = page.locator('.modal')
  await expect(modal).toBeVisible()
  const box = await modal.boundingBox()
  const viewport = page.viewportSize()!
  expect(box).not.toBeNull()
  expect(Math.abs((box!.x + box!.width / 2) - viewport.width / 2)).toBeLessThan(2)
  expect(Math.abs((box!.y + box!.height / 2) - viewport.height / 2)).toBeLessThan(2)
})
