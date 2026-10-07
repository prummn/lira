import { test, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

const fixtures = process.env.RIW_REAL_PAPER_FIXTURES
test.skip(!fixtures, 'Opt-in real downloads: set RIW_REAL_PAPER_FIXTURES to the acquired official fixture directory.')

test('official arXiv URL and three actual PDFs have accurate metadata and usable evidence', async ({ page, request }) => {
  test.setTimeout(180000)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const manifest = JSON.parse(await readFile(path.join(fixtures!, 'manifest.json'), 'utf8'))
  const results: object[] = []
  await page.goto('/')
  await page.getByRole('button', { name: '链接导入', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '通过链接导入论文' })
  await dialog.getByRole('textbox', { name: '论文链接', exact: true }).fill('https://arxiv.org/abs/1706.03762')
  await dialog.getByRole('button', { name: '下载并导入', exact: true }).click()
  await expect(dialog).toContainText('Attention Is All You Need', { timeout: 90000 })
  await page.screenshot({ path: 'test-artifacts/real-attention-link-import.png' })
  await dialog.getByRole('button', { name: '关闭', exact: true }).first().click()
  for (const fixture of manifest.papers) {
    const expected = fixture.authoritative_metadata
    if (fixture.arxiv_id !== '1706.03762') {
      await page.locator('input[type=file]').setInputFiles(path.join(fixtures!, fixture.pdf.artifact.local_file))
      await page.getByRole('dialog',{name:'确认批量导入'}).getByRole('button',{name:'开始导入',exact:true}).click()
      await expect(page.locator('.import-ok')).toContainText(fixture.pdf.artifact.local_file, { timeout: 60000 })
    }
    const row = page.locator('.paper-row').filter({ hasText: expected.title })
    await expect(row).toBeVisible()
    await expect(row.locator('.paper-year')).toHaveText(String(expected.original_year))
    const library = await (await request.get('/api/papers')).json()
    const summary = library.items.find((paper: { arxiv_id: string }) => paper.arxiv_id === fixture.arxiv_id)
    expect(summary.title).toBe(expected.title)
    expect(summary.authors).toEqual(expected.ordered_authors)
    const detail = await (await request.get(`/api/papers/${summary.id}`)).json()
    expect(detail.abstract).toBeTruthy()
    expect(detail.abstract.length).toBeGreaterThan(300)
    expect(detail.abstract).not.toContain('Provided proper attribution')
    expect(detail.metadata_sources.title).toBe('arxiv')
    expect(detail.chunks.some((chunk: { section: string | null }) => chunk.section && /architecture|bert|low.rank|adaptation/i.test(chunk.section))).toBe(true)
    expect(detail.analysis.card.method).toBeTruthy()
    expect(detail.analysis.card.main_results).toBeTruthy()
    if (fixture.arxiv_id === '1810.04805') {
      const training = detail.chunks.find((chunk: { content: string }) => chunk.content.startsWith('Pre-training data'))
      expect(training.section).toBe('3.1 Pre-training BERT')
      expect(detail.analysis.card.main_results.content).toContain('11 NLP tasks')
      expect(detail.analysis.card.main_results.content).not.toContain('BooksCorpus')
    }
    results.push({ arxiv_id: summary.arxiv_id, title: detail.title, authors: detail.authors, year: detail.year,
      venue: detail.venue, sources: detail.metadata_sources, warnings: detail.metadata_warnings,
      abstract_chars: detail.abstract.length, chunks: detail.chunks.length, evidence: detail.evidence.length,
      method: detail.analysis.card.method.content, findings: detail.analysis.card.main_results.content, source_url: detail.source_url })
    await row.locator('.paper-name > button').click()
    await expect(page.locator('.pdfv-canvas')).toBeVisible()
    await page.getByRole('button', { name: '原文证据', exact: true }).click()
    await expect(page.locator('.evidence-item')).not.toHaveCount(0)
    await page.locator('.evidence-item').first().getByRole('button', { name: /定位原文/ }).click()
    await expect(page.locator('.pdfv-evidence-overlay')).toBeVisible()
    await page.screenshot({ path: `test-artifacts/real-${fixture.arxiv_id}-reader.png` })
    await page.getByRole('button', { name: '返回文献库', exact: true }).click()
  }
  await page.screenshot({ path: 'test-artifacts/real-paper-library.png', fullPage: true })
  const duplicate = await request.post('/api/papers/import-url', { data: { url: 'https://arxiv.org/pdf/1706.03762' }, timeout: 60000 })
  expect(duplicate.status()).toBe(409)
  await writeFile('test-artifacts/real-paper-validation.json', JSON.stringify({ results, duplicate_direct_pdf: duplicate.status(), browser_errors: errors }, null, 2))
  expect(errors).toEqual([])
})
