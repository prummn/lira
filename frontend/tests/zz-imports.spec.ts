import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

test('link import reports download errors, imports a PDF, and opens the reader', async ({ page, request }) => {
  const bytes = Buffer.concat([await readFile(path.resolve('test-artifacts/import-fixture.pdf')), Buffer.from('\n% URL browser fixture\n')])
  await page.route('**/api/papers/import-url', async route => {
    const { url } = route.request().postDataJSON()
    if (url.includes('missing')) {
      await route.fulfill({ status: 422, json: { detail: '链接未返回 PDF，请使用论文 PDF 链接。' } })
      return
    }
    const response = await request.post('/api/papers/import', {
      multipart: { file: { name: 'url-import.pdf', mimeType: 'application/pdf', buffer: bytes } },
    })
    await route.fulfill({ status: response.status(), json: await response.json() })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '链接导入', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '通过链接导入论文' })
  await dialog.getByRole('textbox', { name: '论文链接', exact: true }).fill('https://example.org/missing.pdf')
  await dialog.getByRole('button', { name: '下载并导入', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('链接未返回 PDF')
  await expect(dialog.getByRole('textbox', { name: '论文链接', exact: true })).toHaveValue('https://example.org/missing.pdf')
  await dialog.getByRole('textbox', { name: '论文链接', exact: true }).fill('https://example.org/paper.pdf')
  await dialog.getByRole('button', { name: '下载并导入', exact: true }).click()
  await expect(dialog).toContainText('Evidence Integration Test')
  await dialog.getByRole('button', { name: '打开论文', exact: true }).click()
  await expect(page.locator('.pdfv-canvas').first()).toBeVisible()
})

test('metadata edits and refresh preserve favorite, reading state and notes', async ({ page, request }) => {
  await page.goto('/')
  const row = page.locator('.paper-row').first()
  const title = await row.locator('.paper-name > button').innerText()
  const papers = await (await request.get('/api/papers')).json()
  const paper = papers.items.find((item: { title: string }) => item.title === title)
  await request.patch(`/api/papers/${paper.id}`, { data: { is_favorite: true, reading_status: 'reading' } })
  await request.post(`/api/papers/${paper.id}/notes`, { data: { content: 'Metadata refresh must preserve this note.' } })
  await row.getByRole('button', { name: `${title} 论文信息`, exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '论文信息', exact: true })
  await dialog.getByRole('textbox', { name: '标题', exact: true }).fill('Manually corrected research title')
  await dialog.getByRole('textbox', { name: '作者（每行一位，按署名顺序）', exact: true }).fill('First Researcher\nSecond Researcher')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  const updated = page.locator('.paper-row').filter({ hasText: 'Manually corrected research title' })
  await expect(updated).toContainText('First Researcher, Second Researcher')
  await updated.getByRole('button', { name: 'Manually corrected research title 论文信息', exact: true }).click()
  await page.getByRole('button', { name: '重新识别', exact: true }).click()
  await expect(dialog).toContainText('识别完成')
  await expect(dialog.getByRole('textbox', { name: '标题', exact: true })).toHaveValue('Manually corrected research title')
  const detail = await (await request.get(`/api/papers/${paper.id}`)).json()
  expect(detail.authors).toEqual(['First Researcher', 'Second Researcher'])
  expect(detail.is_favorite).toBe(true)
  expect(detail.reading_status).toBe('reading')
  expect(detail.notes.some((item: { content: string }) => item.content.includes('preserve this note'))).toBe(true)
})

test('a failed collection update can be retried without downloading the paper again', async ({ page, request }) => {
  const collection = await (await request.post('/api/collections', { data: { name: 'Link import recovery', color: '#336c61' } })).json()
  const bytes = Buffer.concat([await readFile(path.resolve('test-artifacts/import-fixture.pdf')), Buffer.from('\n% Collection recovery fixture\n')])
  let imports = 0
  let memberships = 0
  await page.route('**/api/papers/import-url', async route => {
    imports++
    const response = await request.post('/api/papers/import', { multipart: { file: { name: 'collection-link.pdf', mimeType: 'application/pdf', buffer: bytes } } })
    await route.fulfill({ status: response.status(), json: await response.json() })
  })
  await page.route(`**/api/collections/${collection.id}/papers/*`, async route => {
    memberships++
    if (memberships === 1) await route.fulfill({ status: 502, json: { detail: '集合更新暂时失败' } })
    else {
      const response = await request.put(route.request().url())
      await route.fulfill({ status: response.status(), body: await response.body() })
    }
  })
  await page.goto('/')
  await page.locator('.collection-nav').getByRole('button', { name: 'Link import recovery', exact: true }).click()
  await page.getByRole('button', { name: '链接导入', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '通过链接导入论文' })
  await dialog.getByRole('textbox', { name: '论文链接', exact: true }).fill('https://example.org/collection-paper.pdf')
  await dialog.getByRole('button', { name: '下载并导入', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('集合更新暂时失败')
  await expect(dialog).toContainText('论文已保存')
  await dialog.getByRole('button', { name: '重试加入集合', exact: true }).click()
  await expect(dialog).toContainText('导入完成')
  expect(imports).toBe(1)
  expect(memberships).toBe(2)
  const papers = await (await request.get('/api/papers')).json()
  expect(papers.items.some((paper: { collection_ids: string[] }) => paper.collection_ids.includes(collection.id))).toBe(true)
})
