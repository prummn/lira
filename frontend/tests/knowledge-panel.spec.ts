import { expect, test } from '@playwright/test'

test('reader exposes a reviewable Knowledge panel without leaving the PDF', async ({ page, request }) => {
  const imported = await request.post('/api/papers', { data: { title: 'Knowledge panel fixture', abstract: 'A local fixture for the knowledge panel.' } })
  expect(imported.ok()).toBeTruthy()
  const paper = await imported.json()
  await page.goto('/')
  await page.locator('.paper-row').filter({ hasText: paper.title }).getByRole('button', { name: paper.title, exact: true }).click()
  await expect(page.locator('.pdf-panel')).toBeVisible()
  await page.locator('.notebook-panel').getByRole('button', { name: '知识摄取', exact: true }).click()
  await expect(page.locator('.knowledge-panel')).toBeVisible()
  await expect(page.locator('.knowledge-panel')).toContainText(/还没有知识候选|No knowledge candidates yet/)
})
