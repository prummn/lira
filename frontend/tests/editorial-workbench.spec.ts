import { expect, test } from '@playwright/test'

test('library focuses a paper and exposes next actions without dashboard chrome', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.library-toolbar')).toBeVisible()
  await expect(page.locator('.paper-table')).toBeVisible()
  await expect(page.locator('.library-selection-detail')).toHaveCount(0)
  await page.locator('.paper-name > button').first().click()
  await expect(page.locator('.library-selection-detail')).toBeVisible()
  await expect(page.getByRole('button', { name: '打开阅读器', exact: true })).toBeVisible()
})

test('librarian keeps its scope and composer visible after returning from a source', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'AI 文献员', exact: true }).click()
  await expect(page.locator('.librarian-scope-panel')).toBeVisible()
  await expect(page.locator('.librarian-composer')).toBeVisible()
})
