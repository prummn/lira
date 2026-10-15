import { test, expect, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

async function openPaper(page:Page,filename='test-artifacts/import-fixture.pdf') {
  const buffer = Buffer.concat([await fs.readFile(path.resolve(filename)), Buffer.from(`\n% notes-${Date.now()}-${Math.random()}`)])
  const response = await page.request.post('/api/papers/import', {multipart:{file:{name:'reading-notes.pdf',mimeType:'application/pdf',buffer}}})
  expect(response.status()).toBe(201)
  const paper = await response.json()
  const title = `Reading annotations ${paper.id}`
  await page.request.patch(`/api/papers/${paper.id}`, {data:{title}})
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:title}).locator('.paper-name > button').click()
  await expect(page.locator('.pdfv-text-layer[data-page-number="1"] span').first()).toBeVisible()
  return paper
}

async function selectPassage(page:Page) {
  const layer = page.locator('.pdfv-text-layer[data-page-number="1"]')
  await layer.evaluate(element => {
    const spans = Array.from(element.querySelectorAll('span[role="presentation"]'))
    const first = spans.find(s=>s.textContent?.includes('We study'))!
    const last = spans.find(s=>s.textContent?.includes('verifier.'))!
    const range = document.createRange()
    range.setStart(first.firstChild!, 0);range.setEnd(last.firstChild!, last.textContent!.length)
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    last.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))
  })
  await expect(page.locator('.selection-actions')).toBeVisible()
}

test('saved multiline highlights render immediately, survive zoom and reload, and open the exact note', async ({page}) => {
  const paper = await openPaper(page)
  await selectPassage(page)
  await page.getByRole('button',{name:'保存高亮',exact:true}).click()
  await expect(page.locator('.pdfv-note-highlight')).not.toHaveCount(0, {timeout:8000})
  const note = (await (await page.request.get(`/api/papers/${paper.id}/notes`)).json())[0]
  expect(note.anchors[0].rects.length).toBeGreaterThan(1)
  const marks = page.locator('.pdfv-note-highlight')
  expect(await marks.count()).toBeGreaterThan(1)
  const firstWidth = (await marks.first().boundingBox())!.width
  await page.getByRole('button',{name:'放大',exact:true}).click()
  await expect.poll(async()=> (await marks.first().boundingBox())?.width??0).toBeGreaterThan(firstWidth)
  await page.getByRole('button',{name:'论文卡片',exact:true}).click()
  await page.getByRole('button',{name:'打开关联笔记',exact:true}).first().click()
  await expect(page.locator('.saved-note.is-focused')).toHaveAttribute('data-note-id',note.id)
  await page.reload()
  await page.getByRole('button',{name:'正在阅读',exact:true}).click()
  await expect(page.locator('.pdfv-note-highlight')).not.toHaveCount(0)
  const mark = page.locator('.pdfv-note-highlight').first()
  const rect = (await mark.boundingBox())!
  await page.mouse.click(rect.x+rect.width/2, rect.y+rect.height/2)
  await expect(page.locator('.saved-note.is-focused')).toHaveAttribute('data-note-id',note.id)
})

test('quote action focuses a stable source draft, then supports editing and deleting with PDF sync', async ({page}) => {
  const paper = await openPaper(page)
  await selectPassage(page)
  await page.getByRole('button',{name:'引用到笔记',exact:true}).click()
  const editor = page.getByRole('textbox',{name:'阅读笔记',exact:true})
  await expect(editor).toBeFocused({timeout:8000})
  await expect(page.locator('.note-source-preview')).toContainText('We study')
  await editor.fill('这里的 verifier 是否经过独立校准？')
  await page.getByRole('button',{name:'论文卡片',exact:true}).click()
  await page.getByRole('button',{name:'我的笔记',exact:true}).click()
  await expect(editor).toHaveValue('这里的 verifier 是否经过独立校准？')
  await page.getByRole('button',{name:'保存',exact:true}).click()
  const noteCard = page.locator('.saved-note').filter({hasText:'独立校准'})
  await expect(noteCard).toBeVisible()
  await expect(page.locator('.pdfv-note-highlight')).not.toHaveCount(0)
  await noteCard.getByRole('button',{name:'编辑笔记',exact:true}).click()
  await expect(editor).toBeFocused()
  await editor.fill('补充：需要核对 verifier 的训练数据。')
  await page.getByRole('button',{name:'保存修改',exact:true}).click()
  await expect(page.locator('.saved-note')).toContainText('核对 verifier')
  expect((await (await page.request.get(`/api/papers/${paper.id}/notes`)).json()).length).toBe(1)
  await page.locator('.saved-note').getByRole('button',{name:'删除笔记',exact:true}).click()
  await page.getByRole('button',{name:'确认删除',exact:true}).click()
  await expect(page.locator('.saved-note')).toHaveCount(0)
  await expect(page.locator('.pdfv-note-highlight')).toHaveCount(0)
})

test('a cross-page quote highlights both pages and either margin marker opens the same note',async({page})=>{
  const paper=await openPaper(page)
  await expect(page.locator('.pdfv-text-layer[data-page-number="2"] span').first()).toBeAttached()
  await page.locator('.pdfv-page-area').evaluate(element=>{
    const first=Array.from(element.querySelectorAll('.pdfv-text-layer[data-page-number="1"] span[role="presentation"]')).find(span=>span.textContent?.includes('verifier.'))!
    const last=Array.from(element.querySelectorAll('.pdfv-text-layer[data-page-number="2"] span[role="presentation"]')).find(span=>span.textContent?.includes('Our method uses'))!
    const range=document.createRange();range.setStart(first.firstChild!,0);range.setEnd(last.firstChild!,last.textContent!.length)
    const selection=window.getSelection()!;selection.removeAllRanges();selection.addRange(range)
    last.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))
  })
  await page.getByRole('button',{name:'引用到笔记',exact:true}).click()
  const editor=page.getByRole('textbox',{name:'阅读笔记',exact:true})
  await expect(page.locator('.note-source-preview')).toContainText('1, 2')
  await editor.fill('跨页原文：需要联系上下文核对。')
  await editor.press('Control+Enter')
  await expect(page.locator('.saved-note')).toHaveCount(1)
  const note=(await(await page.request.get(`/api/papers/${paper.id}/notes`)).json())[0]
  expect(note.anchors.map((anchor:{page:number})=>anchor.page)).toEqual([1,2])
  expect(note.source_text).not.toContain('保存')
  for(const number of [1,2]) {
    const shell=page.locator(`.pdfv-page-shell[data-page-number="${number}"]`)
    await expect(shell.locator('.pdfv-note-highlight')).not.toHaveCount(0)
    // No whole-page selection boxes, even when the range crosses page shells.
    for(const rect of note.anchors[number-1].rects)expect(rect[3]-rect[1]).toBeLessThan(30)
    await page.getByRole('button',{name:'论文卡片',exact:true}).click()
    const marker=shell.getByRole('button',{name:'打开关联笔记',exact:true})
    await marker.focus();await marker.press('Enter')
    await expect(page.locator('.saved-note.is-focused')).toHaveAttribute('data-note-id',note.id)
    await expect(page.locator('.saved-note')).toBeFocused()
  }
  await page.locator('.saved-note').getByRole('button',{name:'页 1–2',exact:true}).click()
  await expect(page.locator('.pdfv-page-input')).toHaveValue('1')
  await expect(page.locator('.pdfv-evidence-overlay')).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollTop)).toBe(0)
})

test('old bbox-only highlights regain exact text, group related notes and accept a thought without duplicating sources',async({page})=>{
  const paper=await openPaper(page)
  const source={kind:'highlight',content:'unreliable self-training feedback.',source_text:'unreliable self-training feedback.',page:1,bbox:[1,1,530,250]}
  const legacy=(await(await page.request.post(`/api/papers/${paper.id}/notes`,{data:source})).json())
  const related=(await(await page.request.post(`/api/papers/${paper.id}/notes`,{data:{...source,kind:'question',content:'同一段的另一个问题'}})).json())
  await page.reload();await page.getByRole('button',{name:'正在阅读',exact:true}).click()
  const marks=page.locator('.pdfv-note-highlight')
  await expect(marks).not.toHaveCount(0)
  expect((await marks.first().boundingBox())!.height).toBeLessThan(35)
  await expect(page.getByRole('button',{name:'打开关联笔记',exact:true})).toHaveCount(1)
  await expect(page.getByRole('button',{name:'打开关联笔记',exact:true})).toContainText('2')
  await page.getByRole('button',{name:'打开关联笔记',exact:true}).click()
  await expect(page.locator('.saved-note.is-focused')).toHaveCount(2)
  const oldCard=page.locator(`.saved-note[data-note-id="${legacy.id}"]`)
  await oldCard.getByRole('button',{name:'写下想法',exact:true}).click()
  const editor=page.getByRole('textbox',{name:'阅读笔记',exact:true})
  await expect(editor).toBeFocused();await expect(editor).toHaveValue('')
  await editor.fill('将反馈可靠性与校准结果联系起来。')
  await page.getByRole('button',{name:'保存修改',exact:true}).click()
  const notes=await(await page.request.get(`/api/papers/${paper.id}/notes`)).json()
  expect(notes).toHaveLength(2)
  const edited=notes.find((note:{id:string})=>note.id===legacy.id)
  expect(edited.kind).toBe('note');expect(edited.bbox).toEqual(source.bbox)
  expect(edited.source_text).toBe(source.source_text)
  expect(notes.some((note:{id:string})=>note.id===related.id)).toBe(true)
  // Existing marks must not swallow selection on the underlying text layer.
  await selectPassage(page)
  await expect(page.locator('.selection-actions')).toContainText('We study')
})

test('failed saves and deletes retain the source and draft, and switching drafts requires an explicit choice',async({page})=>{
  const paper=await openPaper(page)
  await selectPassage(page);await page.getByRole('button',{name:'引用到笔记',exact:true}).click()
  const editor=page.getByRole('textbox',{name:'阅读笔记',exact:true})
  await editor.fill('失败后也不能丢掉的想法。')
  await selectPassage(page);await page.getByRole('button',{name:'引用到笔记',exact:true}).click()
  await expect(page.locator('.note-draft-prompt')).toBeVisible()
  await expect(editor).toHaveValue('失败后也不能丢掉的想法。')
  await page.getByRole('button',{name:'继续编辑',exact:true}).click()
  await page.route(`**/api/papers/${paper.id}/notes`,async route=>{
    if(route.request().method()==='POST')await route.fulfill({status:503,json:{detail:'保存暂时失败，请重试'}})
    else await route.continue()
  })
  await page.getByRole('button',{name:'保存',exact:true}).click()
  await expect(page.locator('.notes-panel')).toContainText('保存暂时失败')
  await expect(editor).toHaveValue('失败后也不能丢掉的想法。')
  await expect(page.locator('.note-source-preview')).toContainText('We study')
  await expect(page.locator('.pdfv-note-highlight')).toHaveCount(0)
  await page.unroute(`**/api/papers/${paper.id}/notes`)
  await page.getByRole('button',{name:'保存',exact:true}).click()
  await expect(page.locator('.saved-note')).toHaveCount(1)
  const note=(await(await page.request.get(`/api/papers/${paper.id}/notes`)).json())[0]
  await page.route(`**/api/papers/${paper.id}/notes/${note.id}`,route=>route.fulfill({status:503,json:{detail:'删除暂时失败，请重试'}}))
  await page.getByRole('button',{name:'删除笔记',exact:true}).click()
  await page.getByRole('button',{name:'确认删除',exact:true}).click()
  await expect(page.locator('.notes-panel')).toContainText('删除暂时失败')
  await expect(page.locator('.saved-note')).toHaveCount(1)
  await expect(page.locator('.pdfv-note-highlight')).not.toHaveCount(0)
  await page.unroute(`**/api/papers/${paper.id}/notes/${note.id}`)
  await page.getByRole('button',{name:'确认删除',exact:true}).click()
  await expect(page.locator('.saved-note')).toHaveCount(0)
  await expect(page.locator('.pdfv-note-highlight')).toHaveCount(0)
})

test('a pending quote waits for an in-flight save and a new selection cannot alter an existing draft',async({page})=>{
  const paper=await openPaper(page)
  await selectPassage(page);await page.getByRole('button',{name:'引用到笔记',exact:true}).click()
  const editor=page.getByRole('textbox',{name:'阅读笔记',exact:true})
  await editor.fill('第一条想法')
  let release!:()=>void
  const held=new Promise<void>(resolve=>{release=resolve})
  await page.route(`**/api/papers/${paper.id}/notes`,async route=>{
    if(route.request().method()==='POST')await held
    await route.continue()
  })
  await page.getByRole('button',{name:'保存',exact:true}).click()
  await expect(editor).toBeDisabled()
  await page.locator('.pdfv-text-layer[data-page-number="2"]').evaluate(element=>{
    const span=Array.from(element.querySelectorAll('span[role="presentation"]')).find(span=>span.textContent?.includes('Our method uses'))!
    const range=document.createRange();range.selectNodeContents(span)
    const selection=window.getSelection()!;selection.removeAllRanges();selection.addRange(range)
    span.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))
  })
  await page.getByRole('button',{name:'引用到笔记',exact:true}).click()
  release()
  await expect(editor).toBeEditable()
  await expect(editor).toBeFocused()
  await expect(page.locator('.note-source-preview')).toContainText('Our method uses')
  await editor.fill('第二页的独立想法')
  await selectPassage(page)
  await page.getByRole('button',{name:'保存',exact:true}).click()
  await expect(page.locator('.saved-note')).toHaveCount(2)
  const notes=await(await page.request.get(`/api/papers/${paper.id}/notes`)).json()
  expect(notes).toHaveLength(2)
  expect(notes.find((note:{content:string})=>note.content==='第二页的独立想法').page).toBe(2)
})

test('saving a draft before switching retains the newly requested quote',async({page})=>{
  const paper=await openPaper(page)
  await page.getByRole('button',{name:'我的笔记',exact:true}).click()
  const editor=page.getByRole('textbox',{name:'阅读笔记',exact:true})
  await editor.fill('先保存这条无引用笔记。')
  await selectPassage(page);await page.getByRole('button',{name:'引用到笔记',exact:true}).click()
  await expect(page.locator('.note-draft-prompt')).toBeVisible()
  await page.locator('.note-editor-actions button.btn').click()
  await expect(page.locator('.saved-note')).toHaveCount(1)
  await expect(editor).toHaveValue('')
  await expect(editor).toBeFocused()
  await expect(page.locator('.note-source-preview')).toContainText('We study')
  expect((await(await page.request.get(`/api/papers/${paper.id}/notes`)).json()).length).toBe(1)
})

test('a delayed highlight does not replace the focus or source of a newer quote draft',async({page})=>{
  const paper=await openPaper(page)
  let release!:()=>void
  const held=new Promise<void>(resolve=>{release=resolve})
  await page.route(`**/api/papers/${paper.id}/notes`,async route=>{
    if(route.request().method()==='POST')await held
    await route.continue()
  })
  await selectPassage(page);await page.getByRole('button',{name:'保存高亮',exact:true}).click()
  await page.locator('.pdfv-text-layer[data-page-number="2"]').evaluate(element=>{
    const span=Array.from(element.querySelectorAll('span[role="presentation"]')).find(span=>span.textContent?.includes('Our method uses'))!
    const range=document.createRange();range.selectNodeContents(span)
    const selection=window.getSelection()!;selection.removeAllRanges();selection.addRange(range)
    span.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))
  })
  await page.getByRole('button',{name:'引用到笔记',exact:true}).click()
  const editor=page.getByRole('textbox',{name:'阅读笔记',exact:true})
  await editor.fill('第二页正在写的内容')
  release()
  await expect(page.locator('.saved-note')).toHaveCount(1)
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))))
  await expect(editor).toBeFocused()
  await expect(editor).toHaveValue('第二页正在写的内容')
  await expect(page.locator('.note-source-preview')).toContainText('Our method uses')
})

test('a background metadata reload cannot overwrite a newly saved note or PDF mark',async({page})=>{
  const paper=await openPaper(page)
  const collectionName=`Annotations ${paper.id}`
  await page.request.post('/api/collections',{data:{name:collectionName,description:'',color:'#536f89'}})
  await page.reload();await page.getByRole('button',{name:'正在阅读',exact:true}).click()
  await expect(page.locator('.pdfv-text-layer[data-page-number="1"] span').first()).toBeVisible()
  await page.locator('.notebook-head > button').click()
  let release!:()=>void,captured!:()=>void
  const held=new Promise<void>(resolve=>{release=resolve}),loaded=new Promise<void>(resolve=>{captured=resolve})
  await page.route(`**/api/papers/${paper.id}`,async route=>{
    const response=await route.fetch()
    captured();await held;await route.fulfill({response})
  })
  await page.locator('.notebook-memberships label').filter({hasText:collectionName}).getByRole('checkbox').check()
  await loaded
  await selectPassage(page);await page.getByRole('button',{name:'引用到笔记',exact:true}).click()
  await page.getByRole('textbox',{name:'阅读笔记',exact:true}).fill('这条新笔记不能被旧的加载结果覆盖。')
  await page.getByRole('button',{name:'保存',exact:true}).click()
  await expect(page.locator('.saved-note')).toHaveCount(1)
  const responseReceived=page.waitForResponse(response=>response.url().endsWith(`/api/papers/${paper.id}`))
  release();await responseReceived
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))))
  await expect(page.locator('.saved-note')).toHaveCount(1)
  await expect(page.locator('.pdfv-note-highlight')).not.toHaveCount(0)
})

test('real research PDF annotations survive page eviction and support text selection over existing marks',async({page})=>{
  test.skip(!process.env.RIW_NOTES_REAL_PDF,'Set RIW_NOTES_REAL_PDF to a local research PDF for visual regression.')
  const paper=await openPaper(page,process.env.RIW_NOTES_REAL_PDF!)
  const bodyIndex=await page.locator('.pdfv-text-layer[data-page-number="1"]').evaluate(layer=>Array.from(layer.querySelectorAll('span[role="presentation"]')).findIndex(span=>{
    const rect=span.getBoundingClientRect(),bounds=layer.getBoundingClientRect()
    return (span.textContent?.length??0)>25&&rect.top>bounds.top+bounds.height*.25&&rect.width>80
  }))
  expect(bodyIndex).toBeGreaterThanOrEqual(0)
  const span=page.locator('.pdfv-text-layer[data-page-number="1"] span[role="presentation"]').nth(bodyIndex)
  await expect(span).toBeVisible()
  const box=(await span.boundingBox())!
  await page.mouse.move(box.x+3,box.y+box.height/2);await page.mouse.down()
  await page.mouse.move(box.x+box.width-3,box.y+box.height/2,{steps:12});await page.mouse.up()
  await expect(page.locator('.selection-actions')).toBeVisible()
  await page.getByRole('button',{name:'引用到笔记',exact:true}).click()
  await page.getByRole('textbox',{name:'阅读笔记',exact:true}).fill('检查这条论述的适用范围；记号 $x_i$ 与后文一致。')
  await page.getByRole('button',{name:'保存',exact:true}).click()
  await expect(page.locator('.saved-note .katex')).toHaveCount(1)
  await page.screenshot({path:'test-artifacts/reading-notes-real.png'})
  await page.locator('.pdfv-page-input').fill(String(paper.page_count));await page.locator('.pdfv-page-input').press('Enter')
  await expect(page.locator('.pdfv-page-shell[data-page-number="1"] .pdfv-canvas')).toHaveCount(0)
  await page.locator('.saved-note').getByRole('button',{name:'页 1',exact:true}).click()
  await expect(page.locator('.pdfv-note-highlight')).not.toHaveCount(0)
  await expect(span).toBeVisible()
  const again=(await span.boundingBox())!
  await page.mouse.move(again.x+5,again.y+again.height/2);await page.mouse.down()
  await page.mouse.move(again.x+again.width-5,again.y+again.height/2,{steps:12});await page.mouse.up()
  await expect(page.locator('.selection-actions')).toBeVisible()
  await page.screenshot({path:'test-artifacts/reading-notes-real-selected.png'})
})
