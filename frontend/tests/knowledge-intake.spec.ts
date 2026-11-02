import { expect, test } from '@playwright/test'

test('an accepted contextual example can be kept as a research object without rejecting its identity',async({page,request})=>{
  const paper=(await(await request.get('/api/papers')).json()).items[0]
  let contextual=true
  const payload=()=>({paper_id:paper.id,paper_status:'settled',relations:[],counts:{},candidates:[{id:'context-object',paper_id:paper.id,entity_id:'retained-identity',entity_type:'method',name:'Example system',normalized_name:'example system',aliases:[],description:'A retained object',role:'proposed',confidence:.99,status:'confirmed',evidence:[{chunk_id:'source',page:1,quote:'Original evidence'}],conflict:contextual?{_steward_context:{verdict:'incidental',reason:'A reproduced appendix example.'}}:{}}]})
  await page.route(`**/api/papers/${paper.id}/knowledge`,route=>route.fulfill({json:payload()}))
  await page.route('**/api/knowledge/candidates/context-object/confirm',route=>{contextual=false;return route.fulfill({json:payload().candidates[0]})})
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:paper.title}).getByRole('button',{name:paper.title,exact:true}).click()
  await page.locator('.notebook-panel').getByRole('button',{name:'知识摄取',exact:true}).click()
  const panel=page.locator('.knowledge-panel')
  await panel.getByRole('button',{name:/^已沉淀/}).click()
  await expect(panel.locator('.intake-context')).toContainText('A reproduced appendix example.')
  await panel.getByRole('button',{name:'保留为研究对象',exact:true}).click()
  await expect(panel.locator('.intake-context')).toHaveCount(0)
  await expect(panel).toContainText('Example system')
  await expect(panel.locator('.intake-status')).toHaveText('已确认')
})

test('paper knowledge separates review states and exposes sources without moving the reader', async ({page, request}) => {
  const papers = (await (await request.get('/api/papers')).json()).items
  const paper = papers[0]
  const evidence = {chunk_id:'anchor',page:1,section:'Method',quote:'MemGPT manages memory through function calls.',bbox:null,page_width:null,page_height:null}
  const item = (id:string,name:string,status:string,kind='method',role='proposed') => ({id,paper_id:paper.id,entity_id:status==='confirmed'?id:null,
    entity_type:kind,name,normalized_name:name.toLowerCase(),aliases:[],description:'A definition grounded in the source paper.',role,confidence:.91,status,
    evidence:[evidence],conflict:{},run_id:'first',model_version:null,prompt_version:null,layer:kind==='dataset'?'evaluation':kind==='concept'?'component':'primary',importance:'core'})
  let candidates=[item('method','MemGPT','new'),item('data','MSC','confirmed','dataset','used'),item('ignored','Irrelevant variant','rejected'),item('concept','external memory','new','concept','component')]
  const batchRequests:unknown[]=[]
  const payload=()=>({paper_id:paper.id,paper_status:'partially_settled',candidates,relations:[],counts:{}})
  await page.route(`**/api/papers/${paper.id}/knowledge`,route=>route.fulfill({json:payload()}))
  await page.route(`**/api/papers/${paper.id}/knowledge/review`,route=>{
    const body=route.request().postDataJSON();batchRequests.push(body)
    candidates=candidates.map(c=>body.candidate_ids.includes(c.id)?{...c,status:body.decision==='confirm'?'confirmed':'rejected'}:c)
    return route.fulfill({json:payload()})
  })
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:paper.title}).getByRole('button',{name:paper.title,exact:true}).click()
  await page.locator('.notebook-panel').getByRole('button',{name:'知识摄取',exact:true}).click()
  const panel=page.locator('.knowledge-panel')
  await expect(panel.locator('.knowledge-candidate')).toHaveCount(2)
  await expect(panel.getByText('MSC',{exact:true})).toHaveCount(0)
  await panel.getByRole('button',{name:/^已沉淀/}).click()
  await expect(panel.locator('.knowledge-candidate')).toHaveCount(1)
  await expect(panel).toContainText('MSC')
  await panel.getByRole('button',{name:/已忽略/}).click()
  await expect(panel).toContainText('Irrelevant variant')
  await panel.getByRole('button',{name:/待审阅/}).click()
  await panel.getByRole('searchbox',{name:'搜索知识条目'}).fill('MemGPT')
  await expect(panel.locator('.knowledge-candidate')).toHaveCount(1)
  await panel.getByRole('searchbox',{name:'搜索知识条目'}).fill('')
  const method=panel.locator('.knowledge-candidate').filter({has:page.locator('.intake-candidate-name').getByText('MemGPT',{exact:true})})
  await method.locator('summary').click()
  await expect(method.locator('blockquote')).toHaveText(evidence.quote)
  await expect(page.locator('.pdf-panel')).toBeVisible()
  await panel.getByRole('checkbox',{name:'选择 MemGPT'}).check()
  await panel.getByRole('button',{name:'确认所选',exact:true}).click()
  await expect(panel.locator('.knowledge-candidate')).toHaveCount(1)
  expect(batchRequests).toEqual([{candidate_ids:['method'],decision:'confirm'}])
  await panel.getByRole('button',{name:/^已沉淀/}).click()
  await expect(panel.locator('.knowledge-candidate')).toHaveCount(2)
})

test('paper knowledge keeps the current inventory visible during refresh', async ({page,request})=>{
  const paper=(await (await request.get('/api/papers')).json()).items[0]
  let hold=false
  let release!:()=>void
  const gate=new Promise<void>(resolve=>{release=resolve})
  await page.route(`**/api/papers/${paper.id}/knowledge`,async route=>{
    if(hold)await gate
    await route.fulfill({json:{paper_id:paper.id,paper_status:'candidates',relations:[],counts:{},candidates:[{id:'object',paper_id:paper.id,entity_id:null,entity_type:'method',name:'Persistent method',normalized_name:'persistent method',aliases:[],description:'Kept while refreshing.',role:'proposed',confidence:.9,status:'new',evidence:[{chunk_id:'source',page:1,section:'Method',quote:'Original evidence',bbox:null,page_width:null,page_height:null}],conflict:{},run_id:null,model_version:null,prompt_version:null}]}})
  })
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:paper.title}).getByRole('button',{name:paper.title,exact:true}).click()
  await page.locator('.notebook-panel').getByRole('button',{name:'知识摄取',exact:true}).click()
  const panel=page.locator('.knowledge-panel')
  await expect(panel).toContainText('Persistent method')
  hold=true
  await panel.getByRole('button',{name:'刷新',exact:true}).click()
  await expect(panel).toContainText('Persistent method')
  release()
})

test('a delayed refresh cannot replace a completed batch review', async ({page,request})=>{
  const paper=(await (await request.get('/api/papers')).json()).items[0]
  let status='new',hold=false,started=false
  let release!:()=>void
  const gate=new Promise<void>(resolve=>{release=resolve})
  const payload=()=>({paper_id:paper.id,paper_status:'candidates',relations:[],counts:{},candidates:[{id:'review-me',paper_id:paper.id,entity_id:null,entity_type:'method',name:'Reviewed method',normalized_name:'reviewed method',aliases:[],description:'Definition',role:'proposed',confidence:.9,status,evidence:[],conflict:{}}]})
  await page.route(`**/api/papers/${paper.id}/knowledge`,async route=>{
    const snapshot=payload()
    if(hold){started=true;await gate}
    await route.fulfill({json:snapshot})
  })
  await page.route(`**/api/papers/${paper.id}/knowledge/review`,route=>{
    status='confirmed'
    return route.fulfill({json:payload()})
  })
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:paper.title}).getByRole('button',{name:paper.title,exact:true}).click()
  await page.locator('.notebook-panel').getByRole('button',{name:'知识摄取',exact:true}).click()
  const panel=page.locator('.knowledge-panel')
  await panel.getByRole('checkbox',{name:'选择 Reviewed method'}).check()
  hold=true
  await panel.getByRole('button',{name:'刷新',exact:true}).click()
  await expect.poll(()=>started).toBe(true)
  await panel.getByRole('button',{name:'确认所选',exact:true}).click()
  await expect(panel.locator('.knowledge-candidate')).toHaveCount(0)
  const response=page.waitForResponse(r=>r.url().endsWith(`/papers/${paper.id}/knowledge`))
  release();await response
  await panel.getByRole('button',{name:/^已沉淀/}).click()
  await expect(panel.locator('.knowledge-candidate')).toHaveCount(1)
  await expect(panel).toContainText('Reviewed method')
})

test('reader dossier opens the actual related paper',async({page,request})=>{
  const papers=(await (await request.get('/api/papers')).json()).items
  const [paper,related]=papers
  await page.route(`**/api/papers/${paper.id}/knowledge`,route=>route.fulfill({json:{paper_id:paper.id,paper_status:'settled',relations:[],counts:{},candidates:[{id:'object',paper_id:paper.id,entity_id:'shared',entity_type:'method',name:'Shared method',normalized_name:'shared method',aliases:[],description:'A shared object',role:'proposed',status:'confirmed',evidence:[],conflict:{}}]}}))
  await page.route('**/api/knowledge/entities/shared',route=>route.fulfill({json:{id:'shared',name:'Shared method',entity_type:'method',aliases:[],description:'Definition',candidates:[],relations:[],evidence:[],links:[],history:[],papers:[{paper_id:related.id,title:related.title,role:'cited',status:'confirmed',evidence_count:1}]}}))
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:paper.title}).getByRole('button',{name:paper.title,exact:true}).click()
  await page.locator('.notebook-panel').getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.locator('.knowledge-panel').getByRole('button',{name:/^已沉淀/}).click()
  await page.getByRole('button',{name:'Shared method',exact:true}).click()
  await page.locator('.dossier-paper-row').click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.reader-title')).toContainText(related.title)
})
