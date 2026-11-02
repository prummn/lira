import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

async function openNotebookQuestion(page: Page) {
  const imported = await page.request.post('/api/papers/import', { multipart: { file: {
    name: 'notebook-chat.pdf', mimeType: 'application/pdf',
    buffer: Buffer.concat([await fs.readFile(path.resolve('test-artifacts/import-fixture.pdf')), Buffer.from(`\n% notebook-${Date.now()}\n`)]),
  } } })
  expect(imported.status()).toBe(201)
  const paper = await imported.json()
  const title = `Notebook conversation ${paper.id}`
  await page.request.patch(`/api/papers/${paper.id}`, { data: { title } })
  await page.route('**/api/settings', route => route.fulfill({ json: { provider: 'Fixture', configured: true, mode: 'remote', intelligence_available: true } }))
  await page.goto('/')
  await page.locator('.paper-row').filter({ hasText: title }).locator('.paper-name > button').click()
  await page.getByRole('button', { name: '问论文', exact: true }).click()
  return { paper, chat: page.locator('.paper-question'), input: page.getByRole('textbox', { name: '问论文', exact: true }) }
}

function conversationAnswer(text: string) {
  return { answer: text, items: [{ kind: 'background', content: text, citations: [] }], citations: [],
    provider: 'Fixture', mode: 'remote', insufficient_evidence: false, limitations: [], coverage: {}, usage: {}, cached: false }
}

test('notebook follow-ups retain earlier answers, history and drafts across notebook tabs', async ({ page }) => {
  const bodies: any[] = []
  await page.route('**/api/intelligence/ask', route => {
    bodies.push(route.request().postDataJSON())
    return route.fulfill({ json: conversationAnswer(bodies.length === 1 ? '先区分反思与探索。' : '探索决定会接触哪些候选。') })
  })
  const { paper, chat, input } = await openNotebookQuestion(page)
  await expect(input).toBeFocused()
  await input.fill('为什么读失败实验？')
  await input.press('Enter')
  await expect(chat.locator('.intelligence-answer')).toContainText('先区分反思与探索')
  await input.fill('探索具体指什么？')
  await page.getByRole('button', { name: '我的笔记', exact: true }).click()
  await expect(chat).toBeHidden()
  await page.getByRole('button', { name: '问论文', exact: true }).click()
  await expect(input).toHaveValue('探索具体指什么？')
  await expect(chat.locator('.intelligence-answer')).toContainText('先区分反思与探索')
  await input.press('Enter')
  await expect(chat.locator('.paper-question-turn')).toHaveCount(2)
  await expect(chat.locator('.intelligence-answer').last()).toContainText('探索决定')
  expect(bodies[1].history).toEqual([{ role: 'user', content: '为什么读失败实验？' }, { role: 'assistant', content: '先区分反思与探索。' }])
  expect(bodies[1].paper_ids).toEqual([paper.id])
  await expect(input).toHaveValue('')
  await expect(input).toBeFocused()
})

test('notebook question failures and cancellation preserve drafts and ignore late answers', async ({ page }) => {
  let calls = 0
  const releases: (() => void)[] = []
  await page.route('**/api/intelligence/ask', async route => {
    const call = ++calls
    if (call === 1) return route.fulfill({ status: 504, json: { detail: '连接超时，请重试' } })
    await new Promise<void>(resolve => releases.push(resolve))
    await route.fulfill({ json: conversationAnswer(call === 2 ? '已取消的旧答案。' : '本轮的新答案。') }).catch(() => {})
  })
  const { chat, input } = await openNotebookQuestion(page)
  await input.fill('第一轮问题')
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true, keyCode: 229 })
  expect(calls).toBe(0)
  await input.press('Enter')
  await expect(chat.getByRole('alert')).toContainText('连接超时')
  await expect(input).toHaveValue('第一轮问题')
  try {
    await input.press('Enter')
    await expect.poll(() => calls).toBe(2)
    await input.press('Enter')
    expect(calls).toBe(2)
    await chat.getByRole('button', { name: '停止回答', exact: true }).click()
    await expect(input).toHaveValue('第一轮问题')
    await input.fill('重新组织的问题')
    await input.press('Enter')
    await expect.poll(() => calls).toBe(3)
    await input.fill('尚未发送的追问')
    releases[0]()
    releases[1]()
    await expect(chat.locator('.intelligence-answer')).toContainText('本轮的新答案')
    await expect(chat).not.toContainText('已取消的旧答案')
    await expect(chat.locator('.paper-question-turn')).toHaveCount(1)
    await expect(input).toHaveValue('尚未发送的追问')
  } finally { releases.forEach(release => release()) }
})

test('paper answers render readable sections, tables and equations with compact traceable references', async ({ page }) => {
  const imported = await page.request.post('/api/papers/import', { multipart: { file: {
    name: 'answer-reading.pdf', mimeType: 'application/pdf',
    buffer: Buffer.concat([await fs.readFile(path.resolve('test-artifacts/import-fixture.pdf')), Buffer.from(`\n% answer-${Date.now()}\n`)]),
  } } })
  expect(imported.status()).toBe(201)
  const paper = await imported.json()
  const source = paper.chunks.find((c: any) => c.page === 2) ?? paper.chunks[0]
  const citation = { id: 'source-one', paper_id: paper.id, title: paper.title, source_id: source.id,
    source_text: source.content, source_type: 'paper', page: 2, section: 'B.1 Failure analysis',
    chunk_id: source.id, bbox: source.bbox, page_width: source.page_width, page_height: source.page_height }
  await page.route('**/api/settings', route => route.fulfill({ json: { provider: 'Fixture', configured: true, mode: 'remote', intelligence_available: true } }))
  const requests: any[] = []
  await page.route('**/api/intelligence/ask', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: { answer: '先读局限，再读实现。', items: [
      { kind: 'inference', content: '先读**失败实验**，再看实现细节。\n\n## 建议的阅读顺序\n\n| 位置 | 为什么读 |\n| --- | --- |\n| B.1 | 理解有效条件 |\n| C | 了解提示词结构 |\n\n1. 先比较失败条件。\n2. 再检查反思内容。\n\n可以把问题写成 $QK^T$。', citations: [citation, citation, { ...citation, id: 'source-two', source_id: 'other-block', source_text: 'A separate original supporting paragraph.' }] },
      { kind: 'background', content: '### 带着这个问题读\n\n一般而言，反思与探索承担不同作用。\n\n<script>window.answerUnsafe=true</script>\n<img src="x" onerror="window.answerUnsafe=true">\n\n[unsafe](javascript:alert(1))', citations: [] },
    ], citations: [citation], provider: 'AnswerFixture', model: 'fixture-model', mode: 'remote',
      insufficient_evidence: false, limitations: [], retrieved_paper_ids: [paper.id], queries: [],
      coverage: { reading_mode: 'full_paper', retrieval_is_partial: false }, usage: { total_tokens: 200, model_calls: 1 }, cached: false } })
  })
  await page.goto('/')
  await page.locator('.paper-row').filter({ hasText: paper.title }).first().locator('.paper-name > button').click()
  await page.getByRole('button', { name: '问论文', exact: true }).click()
  const input = page.getByRole('textbox', { name: '问论文', exact: true })
  await input.fill('附录还有什么值得读？')
  await page.getByRole('button', { name: '提问', exact: true }).click()
  const answer = page.locator('.intelligence-answer')
  await expect(answer.getByRole('heading', { name: '建议的阅读顺序' })).toBeVisible()
  await expect(answer.getByRole('table')).toBeVisible()
  await expect(answer.locator('ol > li')).toHaveCount(2)
  await expect(answer.locator('.katex')).toBeVisible()
  await expect(answer.locator('.answer-reference')).toHaveCount(1)
  await expect(answer.getByText(paper.title, { exact: true })).not.toBeVisible()
  await expect(answer.getByText('AnswerFixture', { exact: false })).not.toBeVisible()
  await answer.locator('.answer-reference').click()
  const sources = answer.locator('.answer-source-panel')
  await expect(sources).toBeVisible()
  await expect(sources.locator('.answer-source-quote')).toHaveCount(2)
  await sources.getByRole('button', { name: '定位原文', exact: true }).first().click()
  await expect(page.locator('.pdfv-page-input')).toHaveValue('2')
  expect(requests[0].reading_page).toBe(1)
  expect(await page.evaluate(() => (window as any).answerUnsafe)).toBeUndefined()
  await expect(answer.locator('a[href^="javascript:"]')).toHaveCount(0)
  await expect(answer.locator('script,img')).toHaveCount(0)
  await answer.locator('.answer-reference').click()
  await expect(sources).not.toBeVisible()
  await page.screenshot({ path: 'test-artifacts/research-answer-desktop.png' })
  await page.setViewportSize({ width: 1080, height: 800 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-artifacts/research-answer-narrow.png' })
})
