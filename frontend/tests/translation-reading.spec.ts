import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

async function openPaper(page: Page) {
  const response = await page.request.post('/api/papers/import', { multipart: { file: {
    name: 'translation-reading.pdf', mimeType: 'application/pdf',
    buffer: Buffer.concat([await fs.readFile(path.resolve('test-artifacts/import-fixture.pdf')), Buffer.from(`\n% reading-${Date.now()}\n`)]),
  } } })
  expect(response.status()).toBe(201)
  const paper = await response.json()
  paper.title = `Translation Reading ${Date.now()}`
  await page.request.patch(`/api/papers/${paper.id}`, {data:{title:paper.title}})
  const reading = await (await page.request.get(`/api/papers/${paper.id}/reading-paragraphs`)).json()
  await page.route('**/api/settings', route => route.fulfill({ json: { provider: 'Fixture', configured: true, mode: 'remote', translation_available: true } }))
  await page.goto('/')
  await page.locator('.paper-row').filter({ hasText: paper.title }).first().locator('.paper-name > button').click()
  await expect(page.locator('.pdfv-canvas').first()).toBeVisible()
  return { paper, reading }
}

test('PDF stays typeset while hovering a paragraph reveals translation actions', async ({ page }) => {
  const { paper } = await openPaper(page)
  let calls = 0
  await page.route(`**/api/papers/${paper.id}/translate`, route => {
    calls++
    expect(route.request().postDataJSON().paragraph_id).toBeTruthy()
    return route.fulfill({ json: { text: '注意力可以写作 $QK^T$，并保留原文中的引用 [12]。', provider: 'Fixture', cached: false } })
  })
  await page.getByRole('button', { name: '中英对照', exact: true }).click()
  await expect(page.locator('.pdfv-canvas').first()).toBeVisible()
  expect(calls).toBe(0)
  const paragraph = page.locator('.pdfv-paragraph-marker').first()
  await expect(paragraph).toBeVisible()
  const box = await paragraph.boundingBox()
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)
  await expect(page.locator('.pdfv-paragraph-actions')).toBeVisible()
  await page.locator('.pdfv-paragraph-actions').getByRole('button', { name: '翻译此段', exact: true }).click()
  await expect(page.locator('.translated-text')).toContainText('注意力')
  await expect(page.locator('.translated-text .katex')).toBeVisible()
  await expect(page.locator('.pdfv-canvas').first()).toBeVisible()
  await page.screenshot({path:'test-artifacts/translation-side-1440.png'})
  await page.getByRole('button', { name: '译文放在下方', exact: true }).click()
  await expect(page.locator('.reader-layout')).toHaveClass(/translation-bottom/)
  await page.screenshot({path:'test-artifacts/translation-bottom-1440.png'})
  await page.getByRole('button', { name: '收起译文', exact: true }).click()
  await expect(page.locator('.translated-text')).toHaveCount(0)
  const resizedBox = await paragraph.boundingBox()
  await page.mouse.move(resizedBox!.x + resizedBox!.width / 2, resizedBox!.y + resizedBox!.height / 2)
  await page.locator('.pdfv-paragraph-actions').getByRole('button', { name: '展开译文', exact: true }).click()
  await expect(page.locator('.translated-text')).toContainText('引用 [12]')
  expect(calls).toBe(1)
})

test('cached paragraph opens offline and formula output cannot execute HTML', async ({ page }) => {
  const { paper, reading } = await openPaper(page)
  const id = reading.paragraphs[0].id
  reading.translations[id] = { text: '本机缓存：$\\frac{QK^T}{\\sqrt{d_k}}$。<img src=x onerror=alert(1)>', model: 'fixture' }
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`, route => route.fulfill({ json: reading }))
  await page.route('**/api/settings', route => route.fulfill({ json: { configured: false, translation_available: false, provider: 'MockProvider' } }))
  await page.reload()
  await page.getByRole('button', { name: '正在阅读', exact: true }).click()
  await page.getByRole('button', { name: '中英对照', exact: true }).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await expect(page.locator('.translated-text')).toContainText('本机缓存')
  await expect(page.locator('.translated-text .katex')).toBeVisible()
  await expect(page.locator('.translated-text img')).toHaveCount(0)
  await expect(page.locator('.pdfv-canvas').first()).toBeVisible()
})

test('translation errors stay with their paragraph and moving to another page still works', async ({ page }) => {
  const { paper } = await openPaper(page)
  await page.route(`**/api/papers/${paper.id}/translate`, route => route.fulfill({ status: 504, json: { detail: '模型连接超时，请重试' } }))
  await page.getByRole('button', { name: '中英对照', exact: true }).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await page.locator('.translation-panel').getByRole('button', { name: '翻译此段', exact: true }).click()
  await expect(page.locator('.translation-panel [role=alert]')).toContainText('模型连接超时')
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.locator('.pdfv-page-input')).toHaveValue('2')
  await expect(page.locator('.translation-panel [role=alert]')).toHaveCount(0)
  await expect(page.locator('.pdfv-page-shell[data-page-number="2"] .pdfv-canvas')).toBeVisible()
})

test('narrow reading space puts translation below the original and restores the wider layout', async ({ page }) => {
  await openPaper(page)
  await page.getByRole('button', { name: '中英对照', exact: true }).click()
  await expect(page.locator('.reader-layout')).toHaveClass(/translation-side/)
  await page.setViewportSize({width:960,height:720})
  await expect(page.locator('.reader-layout')).toHaveClass(/translation-bottom/)
  await expect(page.getByRole('button', { name: '译文放在右侧', exact: true })).toBeDisabled()
  await expect(page.locator('.pdfv-canvas').first()).toBeVisible()
  const panels = await page.evaluate(() => {
    const original=document.querySelector('.pdf-panel')!.getBoundingClientRect()
    const translation=document.querySelector('.translation-panel')!.getBoundingClientRect()
    return {originalRight:original.right,translationLeft:translation.left,translationTop:translation.top,originalBottom:original.bottom,scrollHeight:document.scrollingElement!.scrollHeight,height:innerHeight}
  })
  expect(panels.translationTop).toBeGreaterThanOrEqual(panels.originalBottom-1)
  expect(panels.scrollHeight).toBe(panels.height)
  await page.setViewportSize({width:1440,height:1000})
  await expect(page.locator('.reader-layout')).toHaveClass(/translation-side/)
  await expect(page.getByRole('button', { name: '译文放在右侧', exact: true })).toBeEnabled()
})

test('a paragraph spanning several source regions offers translation beside the hovered region', async ({ page }) => {
  const {paper,reading}=await openPaper(page)
  const paragraph=reading.paragraphs[0]
  const anchor=paragraph.anchors[0]
  const bounds=anchor.bbox
  reading.paragraphs=[{...paragraph,anchors:[anchor,{...anchor,bbox:[bounds[0],bounds[1]+110,bounds[2],bounds[3]+110]}]}]
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`,route=>route.fulfill({json:reading}))
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  const markers=page.locator('.pdfv-paragraph-marker')
  await expect(markers).toHaveCount(2)
  const lower=await markers.nth(1).boundingBox()
  await page.mouse.move(lower!.x+lower!.width/2,lower!.y+lower!.height/2)
  await expect(page.locator('.pdfv-paragraph-actions')).toBeVisible()
  const action=await page.locator('.pdfv-paragraph-actions').boundingBox()
  expect(action!.y).toBeGreaterThan(lower!.y-45)
  expect(action!.y).toBeLessThan(lower!.y)
  await expect(markers.nth(1)).toHaveClass(/hovered/)
  await expect(markers.first()).not.toHaveClass(/hovered/)
})
