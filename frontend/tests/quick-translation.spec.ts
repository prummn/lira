import { test, expect, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

async function openPaper(page: Page) {
  const buffer = await fs.readFile(path.resolve('test-artifacts/import-fixture.pdf'))
  const response = await page.request.post('/api/papers/import', {multipart:{file:{name:'quick-translation.pdf',mimeType:'application/pdf',buffer}}})
  expect(response.status()).toBe(201)
  const paper = await response.json()
  const title = `Quick translation ${paper.id}`
  await page.request.patch(`/api/papers/${paper.id}`, {data:{title}})
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:title}).locator('.paper-name > button').click()
  await expect(page.locator('.pdfv-text-layer[data-page-number="1"] span').first()).toBeVisible()
}

test('a short English selection opens dictionary quick translation without model translation', async ({page}) => {
  await openPaper(page)
  let calls = 0
  let paragraphTranslationCalls = 0
  await page.route('**/api/papers/*/translate', async route => {
    paragraphTranslationCalls += 1
    await route.abort()
  })
  await page.route('**/api/dictionary/lookup', async route => {
    calls += 1
    expect(route.request().postDataJSON()).toEqual({text:'verifier'})
    await route.fulfill({json:{
      query:'verifier', normalized_query:'verifier', translation:'核验器；验证者', phonetic:'/ˈverɪfaɪə(r)/',
      definitions:[{part_of_speech:'n.',text:'核验器；验证者',example:null}], source:'youdao', cached:false,
    }})
  })
  await page.locator('.pdfv-text-layer[data-page-number="1"]').evaluate(element => {
    const span = Array.from(element.querySelectorAll('span[role="presentation"]')).find(item => item.textContent?.includes('verifier.'))!
    const text = span.firstChild!
    const start = text.textContent!.indexOf('verifier')
    const range = document.createRange(); range.setStart(text, start); range.setEnd(text, start + 'verifier'.length)
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    span.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}))
  })
  await page.getByRole('button', {name:'短词速译', exact:true}).click()
  await expect(page.locator('.quick-translation-popover')).toContainText('核验器')
  await expect(page.locator('.quick-translation-popover')).toContainText('/ˈverɪfaɪə(r)/')
  expect(calls).toBe(1)
  expect(paragraphTranslationCalls).toBe(0)
})
