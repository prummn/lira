import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

async function queueFixture(page:Page, paper:any, reading:any, options:{failed?:boolean;held?:boolean;full?:boolean}={}) {
  let jobs:any[]=[]
  const submitted:any[]=[], actions:string[]=[], promoted:string[]=[]
  let directCalls=0
  await page.route(`**/api/papers/${paper.id}/translate`,route=>{directCalls++;return route.fulfill({json:{text:'Unexpected direct translation'}})})
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`,route=>route.fulfill({json:{...reading,translations:{}}}))
  await page.route(`**/api/papers/${paper.id}/translation-jobs`,async route=>{
    if(route.request().method()==='GET')return route.fulfill({json:{jobs}})
    const payload=route.request().postDataJSON();submitted.push(payload)
    const ids=payload.paragraph_ids??reading.paragraphs.map((p:any)=>p.id)
    jobs=[{id:'fixture-job',paper_id:paper.id,mode:payload.mode,status:options.full?'queued':options.held?'running':options.failed?'failed':'completed',reason:options.full?'reading':null,error:null,model_name:'official fixture',completed:options.full?0:options.failed?ids.length-1:options.held?1:ids.length,total:ids.length,failed:options.failed?1:0,scope_total:options.full?ids.length:undefined,scope_skipped:options.full?3:undefined,scope_reason:options.full?'appendix_or_references':null,created_at:'2026-10-26T00:00:00',updated_at:'2026-10-26T00:00:00',items:ids.map((id:string,index:number)=>({id:'item-'+index,paragraph_id:id,original_paragraph_id:id,aliases:[id],page:1,status:options.full?'queued':options.failed&&index===0?'failed':options.held&&index>0?'running':'completed',phase:options.held&&index>0?'translating':null,error:options.failed&&index===0?'这一段暂时翻译失败':null,translation:!options.full&&!(options.held&&index>0)&&!(options.failed&&index===0)?{text:`批量译文 ${index+1}`,model:'official fixture'}:null}))}]
    return route.fulfill({json:jobs[0]})
  })
  await page.route('**/api/translation-jobs/fixture-job/*',route=>{
    const action=route.request().url().split('/').pop()!;actions.push(action)
    jobs[0]={...jobs[0],status:action==='pause'?'paused':action==='cancel'?'cancelled':'queued'}
    return route.fulfill({json:jobs[0]})
  })
  await page.route(`**/api/papers/${paper.id}/translation-jobs/prioritize`,route=>{
    const id=route.request().postDataJSON().paragraph_id;promoted.push(id)
    const job=jobs.find(job=>['queued','running'].includes(job.status)&&job.items.some((item:any)=>item.paragraph_id===id))??jobs.find(job=>job.status==='paused')??jobs[0]
    return route.fulfill({json:job})
  })
  return {submitted,actions,promoted,get directCalls(){return directCalls},get jobs(){return jobs}}
}

async function startSelectedQueue(page:Page) {
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await page.getByRole('button',{name:'批量翻译',exact:true}).click()
  await page.getByRole('button',{name:'全文',exact:true}).click()
  const checkboxes=page.locator('[data-testid="batch-paragraph-checkbox"]')
  await checkboxes.nth(0).check();await checkboxes.nth(1).check()
  await page.getByRole('button',{name:'开始批量翻译',exact:true}).click()
}

test('batch translation submits selected IDs once and reports persistent queue progress',async({page})=>{
  const {paper,reading}=await openPaper(page)
  const queue=await queueFixture(page,paper,reading)
  await startSelectedQueue(page)
  await expect(page.locator('[data-testid="translation-queue-progress"]')).toContainText('2 / 2')
  await expect(page.locator('[data-testid="translation-queue-progress"] .translation-queue-scope')).toHaveCount(0)
  expect(queue.submitted).toEqual([{mode:'selected',paragraph_ids:reading.paragraphs.slice(0,2).map((p:any)=>p.id)}])
  expect(queue.directCalls).toBe(0)
  await expect(page.locator('.batch-item-done')).toHaveCount(2)
})

test('failed queue items remain inspectable and can be retried',async({page})=>{
  const {paper,reading}=await openPaper(page)
  const queue=await queueFixture(page,paper,reading,{failed:true})
  await startSelectedQueue(page)
  await expect(page.locator('.batch-item-failed')).toHaveCount(1)
  await page.getByRole('button',{name:'重试失败项',exact:true}).click()
  expect(queue.actions).toEqual(['retry'])
  expect(queue.directCalls).toBe(0)
})

test('first result opens while the second is held and survives leaving, reload and mode changes',async({page})=>{
  const {paper,reading}=await openPaper(page)
  const queue=await queueFixture(page,paper,reading,{held:true})
  await startSelectedQueue(page)
  await expect(page.locator('[data-testid="translation-queue-progress"]')).toContainText('1 / 2')
  await page.screenshot({path:'test-artifacts/translation-queue-held-1440.png'})
  await page.locator('.batch-translation-heading').getByRole('button').click()
  await page.locator('.translation-paragraph-list button').first().click()
  await expect(page.locator('.translated-text')).toContainText('批量译文 1')
  await page.screenshot({path:'test-artifacts/translation-queue-reading-1440.png'})
  await page.getByRole('button',{name:'下一段',exact:true}).click()
  await expect(page.locator('.translation-panel')).toContainText('翻译中')
  await expect.poll(()=>queue.promoted).toContain(reading.paragraphs[1].id)
  expect(queue.directCalls).toBe(0)
  await page.getByRole('button',{name:'原文',exact:true}).click()
  await expect(page.locator('[data-testid="translation-queue-progress"]')).toContainText('1 / 2')
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await page.getByRole('button',{name:'上一页',exact:true}).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await expect(page.locator('.translated-text')).toContainText('批量译文 1')
  await page.getByRole('button',{name:'文献库',exact:true}).first().click()
  await page.getByRole('button',{name:'正在阅读',exact:true}).click()
  await expect(page.locator('[data-testid="translation-queue-progress"]')).toContainText('1 / 2')
  await page.reload()
  await page.getByRole('button',{name:'正在阅读',exact:true}).click()
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await expect(page.locator('.translated-text')).toContainText('批量译文 1')
  expect(queue.submitted).toHaveLength(1)
  expect(queue.actions).toEqual([])
})

test('full pretranslation progresses during reading and yields to a selected paragraph without narrow overflow',async({page})=>{
  const {paper,reading}=await openPaper(page)
  const queue=await queueFixture(page,paper,reading,{full:true})
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await page.getByRole('button',{name:'后台预译全文',exact:true}).click()
  const progress=page.locator('[data-testid="translation-queue-progress"]')
  await expect(progress).toContainText('0 /')
  await expect(progress).toContainText('正文范围')
  await expect(progress).toContainText('已跳过 3 段附录/参考文献')
  await expect(progress).not.toContainText('阅读结束后继续')
  expect(queue.submitted).toEqual([{mode:'full'}])
  queue.jobs[0]={...queue.jobs[0],status:'running',reason:null,completed:1,items:queue.jobs[0].items.map((item:any,index:number)=>index===0?{...item,status:'completed',translation:{text:'预译第一段已完成',model:'fixture'}}:item)}
  await expect(progress).toContainText('1 /')
  await page.getByRole('button',{name:'下一页',exact:true}).click()
  await page.getByRole('button',{name:'下一页',exact:true}).blur()
  await page.locator('.translation-paragraph-list button').first().click()
  await expect.poll(()=>queue.promoted).toContain(reading.paragraphs[1].id)
  queue.jobs[0]={...queue.jobs[0],status:'queued',reason:'foreground'}
  await expect(progress).toContainText('优先处理当前翻译、提问或分析')
  await page.getByRole('button',{name:'暂停翻译',exact:true}).click()
  await expect(page.locator('[data-testid="translation-queue-progress"]')).toContainText('已暂停')
  await page.getByRole('button',{name:'继续翻译',exact:true}).click()
  await page.setViewportSize({width:390,height:844})
  await expect(page.locator('[data-testid="translation-queue-progress"]')).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  expect(await page.evaluate(()=>document.documentElement.scrollHeight<=innerHeight)).toBe(true)
  await page.screenshot({path:'test-artifacts/translation-queue-full-390.png'})
  await page.getByRole('button',{name:'取消待译',exact:true}).click()
  expect(queue.actions).toEqual(['pause','resume','cancel'])
  await expect(page.locator('[data-testid="translation-queue-progress"]')).toContainText('已取消')
  expect(queue.directCalls).toBe(0)
})

test('queued boundary aliases recover a failed reading refresh without taking over the open translation',async({page})=>{
  const {paper,reading}=await openPaper(page)
  const queue=await queueFixture(page,paper,reading,{held:true})
  await startSelectedQueue(page)
  await page.locator('.batch-item-copy').first().click()
  await expect(page.locator('.translated-text')).toContainText('批量译文 1')
  let reloads=0
  const merged={...reading.paragraphs[1],id:'queue-merged-paragraph',text:'A complete sentence after the boundary merge.',source_text:'A complete sentence after the boundary merge.'}
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`,route=>{reloads++;if(reloads===1)return route.fulfill({status:503,json:{detail:'Temporary reading refresh failure'}});return route.fulfill({json:{...reading,paragraphs:[reading.paragraphs[0],merged,...reading.paragraphs.slice(2)],translations:{}}})})
  const job=queue.jobs[0]
  queue.jobs[0]={...job,status:'completed',completed:2,updated_at:'2026-10-26T00:01:00',items:[job.items[0],{...job.items[1],paragraph_id:merged.id,aliases:[reading.paragraphs[1].id,merged.id],status:'completed',phase:null,translation:{text:'合并后的完整译文',model:'official fixture'}}]}
  await expect(page.locator('[data-testid="translation-queue-progress"]')).toContainText('2 / 2')
  await expect.poll(()=>reloads).toBe(2)
  await expect(page.locator('.translated-text')).toContainText('批量译文 1')
  await page.getByRole('button',{name:'下一段',exact:true}).click()
  await expect(page.locator('.translated-text')).toContainText('合并后的完整译文')
  await page.getByText('对照原文',{exact:true}).click()
  await expect(page.locator('.translation-original')).toContainText(merged.text)
  expect(reloads).toBe(2)
  expect(queue.directCalls).toBe(0)
})

test('queue history and extra active jobs keep the reading area compact',async({page})=>{
  const {paper,reading}=await openPaper(page)
  const queue=await queueFixture(page,paper,reading,{held:true})
  await startSelectedQueue(page)
  const original=queue.jobs[0]
  queue.jobs.push(...Array.from({length:10},(_,index)=>({...original,id:'other-'+index,status:index<4?'queued':'completed',completed:index<4?0:2})))
  await expect(page.locator('.translation-queue-more')).toBeVisible()
  await expect(page.locator('.translation-queue-row:visible')).toHaveCount(2)
  const height=await page.locator('[data-testid="translation-queue-progress"]').evaluate(element=>element.getBoundingClientRect().height)
  expect(height).toBeLessThan(120)
  await page.locator('.translation-queue-more summary').click()
  await expect(page.locator('.translation-queue-row:visible')).toHaveCount(5)
  const extraHeight=await page.locator('.translation-queue-more > div').evaluate(element=>element.getBoundingClientRect().height)
  expect(extraHeight).toBeLessThanOrEqual(120)
  await page.locator('.translation-queue-more summary').click()
  await page.setViewportSize({width:390,height:844})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth&&document.documentElement.scrollHeight<=innerHeight)).toBe(true)
})

for(const [olderMode,olderStatus,newerStatus,label] of [['selected','running','cancelled','待翻译'],['full','running','cancelled','待翻译'],['selected','running','paused','待翻译'],['selected','paused','cancelled','已暂停']] as const)test(`${newerStatus} newer jobs do not hide an older ${olderMode} ${olderStatus} authorization`,async({page})=>{
  const {paper,reading}=await openPaper(page)
  const queue=await queueFixture(page,paper,reading,{held:true})
  await startSelectedQueue(page)
  const original=queue.jobs[0]
  const waiting={...original.items[1],status:'queued',translation:null}
  queue.jobs[0]={...original,mode:olderMode,status:olderStatus,items:[original.items[0],waiting]}
  queue.jobs.unshift({...original,id:'newer-cancelled-job',mode:olderMode==='full'?'selected':'full',status:newerStatus,completed:0,items:[{...waiting,id:'newer-copy',status:newerStatus==='paused'?'queued':'cancelled'}]})
  await expect(page.locator('.batch-translation-item').nth(1)).toContainText(label)
  await page.locator('.batch-item-copy').nth(1).click()
  if(olderStatus==='paused')expect(queue.promoted).toEqual([])
  else await expect.poll(()=>queue.promoted).toContain(reading.paragraphs[1].id)
  await expect(page.locator('.translation-panel')).toContainText(label)
  expect(queue.directCalls).toBe(0)
})

for(const entry of ['panel','pdf','retry'] as const)test(`paused full translation allows an explicit single paragraph from the ${entry} without resuming the rest`,async({page})=>{
  const {paper,reading}=await openPaper(page)
  reading.paragraphs[0].review_available=true
  const queue=await queueFixture(page,paper,reading,{full:true})
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await page.getByRole('button',{name:'后台预译全文',exact:true}).click()
  if(entry==='retry'){
    const full=queue.jobs[0]
    queue.jobs[0]={...full,failed:1,items:[{...full.items[0],status:'failed',error:'单段失败，请重试'},...full.items.slice(1)]}
  }
  await page.getByRole('button',{name:'暂停翻译',exact:true}).click()
  const full=queue.jobs[0],paragraph=reading.paragraphs[0]
  expect(full.status).toBe('paused')
  await page.route(`**/api/papers/${paper.id}/translation-jobs`,route=>{
    if(route.request().method()==='GET')return route.fulfill({json:{jobs:queue.jobs}})
    const payload=route.request().postDataJSON();queue.submitted.push(payload)
    expect(payload).toEqual({mode:'selected',paragraph_ids:[paragraph.id]})
    const selected={...full,id:'explicit-single-paragraph',mode:'selected',status:'completed',reason:null,failed:0,completed:1,total:1,items:[{...full.items[0],id:'explicit-item',status:'completed',error:null,translation:{text:'仅这一段的手选译文',model:'official fixture'}}]}
    queue.jobs.unshift(selected)
    return route.fulfill({json:selected})
  })
  await page.locator('.translation-paragraph-list button').first().click()
  await expect(page.locator('.translation-preview')).toContainText(paragraph.text)
  await expect(page.locator('.translation-panel')).toContainText('已暂停')
  await expect(page.locator('.translation-panel .translation-loading')).toHaveCount(0)
  await expect(page.locator('.translation-review')).toBeEnabled()
  expect(queue.promoted).toEqual([])
  const marker=page.locator('.pdfv-paragraph-marker').first(),box=await marker.boundingBox()
  await page.mouse.move(box!.x+box!.width/2,box!.y+box!.height/2)
  const hover=page.locator('.pdfv-paragraph-actions').getByRole('button',{name:'已暂停 · 翻译此段',exact:true})
  await expect(hover).toBeVisible()
  if(entry==='panel')await page.locator('.translation-panel').getByRole('button',{name:'翻译此段',exact:true}).click()
  else if(entry==='retry')await page.locator('.translation-error').getByRole('button',{name:'重试',exact:true}).click()
  else await hover.click()
  await expect(page.locator('.translated-text')).toContainText('仅这一段的手选译文')
  expect(queue.jobs.find(job=>job.id===full.id)?.status).toBe('paused')
  expect(full.items.slice(1).every((item:any)=>item.status==='queued'&&!item.translation)).toBe(true)
  expect(queue.submitted).toEqual([{mode:'full'},{mode:'selected',paragraph_ids:[paragraph.id]}])
  expect(queue.actions).toEqual(['pause'])
  expect(queue.promoted).toEqual([])
  expect(queue.directCalls).toBe(0)
  await page.getByRole('button',{name:'收起译文',exact:true}).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await expect(page.locator('.translated-text')).toContainText('仅这一段的手选译文')
  const cachedBox=await marker.boundingBox()
  await page.mouse.move(cachedBox!.x+cachedBox!.width/2,cachedBox!.y+cachedBox!.height/2)
  await page.locator('.pdfv-paragraph-actions').getByRole('button',{name:'展开译文',exact:true}).click()
  await expect(page.locator('.translated-text')).toContainText('仅这一段的手选译文')
  expect(queue.submitted).toHaveLength(2)
  expect(queue.promoted).toEqual([])
  expect(queue.directCalls).toBe(0)
})

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
  await page.route(`**/api/papers/${paper.id}/translation-jobs`, route => route.fulfill({json:{jobs:[]}}))
  await page.goto('/')
  await page.locator('.paper-row').filter({ hasText: paper.title }).first().locator('.paper-name > button').click()
  await expect(page.locator('.pdfv-canvas').first()).toBeVisible()
  return { paper, reading }
}

test('saved translations can be regenerated without losing readable text on failure', async ({ page }) => {
  const { paper, reading } = await openPaper(page)
  const paragraph = reading.paragraphs[0]
  reading.translations[paragraph.id] = {text:'原先保存的正确译文。',model:'fixture-model'}
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`, route=>route.fulfill({json:reading}))
  let finish: (()=>void) | undefined
  const bodies: any[] = []
  await page.route(`**/api/papers/${paper.id}/translate`, async route=>{
    bodies.push(route.request().postDataJSON())
    if(bodies.length===1){
      await new Promise<void>(resolve=>{finish=resolve})
      await route.fulfill({status:502,json:{detail:'模型未返回有效译文，请重新翻译。'}})
    }else{
      await route.fulfill({json:{text:'重新生成的完整译文。',model_version:'fixture-model',cached:false}})
    }
  })
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await expect(page.locator('.translated-text')).toHaveText('原先保存的正确译文。')
  await page.getByRole('button',{name:'重新翻译',exact:true}).click()
  await expect(page.getByRole('button',{name:'正在重新翻译',exact:true})).toBeDisabled()
  await expect(page.locator('.translated-text')).toHaveText('原先保存的正确译文。')
  expect(bodies[0]).toEqual({paragraph_id:paragraph.id,force:true})
  finish!()
  await expect(page.locator('.translation-error')).toContainText('模型未返回有效译文')
  await expect(page.locator('.translated-text')).toHaveText('原先保存的正确译文。')
  await page.getByRole('button',{name:'重新翻译',exact:true}).click()
  await expect(page.locator('.translated-text')).toHaveText('重新生成的完整译文。')
  expect(bodies).toHaveLength(2)
  expect(bodies[1].force).toBe(true)
  await page.getByRole('button',{name:'收起译文',exact:true}).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await expect(page.locator('.translated-text')).toHaveText('重新生成的完整译文。')
})

test('historical invalid translations show a retry entry instead of a saved result', async ({ page }) => {
  const {paper,reading}=await openPaper(page)
  const paragraph=reading.paragraphs[0]
  reading.translations={}
  reading.translation_errors={[paragraph.id]:'模型未返回有效译文，请重新翻译。原文已保留。'}
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`,route=>route.fulfill({json:reading}))
  await page.route(`**/api/papers/${paper.id}/translate`,route=>route.fulfill({json:{text:'恢复后的完整译文。',cached:false}}))
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await expect(page.locator('.translated-text')).toHaveCount(0)
  await expect(page.locator('.translation-error')).toContainText('模型未返回有效译文')
  await page.locator('.translation-error').getByRole('button',{name:'重试',exact:true}).click()
  await expect(page.locator('.translated-text')).toHaveText('恢复后的完整译文。')
  await expect(page.locator('.translation-error')).toHaveCount(0)
})

test('background polling cannot replace a regenerated translation with an older result', async ({ page }) => {
  const {paper,reading}=await openPaper(page)
  const paragraph=reading.paragraphs[0]
  const old={text:'后台原先保存的译文。',model:'fixture-model'}
  reading.translations[paragraph.id]=old
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`,route=>route.fulfill({json:reading}))
  let polls=0
  const job={id:'completed-before-retry',paper_id:paper.id,mode:'selected',status:'completed',reason:null,error:null,model_name:'fixture-model',completed:1,total:1,failed:0,created_at:'2026-10-30T01:00:00Z',updated_at:'2026-10-30T01:00:00Z',items:[{id:'old-item',paragraph_id:paragraph.id,original_paragraph_id:paragraph.id,aliases:[],status:'completed',phase:null,error:null,page:1,translation:old}]}
  await page.route(`**/api/papers/${paper.id}/translation-jobs`,route=>{polls++;return route.fulfill({json:{jobs:[{...job,updated_at:`2026-10-30T01:00:${String(polls).padStart(2,'0')}Z`}]}})})
  await page.route(`**/api/papers/${paper.id}/translate`,route=>route.fulfill({json:{text:'用户主动重译的新结果。',cached:false}}))
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await expect(page.locator('.translated-text')).toHaveText(old.text)
  await page.getByRole('button',{name:'重新翻译',exact:true}).click()
  await expect(page.locator('.translated-text')).toHaveText('用户主动重译的新结果。')
  const before=polls
  await expect.poll(()=>polls,{timeout:10000}).toBeGreaterThan(before)
  await expect(page.locator('.translated-text')).toHaveText('用户主动重译的新结果。')
})

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

test('selecting a translated passage opens paper Q&A with its English anchor', async ({ page }) => {
  const { paper, reading } = await openPaper(page)
  const translated = '译文中的这一小段应该可以直接拿来提问。'
  let explainBody: any = null
  await page.route(`**/api/papers/${paper.id}/translate`, route => route.fulfill({ json: { text: translated, provider: 'Fixture', cached: false } }))
  await page.route(`**/api/papers/${paper.id}/explain`, async route => {
    explainBody = route.request().postDataJSON()
    await route.fulfill({ json: { answer: '已结合英文原文回答。', provider: 'Fixture', mode: 'remote', citations: [], insufficient_evidence: false, context_scope: 'paragraph' } })
  })
  await page.getByRole('button', { name: '中英对照', exact: true }).click()
  const paragraph = page.locator('.pdfv-paragraph-marker').first()
  const box = await paragraph.boundingBox()
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)
  await page.locator('.pdfv-paragraph-actions').getByRole('button', { name: '翻译此段', exact: true }).click()
  await expect(page.locator('.translated-text')).toContainText(translated)
  await page.locator('.translated-text').evaluate(element => {
    const range = document.createRange(); range.selectNodeContents(element)
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
  })
  await expect(page.getByRole('button', { name: '解释所选', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '解释所选', exact: true }).click()
  const input = page.getByRole('textbox', { name: '向论文提问', exact: true })
  await input.fill('这句话具体是什么意思？')
  await input.press('Enter')
  await expect(page.locator('.explain-answer')).toContainText('已结合英文原文回答')
  expect(explainBody.translated_text).toBe(translated)
  expect(explainBody.selected_text).toBe(reading.paragraphs[0].source_text)
})

test('translated-selection actions stay inside the viewport at the right edge of the reading pane', async ({ page }) => {
  const { paper } = await openPaper(page)
  const translated = '这是一段足够长的译文，用来模拟右侧对照栏靠近屏幕边缘时的选区操作，用户仍然应该能够完整看到提问按钮并点击。'
  await page.route(`**/api/papers/${paper.id}/translate`, route => route.fulfill({ json: { text: translated, provider: 'Fixture', cached: false } }))
  await page.getByRole('button', { name: '中英对照', exact: true }).click()
  const paragraph = page.locator('.pdfv-paragraph-marker').first()
  const box = await paragraph.boundingBox()
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)
  await page.locator('.pdfv-paragraph-actions').getByRole('button', { name: '翻译此段', exact: true }).click()
  await expect(page.locator('.translated-text')).toContainText('足够长的译文')
  await page.locator('.translated-text').evaluate(element => {
    const text = element.lastChild ?? element
    const range = document.createRange()
    range.selectNodeContents(text)
    const selection = window.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)
    element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
  })
  const actions = page.locator('.selection-actions')
  await expect(actions).toBeVisible()
  const actionsBox = await actions.boundingBox()
  const viewport = await page.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight }))
  expect(actionsBox).not.toBeNull()
  expect(actionsBox!.x).toBeGreaterThanOrEqual(0)
  expect(actionsBox!.x + actionsBox!.width).toBeLessThanOrEqual(viewport.width)
  await expect(actions.getByRole('button', { name: '解释所选', exact: true })).toBeEnabled()
})

test('switching back to original clears the translation locator highlight', async ({ page }) => {
  const { paper } = await openPaper(page)
  await page.route(`**/api/papers/${paper.id}/translate`, route => route.fulfill({ json: { text: '译文保持在边栏。', provider: 'Fixture', cached: false } }))
  await page.getByRole('button', { name: '中英对照', exact: true }).click()
  const paragraph = page.locator('.pdfv-paragraph-marker').first()
  await expect(paragraph).toBeVisible()
  const box = await paragraph.boundingBox()
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)
  await page.locator('.pdfv-paragraph-actions').getByRole('button', { name: '翻译此段', exact: true }).click()
  await expect(page.locator('.translated-text')).toContainText('译文保持')
  await expect(page.locator('.pdfv-evidence-overlay')).toHaveCount(1)
  await page.getByRole('button', { name: '原文', exact: true }).click()
  await expect(page.locator('.pdfv-evidence-overlay')).toHaveCount(0)
})

test('the selected translation remains open while the PDF page changes', async ({ page }) => {
  const { paper } = await openPaper(page)
  await page.route(`**/api/papers/${paper.id}/translate`, route => route.fulfill({ json: { text: '跨页阅读仍保留这段译文。', provider: 'Fixture', cached: false } }))
  await page.getByRole('button', { name: '中英对照', exact: true }).click()
  const paragraph = page.locator('.pdfv-paragraph-marker').first()
  const box = await paragraph.boundingBox()
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)
  await page.locator('.pdfv-paragraph-actions').getByRole('button', { name: '翻译此段', exact: true }).click()
  await expect(page.locator('.translated-text')).toContainText('跨页阅读')
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.locator('.pdfv-page-input')).toHaveValue('2')
  await expect(page.locator('.translated-text')).toContainText('跨页阅读')
})

test('saving a highlight keeps the bilingual translation open without opening a note bubble', async ({ page }) => {
  const { paper } = await openPaper(page)
  await page.route(`**/api/papers/${paper.id}/translate`, route => route.fulfill({ json: { text: '高亮后译文仍停留在这里。', provider: 'Fixture', cached: false } }))
  await page.getByRole('button', { name: '中英对照', exact: true }).click()
  const paragraph = page.locator('.pdfv-paragraph-marker').first()
  const paragraphBox = await paragraph.boundingBox()
  await page.mouse.move(paragraphBox!.x + paragraphBox!.width / 2, paragraphBox!.y + paragraphBox!.height / 2)
  await page.locator('.pdfv-paragraph-actions').getByRole('button', { name: '翻译此段', exact: true }).click()
  await expect(page.locator('.translated-text')).toContainText('高亮后译文')
  await page.locator('.pdfv-text-layer[data-page-number="1"]').evaluate(element => {
    const span = Array.from(element.querySelectorAll('span[role="presentation"]')).find(item => item.textContent?.includes('verifier.'))!
    const text = span.firstChild!
    const start = text.textContent!.indexOf('verifier')
    const range = document.createRange(); range.setStart(text, start); range.setEnd(text, start + 'verifier'.length)
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    span.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}))
  })
  await page.getByRole('button', { name: '保存高亮', exact: true }).click()
  await expect(page.locator('.pdfv-note-highlight')).not.toHaveCount(0)
  await expect(page.locator('.translated-text')).toContainText('高亮后译文')
  await expect(page.getByRole('button', { name: '中英对照', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.pdfv-note-marker')).toHaveCount(0)
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

test('suspect paragraphs are checked before translating and the merged selection survives reload', async ({page})=>{
  const {paper,reading}=await openPaper(page)
  const first=reading.paragraphs[0]
  first.review_needed=true;first.review_available=true
  const merged={...first,id:'paragraph-reviewed',text:first.text+' The sentence continues across the next column.',source_text:first.source_text+'\nThe sentence continues across the next column.',review_needed:false,review_available:true}
  let reviewed=false,reviewCalls=0,translationCalls=0
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`,route=>route.fulfill({json:{...reading,paragraphs:reviewed?[merged,...reading.paragraphs.slice(1)]:reading.paragraphs}}))
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs/review`,async route=>{
    reviewCalls++
    expect(route.request().postDataJSON().paragraph_id).toBe(first.id)
    reviewed=true
    await route.fulfill({json:{...reading,paragraphs:[merged,...reading.paragraphs.slice(1)],selected_paragraph_id:merged.id,review:{checked:1,merged:1,uncertain:0,cached:false}}})
  })
  await page.route(`**/api/papers/${paper.id}/translate`,route=>{
    translationCalls++
    expect(reviewed).toBe(true)
    expect(route.request().postDataJSON().paragraph_id).toBe(merged.id)
    return route.fulfill({json:{text:'完整段落的译文。',provider:'Fixture',cached:false}})
  })
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await page.locator('.translation-panel').getByRole('button',{name:'翻译此段',exact:true}).click()
  await expect(page.locator('.translated-text')).toContainText('完整段落')
  await page.getByText('对照原文',{exact:true}).click()
  await expect(page.locator('.translation-original')).toContainText('next column')
  expect(reviewCalls).toBe(1);expect(translationCalls).toBe(1)
  await page.reload()
  await page.getByRole('button',{name:'正在阅读',exact:true}).click()
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await expect(page.locator('.translation-paragraph-list button').first()).toContainText('next column')
  expect(reviewCalls).toBe(1)
})

test('failed boundary checks preserve the selected paragraph and do not translate a fragment',async({page})=>{
  const {paper,reading}=await openPaper(page)
  reading.paragraphs[0].review_needed=true;reading.paragraphs[0].review_available=true
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`,route=>route.fulfill({json:reading}))
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs/review`,route=>route.fulfill({status:504,json:{detail:'分段检查暂时超时，原文未改动'}}))
  let calls=0
  await page.route(`**/api/papers/${paper.id}/translate`,route=>{calls++;return route.fulfill({json:{text:'Unexpected'}})})
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  await page.locator('.translation-paragraph-list button').first().click()
  await page.locator('.translation-panel').getByRole('button',{name:'翻译此段',exact:true}).click()
  await expect(page.locator('.translation-panel [role=alert]')).toContainText('原文未改动')
  await expect(page.locator('.translation-source').first()).toContainText(reading.paragraphs[0].text)
  expect(calls).toBe(0)
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
  reading.translations={[paragraph.id]:{text:'跨区域段落的已保存译文。',model:'Fixture'}}
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`,route=>route.fulfill({json:reading}))
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  const markers=page.locator('.pdfv-paragraph-marker')
  await expect(markers).toHaveCount(2)
  const lower=await markers.nth(1).boundingBox()
  await page.mouse.move(lower!.x+lower!.width/2,lower!.y+lower!.height/2)
  await expect(page.locator('.pdfv-paragraph-actions')).toBeVisible()
  const action=await page.locator('.pdfv-paragraph-actions').boundingBox()
  expect(action!.y).toBeGreaterThanOrEqual(lower!.y-action!.height-12)
  expect(action!.y).toBeLessThanOrEqual(lower!.y+10)
  expect(action!.x).toBeLessThanOrEqual(lower!.x+lower!.width+12)
  expect(action!.x+action!.width).toBeGreaterThanOrEqual(lower!.x-12)
  await expect(markers.nth(1)).toHaveClass(/hovered/)
  await expect(markers.first()).not.toHaveClass(/hovered/)
  await page.mouse.move(action!.x+action!.width/2,action!.y+action!.height/2,{steps:25})
  await expect(markers.nth(1)).toHaveClass(/hovered/)
  await page.mouse.down();await page.mouse.up()
  await expect(page.locator('.translated-text')).toContainText('跨区域段落的已保存译文')
})

test('translation action stays inside the PDF page when a paragraph touches the right edge', async ({ page }) => {
  const { paper, reading } = await openPaper(page)
  const paragraph = reading.paragraphs[0]
  const anchor = paragraph.anchors[0]
  const width = anchor.page_width ?? 612
  reading.paragraphs = [{ ...paragraph, anchors: [{ ...anchor, bbox: [width - 130, 120, width - 4, 185] }] }]
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`, route => route.fulfill({ json: reading }))
  await page.getByRole('button', { name: '中英对照', exact: true }).click()
  const marker = page.locator('.pdfv-paragraph-marker').first()
  await expect(marker).toBeVisible()
  const markerBox = await marker.boundingBox()
  await page.mouse.move(markerBox!.x + markerBox!.width / 2, markerBox!.y + markerBox!.height / 2)
  const action = page.locator('.pdfv-paragraph-actions')
  await expect(action).toBeVisible()
  const actionBox = await action.boundingBox()
  const pageBox = await marker.locator('xpath=ancestor::*[@data-page-number]').boundingBox()
  expect(actionBox!.x).toBeGreaterThanOrEqual(pageBox!.x)
  expect(actionBox!.x + actionBox!.width).toBeLessThanOrEqual(pageBox!.x + pageBox!.width)
})

for(const width of [1440,960])test(`cached translation action stays attached and clickable after paragraph top scrolls out at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:1000})
  const {paper,reading}=await openPaper(page)
  const paragraph=reading.paragraphs[0],anchor=paragraph.anchors[0]
  reading.paragraphs=[{...paragraph,anchors:[{...anchor,bbox:[70,300,anchor.page_width-70,460]}]}]
  reading.translations={[paragraph.id]:{text:'这是已保存的段落译文。',model:'Fixture'}}
  await page.route(`**/api/papers/${paper.id}/reading-paragraphs`,route=>route.fulfill({json:reading}))
  let modelRequests=0
  await page.route(`**/api/papers/${paper.id}/translate`,route=>{modelRequests++;return route.fulfill({status:500,json:{detail:'Cached text must not be regenerated'}})})
  await page.getByRole('button',{name:'中英对照',exact:true}).click()
  const marker=page.locator('.pdfv-paragraph-marker').first()
  await expect(marker).toBeVisible()
  await marker.scrollIntoViewIfNeeded()
  const before=await marker.boundingBox()
  await page.mouse.move(before!.x+before!.width/2,before!.y+20)
  const action=page.locator('.pdfv-paragraph-actions')
  await expect(action).toBeVisible()
  const actionBox=await action.boundingBox()
  expect(actionBox!.x).toBeLessThanOrEqual(before!.x+before!.width+12)
  expect(await action.locator('.pdfv-paragraph-action-label').evaluate(el=>el.getBoundingClientRect().width)).toBeGreaterThan(30)
  await page.locator('.pdfv-scroll').evaluate((el,top)=>{el.scrollTop+=top-el.getBoundingClientRect().top+40},before!.y)
  const clipped=await marker.boundingBox(),clip=await page.locator('.pdfv-scroll').boundingBox()
  await page.mouse.move(clipped!.x+clipped!.width/2,clip!.y+35)
  await expect(action).toBeVisible()
  await expect.poll(async()=>{const box=await action.boundingBox();return !!box&&box.y>=clip!.y+3&&box.y+box.height<=clip!.y+clip!.height}).toBe(true)
  const current=await action.boundingBox()
  await page.mouse.move(current!.x+current!.width/2,current!.y+current!.height/2,{steps:25})
  const button=action.getByRole('button',{name:'展开译文',exact:true})
  await expect(button).toBeVisible()
  expect(await button.evaluate(el=>{const box=el.getBoundingClientRect();return el.contains(document.elementFromPoint(box.x+box.width/2,box.y+box.height/2))})).toBe(true)
  await page.mouse.down();await page.mouse.up()
  await expect(page.locator('.translated-text')).toContainText('这是已保存的段落译文')
  expect(modelRequests).toBe(0)
})
