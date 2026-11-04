import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

async function openQuestion(page: Page, visual = true) {
  const imported = await page.request.post('/api/papers/import', { multipart: { file: {
    name: 'question-layout.pdf', mimeType: 'application/pdf',
    buffer: Buffer.concat([await fs.readFile(path.resolve('test-artifacts/import-fixture.pdf')), Buffer.from(`\n% chat-${Date.now()}\n`)]),
  } } })
  expect(imported.status()).toBe(201)
  const paper = await imported.json()
  await page.request.patch(`/api/papers/${paper.id}`, { data: { title: `Question layout ${paper.id}` } })
  await page.route(`**/api/papers/${paper.id}/visual-regions`, route => route.fulfill({ json: { items: [
    { id:'fixture-figure',page:1,kind:'figure',label:'Figure 1',caption:'Figure 1: Verifier-guided reasoning',bbox:[48,120,548,290],page_width:595,page_height:842 },
    { id:'fixture-table',page:1,kind:'table',label:'Table 1',caption:'Table 1: Verifier results',bbox:[48,330,548,480],page_width:595,page_height:842 },
    { id:'fixture-equation',page:1,kind:'equation',label:'Equation (3)',caption:'P \uf03d \uf072 R T',bbox:[100,520,500,570],page_width:595,page_height:842 },
  ] } }))
  await page.goto('/')
  await page.locator('.paper-row').filter({ hasText: `Question layout ${paper.id}` }).locator('.paper-name > button').click()
  await expect(page.locator('.pdfv-canvas').first()).toBeVisible()
  if (visual) {
    const figureBox=await page.locator('[data-visual-id="fixture-figure"]').boundingBox()
    expect(figureBox).not.toBeNull()
    await page.mouse.move(figureBox!.x+figureBox!.width/2,figureBox!.y+figureBox!.height/2)
    await page.locator('.pdfv-visual-region-action.figure').click()
  } else {
    const text = page.locator('.pdfv-text-layer span[role="presentation"]').filter({ hasText: 'verifier' }).first()
    await text.evaluate(element => {
      const range = document.createRange()
      range.selectNodeContents(element)
      const selection = window.getSelection()!
      selection.removeAllRanges()
      selection.addRange(range)
      element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    })
    await page.getByRole('button', { name: '解释所选', exact: true }).click()
  }
  return { paper, dialog: page.getByRole('dialog'), input: page.getByRole('textbox', { name: '向论文提问', exact: true }) }
}

const answer = (text: string, citations: unknown[] = []) => ({ answer: text, provider: 'FixtureVision', mode: 'remote', citations, insufficient_evidence: false, context_scope: 'section', visual_used: true })

test('a submitted question keeps its selected passage beside it while waiting and after the answer',async({page})=>{
  let release!:()=>void
  const waiting=new Promise<void>(resolve=>{release=resolve})
  let calls=0
  await page.route('**/api/papers/*/explain',async route=>{calls++;await waiting;await route.fulfill({json:answer('因为模型评审提供的是间接判断，运行测试提供的是直接执行结果。')})})
  const {dialog,input}=await openQuestion(page,false)
  try {
    await input.fill('为什么这么说？');await input.press('Enter')
    const source=dialog.locator('.explain-pending-turn .question-source')
    await expect(source).toContainText('verifier')
    await expect(source.getByRole('button',{name:'定位提问原文',exact:true})).toBeVisible()
    release()
    await expect(dialog.locator('.explain-answer-text')).toContainText('间接判断')
    await expect(dialog.locator('.explain-turn .question-source')).toContainText('verifier')
    expect(calls).toBe(1)
  } finally {release()}
})

test('figures and tables have distinct question actions and no page or drag selection entry remains', async ({ page }) => {
  const { dialog } = await openQuestion(page)
  await expect(page.getByRole('button', { name: /问当前页|框选图表/ })).toHaveCount(0)
  await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
  const figure=page.locator('[data-visual-id="fixture-figure"]'), figureBox=await figure.boundingBox()
  expect(figureBox).not.toBeNull()
  await page.mouse.move(figureBox!.x+figureBox!.width/2,figureBox!.y+figureBox!.height/2)
  const figureIcon = await page.locator('.pdfv-visual-region-action.figure svg').evaluate(element => element.outerHTML)
  const table = page.locator('[data-visual-id="fixture-table"]')
  const box = await table.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)
  const tableAction = page.locator('.pdfv-visual-region-action.table')
  await expect(tableAction).toBeVisible()
  const tableIcon = await tableAction.locator('svg').evaluate(element => element.outerHTML)
  expect(tableIcon).not.toBe(figureIcon)
})

test('a detected equation opens its own visual question and keeps its identity in saved history', async ({page}) => {
  const {dialog,input,paper} = await openQuestion(page)
  await dialog.getByRole('button',{name:'收起对话',exact:true}).click()
  const box = await page.locator('[data-visual-id="fixture-equation"]').boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box!.x+box!.width/2,box!.y+box!.height/2)
  await page.locator('.pdfv-visual-region-action.equation').click()
  await expect(dialog).toContainText('询问公式')
  await dialog.locator('.explain-context-toggle').click()
  await expect(dialog.locator('.explain-page-preview img')).toBeVisible()
  await expect(dialog.locator('.explain-selection-quote')).toContainText('以原文公式图像为准')
  let request:Record<string,unknown>|undefined
  await page.route('**/api/papers/*/explain',async route=>{
    request=route.request().postDataJSON()
    await route.fulfill({json:answer('这是理想气体的状态方程。')})
  })
  await input.fill('各个符号是什么意思？')
  await input.press('Enter')
  await expect(dialog.locator('.explain-answer-text')).toContainText('状态方程')
  expect(request?.visual_kind).toBe('equation')
  expect(request?.bbox).toEqual([100,520,500,570])
  expect(request?.image_data_url).toMatch(/^data:image\/jpeg;base64,/)
  const conversations=await (await page.request.get(`/api/conversations?kind=explanation&paper_id=${paper.id}`)).json()
  const equation=conversations.items.find((item:{context?:Record<string,unknown>})=>item.context?.visual_kind==='equation')
  expect(equation?.context?.visual_label).toBe('Equation (3)')
  await page.screenshot({path:'test-artifacts/equation-question.png'})
})

test('table question images use the detected bounds without padding into adjacent content', async ({ page }) => {
  const {dialog,input}=await openQuestion(page)
  await dialog.getByRole('button',{name:'收起对话',exact:true}).click()
  const region=page.locator('[data-visual-id="fixture-table"]')
  const expected=await region.evaluate(element=>{
    const rectangle=element.getBoundingClientRect()
    const shell=element.closest('.pdfv-page-shell')!
    const canvas=shell.querySelector('canvas')!
    const bounds=shell.getBoundingClientRect()
    const width=Math.round(rectangle.width*canvas.width/bounds.width)
    const height=Math.round(rectangle.height*canvas.height/bounds.height)
    const scale=Math.min(1,1800/width)
    return {width:Math.round(width*scale),height:Math.round(height*scale)}
  })
  const box=await region.boundingBox()
  await page.mouse.move(box!.x+box!.width/2,box!.y+box!.height/2)
  await page.locator('.pdfv-visual-region-action.table').click()
  let imageData=''
  await page.route('**/api/papers/*/explain',async route=>{
    const body=route.request().postDataJSON()
    imageData=body.image_data_url
    await route.fulfill({json:answer('已读取完整表格。')})
  })
  await input.fill('请解释表中数据。')
  await input.press('Enter')
  await expect.poll(()=>imageData).toContain('data:image/')
  const dimensions=await page.evaluate(async data=>{
    const picture=new Image();picture.src=data;await picture.decode()
    return {width:picture.naturalWidth,height:picture.naturalHeight}
  },imageData)
  expect(Math.abs(dimensions.width-expected.width)).toBeLessThanOrEqual(1)
  expect(Math.abs(dimensions.height-expected.height)).toBeLessThanOrEqual(1)
})

test('a selection conversation can be hidden while answering and resumed after reading a different page', async ({ page }) => {
  let release!: () => void
  const waiting = new Promise<void>(resolve => { release = resolve })
  let calls = 0
  await page.route('**/api/papers/*/explain', async route => {
    calls++
    await waiting
    await route.fulfill({ json: answer('收起期间完成的回答。') })
  })
  try {
    const { dialog, input } = await openQuestion(page, false)
    await input.fill('这里的 verifier 做什么？')
    await input.press('Enter')
    await expect.poll(() => calls).toBe(1)
    await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    const resume = page.getByRole('button', { name: '阅读对话', exact: true })
    await expect(resume).toContainText('回答中')
    await page.getByRole('button', { name: '下一页', exact: true }).click()
    await resume.click()
    await expect(dialog.locator('.explain-user-question')).toHaveText('这里的 verifier 做什么？')
    await dialog.locator('.explain-context-toggle').click()
    await expect(dialog.locator('.explain-selection-quote')).toContainText('verifier')
    await input.fill('保留这条追问草稿')
    await dialog.getByRole('button', { name: '关闭', exact: true }).first().click()
    release()
    await expect(resume).toContainText('已回复')
    await resume.click()
    await expect(dialog.locator('.explain-answer-text')).toContainText('收起期间完成的回答')
    await expect(input).toHaveValue('保留这条追问草稿')
    expect(calls).toBe(1)
  } finally { release() }
})

const answerWithProvenance = (text: string) => ({
  ...answer(text),
  context_scope: 'related',
  facts: ['论文明确说明：函数执行器会验证模型输出的函数名和参数。'],
  inferences: ['这意味着用户看到的自然语言回答与函数调用应当经过不同的输出路径。'],
  unknowns: ['当前证据没有给出普通文字输出对应的完整函数签名。'],
  needs_more_context: false,
})

test('a hidden failure remains discoverable and keeps the question for a deliberate retry', async ({ page }) => {
  let release!: () => void
  const waiting = new Promise<void>(resolve => { release = resolve })
  let calls = 0
  await page.route('**/api/papers/*/explain', async route => {
    calls++
    if (calls === 1) { await waiting; await route.fulfill({ status: 504, json: { detail: '连接超时，请重试' } }) }
    else await route.fulfill({ json: answer('主动重试后保留的回答。') })
  })
  try {
    const { dialog, input } = await openQuestion(page, false)
    await input.fill('这里的 verifier 指什么？')
    await input.press('Enter')
    await expect.poll(() => calls).toBe(1)
    await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
    release()
    const resume = page.getByRole('button', { name: '阅读对话', exact: true })
    await expect(resume).toContainText('需重试')
    await resume.click()
    await expect(dialog.getByRole('alert')).toContainText('连接超时')
    await expect(input).toHaveValue('这里的 verifier 指什么？')
    expect(calls).toBe(1)
    await input.press('Enter')
    await expect(dialog.locator('.explain-answer-text')).toContainText('主动重试')
    expect(calls).toBe(2)
  } finally { release() }
})

test('reading history stays inside a narrow viewport and retains older pages after refresh', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 540 })
  const { paper, dialog } = await openQuestion(page, false)
  await dialog.getByRole('button', { name: '收起对话', exact: true }).click()
  const items = Array.from({ length: 55 }, (_, index) => ({
    id: 'history-' + index, kind: 'explanation', paper_id: paper.id,
    context: { page: 1, selected_text: 'verifier', visual: false },
    title: '保存的问题 ' + index, created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z',
    turn_count: 1, latest_status: 'completed', latest_question: '保存的问题 ' + index, latest_turn_id: 'turn-' + index,
  }))
  let reads = 0
  await page.route('**/api/conversations?**', async route => {
    const url = new URL(route.request().url())
    if (url.searchParams.has('context') || url.searchParams.get('kind') !== 'explanation') return route.continue()
    reads++
    const offset = Number(url.searchParams.get('offset') || 0)
    await route.fulfill({ json: { items: items.slice(offset, offset + 50), has_more: offset + 50 < items.length } })
  })
  await page.locator('.reading-chat-history > summary').click()
  const history = page.getByRole('region', { name: '本篇阅读对话', exact: true })
  await expect(history.getByRole('button').filter({ hasText: '保存的问题 49' })).toHaveCount(1)
  const box = await history.boundingBox()
  expect(box!.x).toBeGreaterThanOrEqual(8)
  expect(box!.x + box!.width).toBeLessThanOrEqual(382)
  expect(box!.y).toBeGreaterThanOrEqual(0)
  expect(box!.y + box!.height).toBeLessThanOrEqual(540)
  await history.locator('.reading-chat-more').click()
  await expect(history.getByRole('button').filter({ hasText: '保存的问题 54' })).toHaveCount(1)
  const before = reads
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect.poll(() => reads).toBeGreaterThan(before)
  await expect(history.getByRole('button').filter({ hasText: '保存的问题 54' })).toHaveCount(1)
  await history.getByRole('button').filter({ hasText: '保存的问题 54' }).scrollIntoViewIfNeeded()
  await expect(history.getByRole('button').filter({ hasText: '保存的问题 54' })).toBeInViewport()
  await page.screenshot({ path: 'test-artifacts/reading-chat-history-narrow.png' })
  await page.keyboard.press('Escape')
  await expect(history).not.toBeVisible()
})

test('the first view centers the question and reveals context and options only on demand', async ({ page }) => {
  const { dialog, input } = await openQuestion(page)
  await expect(input).toBeFocused()
  await expect(dialog.locator('.explain-page-preview')).not.toBeVisible()
  await expect(dialog.getByRole('combobox', { name: '证据范围', exact: true })).not.toBeVisible()
  await expect(dialog.getByRole('checkbox', { name: '允许联网查证', exact: true })).not.toBeVisible()
  await expect(dialog.getByRole('button', { name: '这张图展示了什么趋势？', exact: true })).toHaveCount(0)
  await dialog.locator('.explain-context-toggle').click()
  await expect(dialog.locator('.explain-page-preview img')).toBeVisible()
  await page.screenshot({ path: 'test-artifacts/chat-context-desktop.png' })
  await dialog.locator('.explain-context-toggle').click()
  await dialog.getByRole('button', { name: '提问选项', exact: true }).click()
  await expect(dialog.getByRole('combobox', { name: '证据范围', exact: true })).toHaveValue('auto')
  await expect(dialog.getByRole('checkbox', { name: '允许联网查证', exact: true })).not.toBeChecked()
  await page.screenshot({ path: 'test-artifacts/chat-options-desktop.png' })
  await dialog.getByRole('combobox', { name: '证据范围', exact: true }).selectOption('full')
  await input.click()
  await expect(dialog.getByRole('combobox', { name: '证据范围', exact: true })).not.toBeVisible()
  const box = await input.boundingBox()
  const drawer = await dialog.boundingBox()
  expect(box!.x - drawer!.x).toBeGreaterThanOrEqual(28)
  expect(drawer!.x + drawer!.width - box!.x - box!.width).toBeGreaterThanOrEqual(28)
  expect(Math.abs((box!.x - drawer!.x) - (drawer!.x + drawer!.width - box!.x - box!.width))).toBeLessThan(3)
  await page.screenshot({ path: 'test-artifacts/chat-empty-desktop.png' })
})

test('questions and answers stay in order while the composer sends follow-ups with image context', async ({ page }) => {
  const bodies: any[] = []
  await page.route('**/api/papers/*/explain', async route => {
    const body = route.request().postDataJSON()
    bodies.push(body)
    await route.fulfill({ json: answer(bodies.length === 1 ? '先看坐标：$QK^T$。' : '再看趋势：曲线逐步收敛。') })
  })
  const { dialog, input } = await openQuestion(page)
  await input.fill('坐标是什么意思？')
  await input.press('Shift+Enter')
  expect(bodies).toHaveLength(0)
  await input.press('Enter')
  await expect(dialog.locator('.explain-answer')).toContainText('先看坐标')
  await expect(input).toHaveValue('')
  await expect(input).toBeFocused()
  await expect(dialog.locator('.explain-answer .katex')).toBeVisible()
  await input.fill('为什么曲线会收敛？')
  await input.press('Enter')
  await expect(dialog.locator('.explain-turn')).toHaveCount(2)
  await expect(dialog.locator('.explain-turn').nth(0)).toContainText('坐标是什么意思？')
  await expect(dialog.locator('.explain-turn').nth(0)).toContainText('先看坐标')
  await expect(dialog.locator('.explain-turn').nth(1)).toContainText('为什么曲线会收敛？')
  await expect(dialog.locator('.explain-turn').nth(1)).toContainText('再看趋势')
  expect(bodies[0].image_data_url).toMatch(/^data:image\/(png|jpeg|webp);base64,/)
  expect(bodies[0].selected_text).toContain('Figure 1: Verifier-guided reasoning')
  expect(bodies[0].selected_text).not.toContain('second page')
  expect(bodies[0].context_scope).toBe('auto')
  expect(bodies[0].allow_external).toBe(false)
  expect(bodies[1].history).toEqual([{ question: '坐标是什么意思？', answer: '先看坐标：$QK^T$。' }])
  await page.screenshot({ path: 'test-artifacts/chat-conversation-desktop.png' })
})

test('the direct answer comes first and provenance stays quiet until expanded', async ({ page }) => {
  await page.route('**/api/papers/*/explain', route => route.fulfill({ json: answerWithProvenance('先给结论：模型输出会在满足函数调用格式时进入执行路径。') }))
  const { dialog, input } = await openQuestion(page)
  await input.fill('这里的两条输出路径有什么区别？')
  await input.press('Enter')
  await expect(dialog.locator('.explain-answer-text')).toContainText('先给结论')
  const provenance = dialog.locator('.explain-provenance')
  await expect(provenance).toBeVisible()
  await expect(provenance).not.toHaveAttribute('open', '')
  await expect(provenance.locator('.explain-provenance-group').first()).not.toBeVisible()
  await provenance.locator('summary').click()
  await expect(provenance.locator('.is-fact')).toContainText('函数执行器')
  await expect(provenance.locator('.is-inference')).toContainText('不同的输出路径')
  await expect(provenance.locator('.is-unknown')).toContainText('完整函数签名')
  await expect(dialog.locator('.explain-answer-details')).toContainText('相关章节')
})

test('an unsuccessful question keeps its draft and can be retried without a duplicate turn', async ({ page }) => {
  let calls = 0
  await page.route('**/api/papers/*/explain', async route => {
    calls++
    await route.fulfill(calls === 1 ? { status: 504, json: { detail: '连接超时，请重试' } } : { json: answer('重试后的答案。') })
  })
  const { dialog, input } = await openQuestion(page, false)
  await input.fill('这里的 verifier 指什么？')
  await dialog.getByRole('button', { name: '提问', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('连接超时')
  await expect(input).toHaveValue('这里的 verifier 指什么？')
  await dialog.getByRole('button', { name: '提问', exact: true }).click()
  await expect(dialog.locator('.explain-answer')).toContainText('重试后的答案')
  await expect(dialog.locator('.explain-turn')).toHaveCount(1)
  await expect(dialog.getByRole('alert')).toHaveCount(0)
})

test('composition does not submit and edits made during an answer survive its completion', async ({ page }) => {
  let calls = 0
  let release!: () => void
  const waiting = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/papers/*/explain', async route => {
    calls++
    await waiting
    await route.fulfill({ json: answer('第一轮回答。') })
  })
  const { dialog, input } = await openQuestion(page)
  await input.fill('第一轮问题')
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true, keyCode: 229 })
  await expect(dialog.locator('.explain-turn')).toHaveCount(0)
  expect(calls).toBe(0)
  try {
    await input.press('Enter')
    await expect.poll(() => calls).toBe(1)
    await input.press('Enter')
    await input.fill('下一轮还没写完的问题')
    expect(calls).toBe(1)
  } finally { release() }
  await expect(dialog.locator('.explain-answer')).toContainText('第一轮回答')
  await expect(input).toHaveValue('下一轮还没写完的问题')
  await expect(input).toBeFocused()
})

test('small screens keep question options visible without stacking them over an expanded preview', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 540 })
  const { dialog } = await openQuestion(page)
  await dialog.locator('.explain-context-toggle').click()
  await expect(dialog.locator('.explain-page-preview img')).toBeVisible()
  await dialog.getByRole('button', { name: '提问选项', exact: true }).click()
  await expect(dialog.locator('.explain-page-preview')).not.toBeVisible()
  const options = dialog.locator('.explain-options-popover')
  await expect(options).toBeInViewport({ ratio: 1 })
  await page.screenshot({ path: 'test-artifacts/chat-options-mobile.png' })
  await dialog.getByRole('combobox', { name: '证据范围', exact: true }).focus()
  await page.keyboard.press('Escape')
  await expect(options).not.toBeVisible()
  await expect(dialog).toBeVisible()
})

test('a long conversation scrolls independently and keeps the input inside a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 720, height: 660 })
  await page.route('**/api/papers/*/explain', route => route.fulfill({ json: answer('可追溯的解释。\n\n'.repeat(35)) }))
  const { dialog, input } = await openQuestion(page)
  await input.fill('这张图说明什么？')
  await input.press('Enter')
  await expect(dialog.locator('.explain-answer')).toContainText('可追溯的解释')
  await expect.poll(() => dialog.evaluate(element => getComputedStyle(element).transform)).toBe('matrix(1, 0, 0, 1, 0, 0)')
  const geometry = await dialog.evaluate(element => {
    const composer = element.querySelector('.explain-composer')!.getBoundingClientRect()
    const transcript = element.querySelector('.explain-transcript')!
    return { left: composer.left, right: composer.right, bottom: composer.bottom, height: innerHeight, width: innerWidth, scroll: transcript.scrollHeight > transcript.clientHeight, bodyWidth: document.documentElement.scrollWidth }
  })
  expect(geometry.bottom).toBeLessThanOrEqual(geometry.height)
  expect(geometry.left).toBeGreaterThanOrEqual(0)
  expect(geometry.right).toBeLessThanOrEqual(geometry.width)
  expect(geometry.bodyWidth).toBe(geometry.width)
  expect(geometry.scroll).toBe(true)
  await page.screenshot({ path: 'test-artifacts/chat-conversation-narrow.png' })
  await input.fill('再解释一下与前文的关系？')
  await input.press('Enter')
  await expect(dialog.locator('.explain-turn')).toHaveCount(2)
  await expect(dialog.locator('.explain-pending-turn')).toHaveCount(0)
  const followUp = await dialog.locator('.explain-question').last().boundingBox()
  const transcript = await dialog.locator('.explain-transcript').boundingBox()
  expect(followUp!.y - transcript!.y).toBeGreaterThanOrEqual(0)
  expect(followUp!.y - transcript!.y).toBeLessThanOrEqual(22)
  await expect(dialog.locator('.explain-answer').last()).toBeInViewport()
})
