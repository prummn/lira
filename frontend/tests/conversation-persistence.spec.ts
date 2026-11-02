import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createServer } from 'node:http'

// These tests exercise SQLite and the real API. The loopback provider below is
// deterministic and cannot use the user's credentials or model quota.
async function importPaper(page: Page) {
  const result = await page.request.post('/api/papers/import', { multipart: { file: {
    name: 'persistent-chat.pdf', mimeType: 'application/pdf',
    buffer: Buffer.concat([await fs.readFile(path.resolve('test-artifacts/import-fixture.pdf')), Buffer.from(`\n% persistence-${crypto.randomUUID()}\n`)]),
  } } })
  expect(result.status()).toBe(201)
  const paper = await result.json()
  paper.title = `Persistent conversation ${paper.id}`
  expect((await page.request.patch(`/api/papers/${paper.id}`, { data: { title: paper.title } })).ok()).toBe(true)
  await page.route(`**/api/papers/${paper.id}/visual-regions`, route => route.fulfill({ json: { items: [
    { id:'fixture-figure',page:1,kind:'figure',label:'Figure 1',caption:'Figure 1: Verifier-guided reasoning',bbox:[48,120,548,290],page_width:595,page_height:842 },
  ] } }))
  return paper
}

async function openPaper(page: Page, title: string) {
  await page.getByRole('button', { name: '文献库', exact: true }).click()
  await page.locator('.paper-row').filter({ hasText: title }).locator('.paper-name > button').click()
  await expect(page.locator('.pdfv-canvas').first()).toBeVisible()
}

async function selectWord(page: Page, word = 'verifier') {
  const span = page.locator('.pdfv-text-layer span[role="presentation"]').filter({ hasText: word }).first()
  await span.evaluate((element, value) => {
    const node = element.firstChild!
    const start = node.textContent!.indexOf(value)
    const range = document.createRange()
    range.setStart(node, start)
    range.setEnd(node, start + value.length)
    window.getSelection()!.removeAllRanges()
    window.getSelection()!.addRange(range)
    element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
  }, word)
  await page.getByRole('button', { name: '解释所选', exact: true }).click()
}

test('paper answers and source snapshots survive navigation, reload and a fresh browser context', async ({ page, browser }) => {
  const paper = await importPaper(page)
  await page.goto('/')
  await openPaper(page, paper.title)
  await page.getByRole('button', { name: '问论文', exact: true }).click()
  const chat = page.locator('.paper-question')
  const input = chat.getByRole('textbox')
  const question = 'What does the verifier select?'
  await input.fill(question)
  await input.press('Enter')
  await expect(chat.locator('.intelligence-answer')).toBeVisible()
  const answerText = await chat.locator('.research-markdown').first().innerText()
  const history = await (await page.request.get(`/api/conversations?kind=paper&paper_id=${paper.id}`)).json()
  const firstId = history.items[0].id
  const saved = await (await page.request.get(`/api/conversations/${firstId}`)).json()
  expect(saved.turns[0].question).toBe(question)
  expect(saved.turns[0].response.citations.length).toBeGreaterThan(0)

  await openPaper(page, paper.title)
  await page.getByRole('button', { name: '问论文', exact: true }).click()
  await expect(chat.locator('.paper-question-user')).toHaveText(question)
  await expect(chat.locator('.research-markdown').first()).toHaveText(answerText)
  await page.reload()
  await openPaper(page, paper.title)
  await page.getByRole('button', { name: '问论文', exact: true }).click()
  await expect(chat.locator('.research-markdown').first()).toHaveText(answerText)
  await chat.locator('.answer-reference').first().click()
  await expect(chat.locator('.answer-source-panel')).toBeVisible()
  await chat.getByRole('button', { name: '定位原文', exact: true }).first().click()
  await expect(page.locator('.pdfv-page-input')).toHaveValue(String(saved.turns[0].response.citations[0].page))

  await chat.getByRole('button', { name: '新对话', exact: true }).click()
  await expect(chat.locator('.paper-question-turn')).toHaveCount(0)
  await input.fill('What is the limitation?')
  await input.press('Enter')
  await expect(chat.locator('.intelligence-answer')).toBeVisible()
  await chat.locator('.conversation-history > summary').click()
  await chat.locator('.conversation-history-menu').getByRole('button').filter({ hasText: question }).click()
  await expect(chat.locator('.paper-question-user')).toHaveText(question)
  expect((await (await page.request.get(`/api/conversations?kind=paper&paper_id=${paper.id}`)).json()).items).toHaveLength(2)
  await page.screenshot({ path: 'test-artifacts/persistent-paper-chat.png' })

  // No localStorage: the server archive still restores the latest conversation.
  const fresh = await browser.newContext()
  try {
    const nextPage = await fresh.newPage()
    await nextPage.goto('/')
    await openPaper(nextPage, paper.title)
    await nextPage.getByRole('button', { name: '问论文', exact: true }).click()
    await expect(nextPage.locator('.paper-question-user')).toHaveText('What is the limitation?')
  } finally { await fresh.close() }
})

test('selection questions reopen with saved answers without mixing different passages', async ({ page, browser }) => {
  const paper = await importPaper(page)
  await page.goto('/')
  await openPaper(page, paper.title)
  await selectWord(page)
  const dialog = page.getByRole('dialog')
  const question = 'What does this verifier do?'
  await dialog.getByRole('textbox').fill(question)
  await dialog.getByRole('textbox').press('Enter')
  await expect(dialog.locator('.explain-answer')).toBeVisible()
  const answerText = await dialog.locator('.explain-answer-text').innerText()
  const source=dialog.locator('.explain-turn .question-source')
  await expect(source).toContainText('verifier')
  await expect(source).toContainText('页 1')
  expect((await source.boundingBox())!.y).toBeLessThan((await dialog.locator('.explain-user-question').boundingBox())!.y)
  await dialog.getByRole('button', { name: '关闭', exact: true }).first().click()
  await selectWord(page)
  await expect(dialog.locator('.explain-user-question')).toHaveText(question)
  await expect(dialog.locator('.explain-answer-text')).toHaveText(answerText)
  await dialog.getByRole('button', { name: '关闭', exact: true }).first().click()
  await selectWord(page, 'reasoning')
  await expect(dialog.getByRole('textbox')).toBeEnabled()
  await expect(dialog.locator('.explain-turn')).toHaveCount(0)
  await dialog.getByRole('button', { name: '关闭', exact: true }).first().click()
  await page.reload()
  await openPaper(page, paper.title)
  await selectWord(page)
  await expect(dialog.locator('.explain-answer-text')).toHaveText(answerText)
  await expect(source).toContainText('verifier')
  const fresh=await browser.newContext()
  try {
    const restored=await fresh.newPage()
    await restored.goto('/')
    await openPaper(restored,paper.title)
    await restored.getByRole('button',{name:'阅读对话',exact:true}).click()
    const archived=restored.getByRole('dialog')
    await expect(archived.locator('.question-source')).toContainText('verifier')
    await archived.getByRole('button',{name:'定位提问原文',exact:true}).click()
    await expect(archived).toHaveCount(0)
    await expect(restored.locator('.pdfv-page-input')).toHaveValue('1')
    await expect(restored.locator('.pdfv-evidence-overlay')).toBeVisible()
  } finally {await fresh.close()}
})

test('dialog history includes all passages in this paper and restores the complete context for follow-ups', async ({ page }) => {
  test.setTimeout(90000)
  const paper = await importPaper(page)
  const other = await importPaper(page)
  const detail = await (await page.request.get('/api/papers/' + paper.id)).json()
  const originalChunk = detail.chunks.find((item: any) => item.page === 2 && item.content.includes('valid traces'))
  const translatedChunk = detail.chunks.find((item: any) => item.page === 1 && item.content.includes('verifier'))
  const pixel = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
  const seed = async (paperId: string, context: Record<string, unknown>, question: string) => {
    const created = await page.request.post('/api/conversations', { data: { kind: 'explanation', paper_id: paperId, context } })
    expect(created.status()).toBe(201)
    const saved = await created.json()
    const response = await page.request.post('/api/papers/' + paperId + '/explain', { data: {
      ...context, question, conversation_id: saved.id, ...(context.visual ? { image_data_url: pixel } : {}),
    } })
    expect(response.ok(), await response.text()).toBe(true)
    return saved.id as string
  }
  const original = { page: 2, chunk_id: originalChunk.id, selected_text: 'valid traces', visual: false }
  const translated = { page: 1, chunk_id: translatedChunk.id, selected_text: 'verifier', translated_text: '这里的验证器', visual: false }
  const visual = { page: 1, selected_text: 'verifier', visual: true, visual_kind: 'figure', visual_label: 'Figure 1', bbox: [48, 120, 548, 290] }
  const originalId = await seed(paper.id, original, '原文对话：这些轨迹怎么选择？')
  const translatedId = await seed(paper.id, translated, '译文对话：这里的验证器做什么？')
  const visualId = await seed(paper.id, visual, '图表对话：Figure 1 如何工作？')
  const otherDetail = await (await page.request.get('/api/papers/' + other.id)).json()
  await seed(other.id, { page: 1, chunk_id: otherDetail.chunks[0].id, selected_text: otherDetail.chunks[0].content, visual: false }, '另一篇论文的对话')
  const submissions: any[] = []
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/api/papers/' + paper.id + '/explain')) submissions.push(request.postDataJSON())
  })
  await page.goto('/')
  await openPaper(page, paper.title)
  await selectWord(page, 'reasoning')
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('textbox')).toBeEnabled()
  await expect(dialog.locator('.explain-turn')).toHaveCount(0)
  const openHistory = async () => {
    await dialog.locator('.conversation-history > summary').click()
    return dialog.locator('.conversation-history-menu')
  }
  let history = await openHistory()
  await expect(history.getByRole('button')).toHaveCount(3)
  await expect(history).not.toContainText('另一篇论文的对话')
  await history.getByRole('button').filter({ hasText: '译文对话：' }).click()
  await expect(dialog.locator('.explain-user-question')).toHaveText(['译文对话：这里的验证器做什么？'])
  await expect(dialog.locator('.question-source')).toContainText('这里的验证器')
  await dialog.locator('.explain-context-toggle').click()
  await expect(dialog.locator('.explain-selection-quote')).toHaveText('这里的验证器')
  await expect(dialog.locator('.explain-selection-source')).toContainText('verifier')
  const followUp = async (question: string) => {
    await dialog.getByRole('textbox').fill(question)
    await dialog.getByRole('textbox').press('Enter')
    await expect(dialog.locator('.explain-answer-text')).toHaveCount(2)
    await expect(dialog.locator('[role=alert]')).toHaveCount(0)
  }
  await followUp('译文追问')
  expect(submissions.at(-1)).toMatchObject({ conversation_id: translatedId, page: 1, chunk_id: translatedChunk.id, selected_text: 'verifier', translated_text: '这里的验证器' })
  history = await openHistory()
  await expect(history.locator('button[aria-current=true]')).toContainText('译文对话：')
  await history.getByRole('button').filter({ hasText: '图表对话：' }).click()
  await expect(dialog.locator('.explain-user-question')).toHaveText(['图表对话：Figure 1 如何工作？'])
  await expect(dialog.locator('.question-source')).toContainText('Figure 1')
  await dialog.locator('.explain-context-toggle').click()
  const preview = dialog.locator('.explain-page-preview img')
  await expect(preview).toBeVisible()
  await expect.poll(() => preview.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(500)
  expect(await preview.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeLessThan(900)
  await followUp('图表追问')
  expect(submissions.at(-1)).toMatchObject({ conversation_id: visualId, page: 1, bbox: visual.bbox, visual_kind: 'figure', visual_label: 'Figure 1', selected_text: visual.selected_text })
  expect(submissions.at(-1).image_data_url).toContain('data:image/')
  expect(submissions.at(-1).translated_text).toBeUndefined()
  history = await openHistory()
  await history.getByRole('button').filter({ hasText: '原文对话：' }).click()
  await expect(dialog.locator('.explain-user-question')).toHaveText(['原文对话：这些轨迹怎么选择？'])
  await expect(dialog.locator('.question-source')).toContainText('页 2')
  await expect(dialog.locator('.question-source')).toContainText('valid traces')
  await dialog.locator('.explain-context-toggle').click()
  await expect(dialog.locator('.explain-selection-quote')).toHaveText('valid traces')
  await expect(dialog.locator('.explain-page-preview')).toHaveCount(0)
  await followUp('原文追问')
  expect(submissions.at(-1)).toMatchObject({ conversation_id: originalId, page: 2, chunk_id: originalChunk.id, selected_text: 'valid traces' })
  expect(submissions.at(-1).image_data_url).toBeUndefined()
  for (const id of [originalId, translatedId, visualId]) {
    const saved = await (await page.request.get('/api/conversations/' + id)).json()
    expect(saved.turns).toHaveLength(2)
    expect(saved.turns.every((turn: any) => turn.status === 'completed')).toBe(true)
  }
  await dialog.getByRole('button', { name: '新对话', exact: true }).click()
  await expect(dialog.locator('.explain-turn')).toHaveCount(0)
  await expect(dialog.locator('.explain-context-excerpt')).toHaveText('valid traces')
  await dialog.getByRole('textbox').fill('原文选区的新对话')
  await dialog.getByRole('textbox').press('Enter')
  await expect(dialog.locator('.explain-answer-text')).toHaveCount(1)
  expect(submissions.at(-1).conversation_id).not.toBe(originalId)
  expect(submissions.at(-1)).toMatchObject({ page: 2, chunk_id: originalChunk.id, selected_text: 'valid traces' })
  await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
  await page.getByRole('button', { name: '阅读对话', exact: true }).click()
  await expect(dialog.locator('.explain-user-question')).toHaveText('原文选区的新对话')
  await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
  await selectWord(page, 'reasoning')
  await expect(dialog.getByRole('textbox')).toBeEnabled()
  await expect(dialog.locator('.explain-turn')).toHaveCount(0)
  history = await openHistory()
  await expect(history.getByRole('button')).toHaveCount(4)
  await history.getByRole('button').filter({ hasText: '原文对话：' }).click()
  await expect(dialog.locator('.explain-user-question')).toHaveText(['原文对话：这些轨迹怎么选择？', '原文追问'])
  await dialog.getByRole('button', { name: '新对话', exact: true }).click()
  await expect(dialog.locator('.explain-turn')).toHaveCount(0)
  history = await openHistory()
  await history.getByRole('button').filter({ hasText: '原文对话：' }).click()
  await expect(dialog.locator('.explain-user-question')).toHaveText(['原文对话：这些轨迹怎么选择？', '原文追问'])
  expect(submissions).toHaveLength(4)
})

test('the reading entry restores both a translated excerpt and its original evidence without reselecting', async ({ page }) => {
  const paper = await importPaper(page)
  const detail = await (await page.request.get('/api/papers/' + paper.id)).json()
  const chunk = detail.chunks.find((item: any) => item.content.includes('verifier'))
  const context = { page: chunk.page, chunk_id: chunk.id, selected_text: 'verifier', translated_text: '这里的验证器', visual: false }
  const saved = await (await page.request.post('/api/conversations', { data: { kind: 'explanation', paper_id: paper.id, context } })).json()
  const result = await page.request.post('/api/papers/' + paper.id + '/explain', { data: {
    conversation_id: saved.id, question: '这里的验证器做什么？', page: chunk.page, chunk_id: chunk.id,
    selected_text: 'verifier', translated_text: '这里的验证器',
  } })
  expect(result.ok()).toBe(true)
  let submissions = 0
  await page.route('**/api/papers/*/explain', async route => {
    submissions++
    const body = route.request().postDataJSON()
    expect(body.conversation_id).toBe(saved.id)
    expect(body.selected_text).toBe('verifier')
    expect(body.translated_text).toBe('这里的验证器')
    await route.fulfill({ json: { answer: '沿用原来的英文证据回答追问。', citations: [], insufficient_evidence: false, provider: 'Fixture', mode: 'remote' } })
  })
  await page.goto('/')
  await openPaper(page, paper.title)
  await page.getByRole('button', { name: '阅读对话', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('.explain-user-question')).toHaveText('这里的验证器做什么？')
  const source=dialog.locator('.explain-turn .question-source')
  await expect(source).toContainText('这里的验证器')
  await source.getByRole('button',{name:'展开完整选区',exact:true}).click()
  await expect(source.locator('.question-source-original')).toContainText('verifier')
  await dialog.locator('.explain-context-toggle').click()
  await expect(dialog.locator('.explain-selection-quote')).toHaveText('这里的验证器')
  await expect(dialog.locator('.explain-selection-source')).toContainText('verifier')
  expect(submissions).toBe(0)
  await dialog.getByRole('textbox').fill('它怎样筛选？')
  await dialog.getByRole('textbox').press('Enter')
  await expect(dialog.locator('.explain-answer-text').last()).toContainText('沿用原来的英文证据')
  expect(submissions).toBe(1)
})

for (const mode of ['selection', 'visual'] as const) test('reading chat restores an in-flight ' + mode + ' question after navigation and reload without another submission', async ({ page }) => {
  const paper = await importPaper(page)
  let release!: () => void
  const waiting = new Promise<void>(resolve => { release = resolve })
  let calls = 0
  let entered = false
  const server = createServer(async (request, response) => {
    try {
      const buffers: Buffer[] = []
      for await (const part of request) buffers.push(Buffer.from(part))
      const body = JSON.parse(Buffer.concat(buffers).toString())
      const content = body.messages.at(-1).content
      const raw = typeof content === 'string' ? content : content.find((part: any) => part.type === 'text').text
      const payload = JSON.parse(raw.replace(/^Return JSON for this data:\s*/, ''))
      calls++
      entered = true
      await waiting
      const chunk = payload.chunks[0]
      const data = { answer: '收起和离开后保留下来的回答：验证器筛选推理轨迹。', insufficient_evidence: false,
        citations: chunk ? [{ chunk_id: chunk.chunk_id, source_text: chunk.content }] : [], needs_more_context: false }
      response.writeHead(200, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify(data) }, finish_reason: 'stop' }],
        model: 'reading-resume-fixture', usage: { prompt_tokens: 100, completion_tokens: 40, total_tokens: 140 } }))
    } catch { response.writeHead(500); response.end('Local fixture failed') }
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address() as { port: number }
  const configured = await page.request.post('/api/settings/profiles', { data: {
    name: 'Reading resume loopback', base_url: 'http://127.0.0.1:' + address.port + '/v1', model: 'reading-resume-fixture',
    api_key: 'local-fixture-only', wire_api: 'chat_completions', reasoning_effort: 'disabled', test_connection: false,
  } })
  expect(configured.status()).toBe(201)
  const profile = await configured.json()
  try {
    await page.goto('/')
    await openPaper(page, paper.title)
    if (mode === 'selection') await selectWord(page)
    else {
      const figureBox=await page.locator('[data-visual-id="fixture-figure"]').boundingBox()
      expect(figureBox).not.toBeNull()
      await page.mouse.move(figureBox!.x+figureBox!.width/2,figureBox!.y+figureBox!.height/2)
      await page.locator('.pdfv-visual-region-action').first().click()
    }
    const dialog = page.getByRole('dialog')
    const question = '解释这里的 verifier：' + mode
    await dialog.getByRole('textbox', { name: '向论文提问', exact: true }).fill(question)
    await dialog.getByRole('textbox', { name: '向论文提问', exact: true }).press('Enter')
    await expect.poll(() => entered).toBe(true)
    const list = await (await page.request.get('/api/conversations?kind=explanation&paper_id=' + paper.id)).json()
    const id = list.items[0].id
    expect(list.items[0].latest_status).toBe('running')
    await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    if (mode === 'selection') {
      await selectWord(page, 'reasoning')
      await expect(dialog.getByRole('textbox')).toBeEnabled()
      await expect(dialog.locator('.explain-turn')).toHaveCount(0)
      await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
      await page.locator('.reading-chat-history > summary').click()
      await page.getByRole('region', { name: '本篇阅读对话', exact: true }).getByRole('button').filter({ hasText: question }).click()
      await expect(dialog.locator('.explain-user-question')).toHaveText(question)
      await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
      expect(calls).toBe(1)
    }
    await page.getByRole('button', { name: '文献库', exact: true }).first().click()
    await page.reload()
    await openPaper(page, paper.title)
    const resume = page.getByRole('button', { name: '阅读对话', exact: true })
    await expect(resume).toContainText('回答中')
    await resume.click()
    await expect(dialog.locator('.explain-user-question')).toHaveText(question)
    await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
    release()
    await expect.poll(async () => (await (await page.request.get('/api/conversations/' + id)).json()).turns[0].status).toBe('completed')
    await resume.click()
    await expect(dialog.locator('.explain-answer-text')).toContainText('保留下来的回答', { timeout: 15000 })
    if (mode === 'visual') {
      await dialog.locator('.explain-context-toggle').click()
      await expect(dialog.locator('.explain-page-preview img')).toBeVisible()
    }
    expect(calls).toBe(1)
    await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
    await page.locator('.reading-chat-history > summary').click()
    const history = page.getByRole('region', { name: '本篇阅读对话', exact: true })
    await expect(history).toContainText(question)
    await history.getByRole('button').filter({ hasText: question }).click()
    await expect(dialog.locator('.explain-answer-text')).toContainText('保留下来的回答')
    expect(calls).toBe(1)
    await page.screenshot({ path: 'test-artifacts/reading-chat-resumed-' + mode + '.png' })
  } finally {
    release()
    await page.request.delete('/api/settings/profiles/' + profile.id)
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
})

test('librarian finishes and saves an answer after leaving, then restores it after reload', async ({ page }) => {
  const paper = await importPaper(page)
  let calls = 0
  let release!: () => void
  const waiting = new Promise<void>(resolve => { release = resolve })
  let entered = false
  const server = createServer(async (request, response) => {
    try {
      const buffers: Buffer[] = []
      for await (const part of request) buffers.push(Buffer.from(part))
      const body = JSON.parse(Buffer.concat(buffers).toString())
      const payload = JSON.parse(body.messages.at(-1).content)
      calls++
      let data
      if (payload.sources) {
        entered = true
        await waiting
        const source = payload.sources.find((s: any) => s.paper_id === paper.id && s.type === 'paper')
          ?? payload.sources.find((s: any) => s.type === 'paper')
        data = { insufficient_evidence: false, items: [{ kind: 'fact', content: '## 保留下来的回答\n\n方法通过验证器筛选推理轨迹。',
          citations: [{ source_id: source.source_id, quote_id: source.quote_id }] }], limitations: [] }
      } else data = { intent: 'research', queries: ['verifier'], paper_ids: [paper.id] }
      response.writeHead(200, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify(data) }, finish_reason: 'stop' }],
        model: 'archive-fixture', usage: { prompt_tokens: 100, completion_tokens: 40, total_tokens: 140 } }))
    } catch (error) { response.writeHead(500); response.end(String(error)) }
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address() as { port: number }
  const configured = await page.request.post('/api/settings/profiles', { data: {
    name: 'Persistence loopback fixture', base_url: `http://127.0.0.1:${address.port}/v1`, model: 'archive-fixture', api_key: 'local-fixture-only',
    wire_api: 'chat_completions', reasoning_effort: 'disabled', test_connection: false,
  } })
  expect(configured.status()).toBe(201)
  const profile = await configured.json()
  try {
    await page.goto('/')
    await page.getByRole('button', { name: 'AI 文献员', exact: true }).click()
    const question = `请介绍验证器的作用 ${paper.id}`
    await page.getByRole('textbox', { name: '向文献员提问' }).fill(question)
    await page.getByRole('button', { name: '提问', exact: true }).click()
    await expect.poll(() => entered).toBe(true)
    const list = await (await page.request.get('/api/conversations?kind=librarian&context=%7B%7D')).json()
    const saved = await (await page.request.get(`/api/conversations/${list.items[0].id}`)).json()
    expect(saved.turns[0].question).toBe(question)
    expect(saved.turns[0].status).toBe('running')
    await page.getByRole('button', { name: '文献库', exact: true }).click()
    await page.getByRole('button', { name: 'AI 文献员', exact: true }).click()
    await expect(page.locator('.librarian-user-question')).toHaveText(question)
    release()
    await expect(page.locator('.librarian-answer')).toContainText('保留下来的回答', { timeout: 15000 })
    const finalCalls = calls
    await page.reload()
    await page.getByRole('button', { name: 'AI 文献员', exact: true }).click()
    await expect(page.locator('.librarian-answer h2')).toHaveText('保留下来的回答')
    await page.locator('.librarian-answer .answer-reference').first().click()
    await expect(page.locator('.answer-source-panel')).toBeVisible()
    expect(calls).toBe(finalCalls)
    await page.screenshot({ path: 'test-artifacts/persistent-librarian-chat.png' })
  } finally {
    release()
    await page.request.delete(`/api/settings/profiles/${profile.id}`)
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
})
