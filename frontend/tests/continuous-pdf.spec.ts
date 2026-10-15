import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

// A real, deliberately mixed-size document keeps the virtualization assertions
// independent of network downloads and of the backend's short fixture.
function longPdf(): Buffer {
  const objects: string[] = []
  objects.push('<< /Type /Catalog /Pages 2 0 R >>')
  objects.push(`<< /Type /Pages /Count 12 /Kids [${Array.from({ length: 12 }, (_, i) => `${4 + i * 2} 0 R`).join(' ')}] >>`)
  objects.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
  for (let page = 1; page <= 12; page++) {
    const [width, height] = page % 2 ? [595, 842] : [420, 500]
    const text = `BT /F1 18 Tf 60 ${height - 100} Td (Continuous Reading page ${page}) Tj 0 -35 Td (${page === 12 ? 'distantneedle' : 'Native scrolling preserves the reading position.'}) Tj ET`
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] /Resources << /Font << /F1 3 0 R >> >> /Contents ${5 + (page - 1) * 2} 0 R >>`)
    objects.push(`<< /Length ${text.length} >>\nstream\n${text}\nendstream`)
  }
  let body = '%PDF-1.4\n'
  const offsets = [0]
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(body)); body += `${index + 1} 0 obj\n${object}\nendobj\n` })
  const xref = Buffer.byteLength(body)
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`
  return Buffer.from(body)
}

async function openFixture(page: Page, long = false) {
  const response = await page.request.post('/api/papers/import', { multipart: { file: {
    name: 'continuous-reading.pdf', mimeType: 'application/pdf',
    buffer: Buffer.concat([
      long ? longPdf() : await fs.readFile(path.resolve('test-artifacts/import-fixture.pdf')),
      Buffer.from(`\n% continuous-${Date.now()}\n`),
    ]),
  } } })
  expect(response.status()).toBe(201)
  const paper = await response.json()
  paper.title = `Continuous Reading ${Date.now()}`
  await page.request.patch(`/api/papers/${paper.id}`, { data: { title: paper.title } })
  await page.goto('/')
  await page.locator('.paper-row').filter({ hasText: paper.title }).first().locator('.paper-name > button').click()
  await expect(page.locator('.pdfv-page-shell[data-page-number="1"]')).toBeVisible()
  await expect(page.locator('.pdfv-page-shell[data-page-number="2"]')).toBeAttached()
  return paper
}

test('PDF pages share one native scroll surface and update the current page', async ({ page }) => {
  await openFixture(page)
  const scroll = page.locator('.pdfv-scroll')
  const initial = await scroll.evaluate(element => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    overflowY: getComputedStyle(element).overflowY,
  }))
  expect(initial.scrollHeight).toBeGreaterThan(initial.clientHeight)
  expect(initial.overflowY).toBe('auto')

  await scroll.hover()
  await page.mouse.wheel(0, initial.scrollHeight)
  await expect(page.locator('.pdfv-page-input')).toHaveValue('2')
  await expect(page.locator('.pdfv-page-shell[data-page-number="2"] .pdfv-canvas')).toBeVisible()
  await expect(page.locator('.pdfv-page-shell[data-page-number="1"] .pdfv-canvas')).toBeVisible()
  const lower = await scroll.evaluate(element => element.scrollTop)
  await page.mouse.wheel(0, -120)
  await expect.poll(() => scroll.evaluate(element => element.scrollTop)).toBeLessThan(lower - 60)
})

test('page controls and evidence navigation scroll within the PDF container', async ({ page }) => {
  await openFixture(page)
  await page.locator('.pdfv-page-input').fill('2')
  await page.locator('.pdfv-page-input').press('Enter')
  expect(await page.locator('.pdfv-scroll').evaluate(element => element.scrollTop)).toBeGreaterThan(0)
  await expect(page.locator('.pdfv-page-input')).toHaveValue('2')
  const positions = await page.locator('.pdfv-page-shell').evaluateAll(elements => elements.map(element => ({
    page: element.getAttribute('data-page-number'), top: element.getBoundingClientRect().top,
  })))
  expect(positions[1].top).toBeLessThan(await page.locator('.pdfv-scroll').evaluate(element => element.getBoundingClientRect().bottom))
  expect(await page.evaluate(() => document.documentElement.scrollTop)).toBe(0)
})

test('distant evidence navigation retains its precise rectangle while page geometry loads', async ({ page }) => {
  const response=await page.request.post('/api/papers/import',{multipart:{file:{
    name:'continuous-evidence.pdf',mimeType:'application/pdf',
    buffer:Buffer.concat([longPdf(),Buffer.from(`\n% evidence-${Date.now()}\n`)]),
  }}})
  expect(response.status()).toBe(201)
  const paper=await response.json()
  paper.title=`Continuous Evidence ${Date.now()}`
  await page.request.patch(`/api/papers/${paper.id}`,{data:{title:paper.title}})
  await page.goto('/')
  await page.locator('.library-controls input').fill('distantneedle')
  const hit=page.locator('.fulltext-hit').filter({hasText:paper.title})
  await expect(hit).toBeVisible()
  await hit.click()
  await expect(page.locator('.pdfv-page-input')).toHaveValue('12')
  const shell=page.locator('.pdfv-page-shell[data-page-number="12"]')
  const overlay=shell.locator('.pdfv-evidence-overlay')
  await expect(overlay).toBeVisible()
  const position=await shell.evaluate(element=>{
    const pageRect=element.getBoundingClientRect(),target=element.querySelector('.pdfv-evidence-overlay')!.getBoundingClientRect()
    return {top:target.top-pageRect.top,width:target.width,height:target.height}
  })
  expect(position.top).toBeGreaterThan(20)
  expect(position.width).toBeGreaterThan(10)
  expect(position.height).toBeGreaterThan(5)
})

test('zoom and layout changes preserve the page and fractional reading anchor', async ({ page }) => {
  await openFixture(page, true)
  const scroll = page.locator('.pdfv-scroll')
  await page.locator('.pdfv-page-input').fill('6')
  await page.locator('.pdfv-page-input').press('Enter')
  await expect(page.locator('.pdfv-page-input')).toHaveValue('6')
  await scroll.evaluate(element => element.scrollBy(0, 170))
  const anchor = () => page.evaluate(() => {
    const scroll = document.querySelector('.pdfv-scroll')!
    const paper = document.querySelector('.pdfv-page-shell[data-page-number="6"]')!
    const bounds = paper.getBoundingClientRect()
    return (scroll.getBoundingClientRect().top + 100 - bounds.top) / bounds.height
  })
  const before = await anchor()
  await page.getByRole('button', { name: /放大|Zoom in/i }).click()
  await expect(page.locator('.pdfv-page-shell[data-page-number="6"] .pdfv-canvas')).toBeVisible()
  await expect.poll(async () => Math.abs(await anchor() - before)).toBeLessThan(.03)
  await page.setViewportSize({ width: 1250, height: 850 })
  await expect.poll(async () => Math.abs(await anchor() - before)).toBeLessThan(.03)
})

test('distant search mounts only nearby pages while preserving exact placeholders', async ({ page }) => {
  await openFixture(page, true)
  await expect(page.locator('.pdfv-page-shell')).toHaveCount(12)
  const dimensions=await page.locator('.pdfv-page-shell').evaluateAll(elements=>elements.slice(0,2).map(element=>{
    const rect=element.getBoundingClientRect();return {width:rect.width,height:rect.height}
  }))
  expect(dimensions[0].height/dimensions[0].width).toBeCloseTo(842/595,2)
  expect(dimensions[1].height/dimensions[1].width).toBeCloseTo(500/420,2)
  const before = await page.locator('.pdfv-page-shell[data-page-number="1"]').evaluate(element => element.getBoundingClientRect().height)
  await page.getByRole('button', { name: '全文搜索', exact: true }).click()
  await page.locator('.pdfv-searchbar input').fill('distantneedle')
  await expect(page.locator('.pdfv-page-input')).toHaveValue('12')
  await expect(page.locator('.pdfv-page-shell[data-page-number="12"] .pdfv-search-match')).toBeVisible()
  await expect(page.locator('.pdfv-page-shell[data-page-number="1"] .pdfv-canvas')).toHaveCount(0)
  expect(await page.locator('.pdfv-canvas').count()).toBeLessThanOrEqual(5)
  expect(await page.locator('.pdfv-page-shell[data-page-number="1"]').evaluate(element => element.getBoundingClientRect().height)).toBeCloseTo(before, 1)
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(await page.evaluate(() => innerHeight))
})
