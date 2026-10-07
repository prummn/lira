import { expect, test, type Page } from '@playwright/test'
import path from 'node:path'

// UI contract fixtures only: these responses make no claims about live model quality.
const remote = { provider:'FixtureProvider', mode:'remote', configured:true, translation_available:true,
  model:'fixture-model', wire_api:'responses', reasoning_effort:'high' }
async function realPaper(page:Page,title='Intelligence UI Research',suffix='intelligence fixture') {
  const response = await page.request.post('/api/papers/import', {multipart:{file:{
    name:`intelligence-${Date.now()}.pdf`, mimeType:'application/pdf',
    buffer: Buffer.concat([await (await import('node:fs/promises')).readFile(path.resolve('test-artifacts/import-fixture.pdf')),Buffer.from(`\n% ${suffix}\n`)]),
  }}})
  if(response.status()===409) {
    const papers=(await (await page.request.get('/api/papers')).json()).items
    const paper=papers.find((p:any)=>p.title===title&&!p.is_demo)
    return await (await page.request.get(`/api/papers/${paper.id}`)).json()
  }
  expect(response.status()).toBe(201)
  const created=await response.json()
  await page.request.patch(`/api/papers/${created.id}`,{data:{title}})
  return (await page.request.get(`/api/papers/${created.id}`)).json()
}
async function settings(page:Page, configured=true) {
  await page.route('**/api/settings',route=>route.fulfill({json:configured?remote:{...remote,provider:'MockProvider',mode:'extractive',configured:false,translation_available:false}}))
}

test('file batches require preflight, default opt-out and explain unavailable AI', async({page})=>{
  await settings(page,false)
  let imports=0
  await page.route('**/api/papers/import',async route=>{imports++;expect(route.request().postData()).toContain('name="analyze"');expect(route.request().postData()).toContain('false');await route.continue()})
  await page.goto('/')
  await page.locator('input[type=file]').setInputFiles({name:'preflight-invalid.pdf',mimeType:'application/pdf',buffer:Buffer.from('invalid pdf')})
  const dialog=page.getByRole('dialog',{name:'确认批量导入'})
  await expect(dialog).toBeVisible()
  expect(imports).toBe(0)
  await expect(dialog.getByRole('checkbox',{name:'导入后智能分析'})).not.toBeChecked()
  await expect(dialog.getByRole('checkbox',{name:'导入后智能分析'})).toBeDisabled()
  await expect(dialog).toContainText('先在后端配置远程模型')
  await dialog.getByRole('button',{name:'开始导入',exact:true}).click()
  await expect(page.locator('.import-report')).toContainText('不是有效 PDF')
  expect(imports).toBe(1)
})

test('URL opt-in remembers preference and collection retry reuses saved PDF',async({page})=>{
  const paper=await realPaper(page)
  const collection=await (await page.request.post('/api/collections',{data:{name:'Intelligence Retry Scope',description:'UI fixture'}})).json()
  await settings(page)
  let imports=0,memberships=0
  await page.route('**/api/papers/import-url',route=>{imports++;expect(route.request().postDataJSON().analyze).toBe(true);return route.fulfill({status:201,json:paper})})
  await page.route(`**/api/collections/${collection.id}/papers/${paper.id}`,route=>{memberships++;return route.fulfill(memberships===1?{status:503,json:{detail:'Collection fixture unavailable'}}:{json:{ok:true}})})
  await page.goto('/')
  await page.getByRole('button',{name:collection.name,exact:true}).click()
  await page.getByRole('button',{name:'链接导入',exact:true}).click()
  const dialog=page.getByRole('dialog')
  await dialog.getByRole('checkbox',{name:'导入后智能分析'}).check()
  await dialog.getByRole('textbox',{name:'论文链接'}).fill('https://example.org/real.pdf')
  await dialog.getByRole('button',{name:'下载并导入'}).click()
  await expect(dialog).toContainText('论文已保存')
  await dialog.getByRole('button',{name:'重试加入集合'}).click()
  await expect(dialog).toContainText('导入完成')
  expect(imports).toBe(1);expect(memberships).toBe(2)
  await dialog.getByRole('button',{name:'关闭',exact:true}).last().click()
  await page.locator('input[type=file]').setInputFiles(path.resolve('test-artifacts/import-fixture.pdf'))
  await expect(page.getByRole('dialog').getByRole('checkbox',{name:'导入后智能分析'})).toBeChecked()
})

test('batch analysis shows task progress, cancellation and stops polling at terminal state',async({page})=>{
  const paper=await realPaper(page)
  await settings(page)
  let status='unanalyzed',task:any=null,polls=0
  await page.route('**/api/papers?*',async route=>{const response=await route.fetch();const json=await response.json();json.items=json.items.map((p:any)=>p.id===paper.id?{...p,intelligence_status:status,intelligence_task:task}:p);await route.fulfill({json})})
  await page.route('**/api/intelligence/tasks{,?*}',route=>{
    if(route.request().method()==='POST') {expect(route.request().postDataJSON().paper_ids).toEqual([paper.id]);status='running';task={id:'fixture-task',paper_id:paper.id,status,phase:'extracting',completed_steps:1,total_steps:4,report:{},error:null};return route.fulfill({json:{tasks:[task]}})}
    const query=new URL(route.request().url()).searchParams
    expect(query.get('paper_id')).toBe(paper.id);expect(query.get('limit')).toBe('1')
    polls++;return route.fulfill({json:{tasks:task?[task]:[]}})
  })
  await page.route('**/api/intelligence/tasks/fixture-task/cancel',route=>{status='cancelled';task={...task,status,phase:'cancelled'};return route.fulfill({json:task})})
  await page.goto('/')
  const row=page.locator('.paper-row').filter({hasText:paper.title})
  await expect(row).toContainText('未进行智能分析')
  await row.getByRole('checkbox').check()
  await page.getByRole('button',{name:'分析所选论文'}).click()
  await expect(row).toContainText('1 / 4')
  await expect.poll(()=>polls).toBeGreaterThan(0)
  await page.getByRole('button',{name:'取消任务',exact:true}).click()
  await expect(row).toContainText('已取消')
  const stopped=polls
  await page.waitForTimeout(3000)
  expect(polls).toBe(stopped)
})

test('librarian scopes real papers, distinguishes claims and preserves conversation on source navigation',async({page})=>{
  const paper=await realPaper(page)
  const second=await realPaper(page,'Cross-paper Evidence Fixture','second librarian fixture')
  const note=await (await page.request.post(`/api/papers/${paper.id}/notes`,{data:{content:'NULL-PAGE-NOTE fixture: verify the assumption',kind:'question'}})).json()
  await settings(page)
  const source=paper.chunks.find((c:any)=>c.page===2)
  const citation={id:'fixture-source',paper_id:paper.id,title:paper.title,source_id:source.id,source_text:source.content,source_type:'paper',page:2,section:source.section,chunk_id:source.id,bbox:source.bbox,page_width:source.page_width,page_height:source.page_height}
  const secondSource=second.chunks.find((c:any)=>c.page===2)
  const secondCitation={...citation,id:'second-source',paper_id:second.id,title:second.title,source_id:secondSource.id,chunk_id:secondSource.id,source_text:secondSource.content}
  let asked=0
  await page.route('**/api/intelligence/ask',route=>{
    const body=route.request().postDataJSON();expect(body).not.toHaveProperty('paper_ids');expect(body).not.toHaveProperty('collection_id');asked++
    if(asked===2)expect(body.history).toHaveLength(2)
    return route.fulfill({json:{answer:'Evidence-backed fixture response',items:[
      {content:'The method verifies candidate traces.',kind:'fact',citations:[citation]},
      {content:'Both papers expose evidence sources.',kind:'comparison',citations:[citation,secondCitation]},
      {content:'Bibliographic record',kind:'metadata',citations:[{...citation,id:'metadata-source',source_type:'external_metadata',page:null,bbox:null}]},
      {content:'A personal research question.',kind:'user_note',citations:[{...citation,id:'note-source',source_id:note.id,source_type:'user',page:null,bbox:null,source_text:note.content}]},
      {content:'A possible comparison requires review.',kind:'inference',citations:[citation]},
    ],citations:[citation],provider:'FixtureProvider',mode:'remote',insufficient_evidence:false,limitations:['UI fixture; not live quality'],retrieved_paper_ids:[paper.id],queries:['verification'],coverage:{},usage:{input_tokens:100,output_tokens:30,total_tokens:130,model_calls:2,cache_hits:0},cached:false}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'AI 文献员',exact:true}).click()
  await expect(page.locator('.librarian-page')).toContainText('仅真实论文')
  await page.getByRole('textbox',{name:'向文献员提问'}).fill('哪些方法使用验证器？')
  await page.getByRole('button',{name:'提问',exact:true}).click()
  await expect(page.locator('.librarian-conversation')).toContainText('论文事实')
  await expect(page.locator('.librarian-conversation')).toContainText('AI 推断')
  await page.locator('.claim-metadata .claim-citations button').click()
  await expect(page.getByRole('dialog',{name:'论文信息',exact:true}).getByRole('textbox',{name:'标题',exact:true})).toHaveValue(paper.title)
  await page.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).first().click()
  await page.locator('.claim-user_note .claim-citations button').click()
  await expect(page.locator('.reader-title')).toContainText(paper.title)
  await expect(page.locator('.notebook-tabs .active')).toHaveText(/我的笔记/)
  await expect(page.locator('.saved-note')).toContainText('NULL-PAGE-NOTE fixture')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button',{name:'返回文献员',exact:true}).click()
  await page.locator('.claim-comparison .claim-citations button').nth(1).click()
  await expect(page.locator('.reader-title')).toContainText(second.title)
  await expect(page.getByRole('textbox',{name:'页码',exact:true})).toHaveValue('2')
  await page.getByRole('button',{name:'返回文献员',exact:true}).click()
  await expect(page.locator('.librarian-conversation')).toContainText('The method verifies candidate traces.')
  await page.getByRole('textbox',{name:'向文献员提问'}).fill('证据有什么局限？')
  await page.getByRole('button',{name:'提问',exact:true}).click()
  await expect(page.locator('.librarian-answer')).toHaveCount(2)
  await page.setViewportSize({width:1080,height:900})
  await page.screenshot({path:'test-artifacts/librarian-1080.png',fullPage:true})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await page.getByRole('button',{name:'设置',exact:true}).click()
  await page.getByRole('button',{name:'深色',exact:true}).click()
  await page.getByRole('combobox',{name:'语言',exact:true}).selectOption('en-US')
  await page.getByRole('button',{name:'AI Librarian',exact:true}).click()
  await expect(page.locator('.librarian-page')).toContainText('Paper fact')
  await expect(page.locator('html')).toHaveClass(/theme-dark/)
  await page.screenshot({path:'test-artifacts/librarian-dark-en-1080.png',fullPage:true})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await page.setViewportSize({width:1440,height:1000})
  await page.screenshot({path:'test-artifacts/librarian-dark-en-1440.png',fullPage:true})
})

test('Notebook keeps PDF and cached card available, reports coverage honestly, and uses scoped retrieval',async({page})=>{
  const paper=await realPaper(page)
  await settings(page)
  let complete=false
  const report={coverage:{total_windows:2,processed_windows:2,total_chars:4000,processed_chars:4000,complete:true},usage:{input_tokens:120,output_tokens:35,remote_calls:2,cache_hits:1,unknown_usage_calls:1},citation_count:6,semantic_verification:'not_automatically_proven',invalid_entries:2,rejections:[{phase:'extract',window_index:0,field:'facts[0]',reason:'quote_not_found'},{phase:'synthesize',field:'section_summaries[2]',reason:'section_mismatch'}]}
  const task=()=>({id:'notebook-task',paper_id:paper.id,status:complete?'completed':'running',phase:complete?'complete':'extracting',completed_steps:complete?3:1,total_steps:3,report:complete?report:{},error:null,updated_at:complete?'finished':'processing'})
  const detail=()=>({...paper,intelligence_status:task().status,intelligence_task:task(),intelligence_report:complete?report:null})
  await page.route('**/api/papers?*',async route=>{const result=await (await route.fetch()).json();result.items=result.items.map((p:any)=>p.id===paper.id?detail():p);await route.fulfill({json:result})})
  await page.route(`**/api/papers/${paper.id}`,route=>route.fulfill({json:detail()}))
  await page.route('**/api/intelligence/tasks{,?*}',route=>route.fulfill({json:{tasks:[task()]}}))
  let requests=0
  await page.route('**/api/intelligence/ask',route=>{requests++;expect(route.request().postDataJSON().paper_ids).toEqual([paper.id]);return route.fulfill({json:{answer:'Scoped retrieval fixture',items:[{content:'Supported by this paper.',kind:'fact',citations:[]}],citations:[],provider:'FixtureProvider',mode:'remote',insufficient_evidence:false,limitations:[],retrieved_paper_ids:[paper.id],queries:['verifier'],coverage:{},usage:{},cached:false}})})
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:paper.title}).locator('.paper-name > button').click()
  await expect(page.locator('.pdfv-canvas')).toBeVisible()
  await expect(page.locator('.analysis-control')).toContainText('1 / 3')
  await expect(page.locator('.paper-card')).toBeVisible()
  await expect(page.locator('.analyze-btn')).toHaveCount(0)
  complete=true
  await expect(page.locator('.analysis-control')).toContainText('智能分析完成')
  await page.locator('.analysis-report summary').click()
  await expect(page.locator('.analysis-report')).toContainText('2 / 2')
  await expect(page.locator('.analysis-report')).toContainText('部分调用未返回用量')
  await expect(page.locator('.analysis-report')).toContainText('6')
  await expect(page.locator('.analysis-report')).toContainText('仍需复核')
  await expect(page.locator('.analysis-report')).toContainText('未通过核验的条目 · 2')
  await expect(page.locator('.analysis-report')).toContainText('原文引句未匹配 · 1')
  await expect(page.locator('.analysis-report')).toContainText('章节标签与证据不符 · 1')
  await page.getByRole('button',{name:'问论文',exact:true}).click()
  await page.getByRole('textbox',{name:'问论文',exact:true}).fill('这篇论文如何验证证据？')
  await page.getByRole('button',{name:'提问',exact:true}).click()
  await expect(page.locator('.ask-answer')).toContainText('Supported by this paper.')
  expect(requests).toBe(1)
  await expect(page.locator('.pdfv-canvas')).toBeVisible()
  await page.screenshot({path:'test-artifacts/intelligence-notebook-1440.png'})
})

test('librarian discards stale requests after scope change and offers a useful retry',async({page})=>{
  await realPaper(page);await settings(page)
  let calls=0
  await page.route('**/api/intelligence/ask',async route=>{
    calls++
    if(calls===1){await new Promise(resolve=>setTimeout(resolve,1200));await route.fulfill({json:{answer:'STALE ANSWER MUST NOT APPEAR',items:[],citations:[],provider:'FixtureProvider',mode:'remote',insufficient_evidence:false,limitations:[],retrieved_paper_ids:[],queries:[],coverage:{},usage:{},cached:false}}).catch(()=>{});return}
    if(calls===2){await route.fulfill({status:503,json:{detail:'Fixture retrieval unavailable'}});return}
    await route.fulfill({json:{answer:'Retried scoped answer',items:[],citations:[],provider:'FixtureProvider',mode:'remote',insufficient_evidence:true,limitations:['Sources are insufficient'],retrieved_paper_ids:[],queries:[],coverage:{},usage:{},cached:false}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'AI 文献员',exact:true}).click()
  const question=page.getByRole('textbox',{name:'向文献员提问'})
  await question.fill('请查找论文中的证据')
  await page.getByRole('button',{name:'提问',exact:true}).click()
  await page.getByRole('combobox',{name:'检索范围'}).selectOption('selected')
  await expect(page.locator('.librarian-dialogue')).toContainText('范围已改变')
  await page.waitForTimeout(1500)
  await expect(page.locator('.librarian-dialogue')).not.toContainText('STALE ANSWER')
  await page.getByRole('combobox',{name:'检索范围'}).selectOption('')
  await page.getByRole('button',{name:'提问',exact:true}).click()
  await expect(page.getByRole('alert')).toContainText('Fixture retrieval unavailable')
  await page.getByRole('button',{name:'重试',exact:true}).click()
  await expect(page.locator('.librarian-answer')).toContainText('当前材料不足以确认')
  await expect(page.locator('.librarian-answer')).toContainText('Retried scoped answer')
})

test('librarian uses server scopes and limits explicit selection to fifty papers',async({page})=>{
  const paper=await realPaper(page)
  await settings(page)
  const papers=Array.from({length:51},(_,i)=>({...paper,id:`scope-paper-${i}`,title:`Scope Paper ${i+1}`,collection_ids:['fixture-collection']}))
  await page.route('**/api/papers?*',route=>route.fulfill({json:{items:papers,total:papers.length}}))
  await page.route('**/api/collections',route=>route.fulfill({json:{items:[{id:'fixture-collection',name:'Large Scope Collection',description:'',color:'#536f89',paper_count:51}]}}))
  const requests:any[]=[]
  await page.route('**/api/intelligence/ask',route=>{
    requests.push(route.request().postDataJSON())
    return route.fulfill({json:{answer:`Scope response ${requests.length}`,items:[],citations:[],provider:'FixtureProvider',mode:'remote',insufficient_evidence:false,limitations:[],retrieved_paper_ids:[],queries:[],coverage:{},usage:{},cached:false}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'AI 文献员',exact:true}).click()
  const question=page.getByRole('textbox',{name:'向文献员提问'})
  await question.fill('检查全库')
  await page.getByRole('button',{name:'提问',exact:true}).click()
  await expect(page.locator('.librarian-answer')).toContainText('Scope response 1')
  expect(requests[0]).not.toHaveProperty('paper_ids');expect(requests[0]).not.toHaveProperty('collection_id')
  await page.getByRole('combobox',{name:'检索范围'}).selectOption('fixture-collection')
  await question.fill('检查集合')
  await page.getByRole('button',{name:'提问',exact:true}).click()
  await expect(page.locator('.librarian-answer')).toContainText('Scope response 2')
  expect(requests[1].collection_id).toBe('fixture-collection');expect(requests[1]).not.toHaveProperty('paper_ids')
  await page.getByRole('combobox',{name:'检索范围'}).selectOption('selected')
  const choices=page.locator('.librarian-paper-selection input[type=checkbox]')
  await expect(choices).toHaveCount(51)
  for(let i=0;i<50;i++)await choices.nth(i).check()
  await expect(choices.nth(50)).toBeDisabled()
  await expect(page.locator('.librarian-paper-selection')).toContainText('最多 50 篇')
  await question.fill('检查指定论文')
  await page.getByRole('button',{name:'提问',exact:true}).click()
  await expect(page.locator('.librarian-answer')).toContainText('Scope response 3')
  expect(requests[2].paper_ids).toHaveLength(50);expect(requests[2]).not.toHaveProperty('collection_id')
  await choices.nth(0).uncheck()
  await expect(choices.nth(50)).toBeEnabled()
})

test('partial reanalysis retains published card coverage and shows its attempt separately',async({page})=>{
  const paper=await realPaper(page)
  await settings(page)
  let started=false,partial=false
  const published={coverage:{total_windows:3,processed_windows:3,complete:true},citation_count:9,usage:{input_tokens:110,output_tokens:40,remote_calls:2}}
  const attempt={coverage:{total_windows:3,processed_windows:1,complete:false},retained_previous_card:true,citation_count:1,usage:{input_tokens:40,output_tokens:5,remote_calls:1}}
  const task=()=>({id:started?'partial-attempt':'published-task',paper_id:paper.id,status:partial?'partial':started?'running':'completed',phase:partial?'partial':started?'extracting':'complete',completed_steps:started?1:3,total_steps:3,report:partial?attempt:started?{}:published,error:null,updated_at:partial?'finished':'processing'})
  const detail=()=>({...paper,intelligence_status:task().status,intelligence_task:task(),intelligence_report:published,analysis:{...paper.analysis,provider:'FixtureProvider',mode:'remote',card:{...paper.analysis?.card,one_sentence_summary:{content:'Previously published research card',evidence_ids:[]}}}})
  await page.route('**/api/papers?*',async route=>{const json=await (await route.fetch()).json();json.items=json.items.map((p:any)=>p.id===paper.id?detail():p);await route.fulfill({json})})
  await page.route(`**/api/papers/${paper.id}`,route=>route.fulfill({json:detail()}))
  await page.route('**/api/intelligence/tasks{,?*}',route=>{if(route.request().method()==='POST')started=true;return route.fulfill({json:{tasks:[task()]}})})
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:paper.title}).locator('.paper-name > button').click()
  await expect(page.locator('.paper-card')).toContainText('Previously published research card')
  await page.getByRole('button',{name:'重新分析全文',exact:true}).click()
  await expect(page.locator('.analysis-control')).toContainText('1 / 3')
  await page.locator('.analysis-published-report summary').click()
  await expect(page.locator('.analysis-published-report')).toContainText('3 / 3')
  await page.locator('.analysis-published-report summary').click()
  partial=true
  await expect(page.locator('.analysis-control')).toContainText('保留上一版卡片')
  await page.locator('.analysis-published-report summary').click()
  await expect(page.locator('.analysis-published-report')).toContainText('3 / 3')
  await page.locator('.analysis-attempt-report summary').click()
  await expect(page.locator('.analysis-attempt-report')).toContainText('1 / 3')
  await expect(page.locator('.paper-card')).toContainText('Previously published research card')
})

for(const terminalStatus of ['failed','cancelled'] as const)test(`a ${terminalStatus} retry keeps the published card report`,async({page})=>{
  const paper=await realPaper(page)
  await settings(page)
  let started=false,terminal=false
  const published={coverage:{total_windows:3,processed_windows:3,complete:true},citation_count:9,usage:{input_tokens:110,output_tokens:40,remote_calls:2}}
  const attempt={coverage:{total_windows:3,processed_windows:1,complete:false},usage:{input_tokens:40,output_tokens:5,remote_calls:1}}
  const running=()=>({id:'retry-task',paper_id:paper.id,status:'running',phase:'extracting',completed_steps:1,total_steps:3,report:{},error:null})
  const terminalTask=()=>({...running(),status:terminalStatus,phase:terminalStatus,error:terminalStatus==='failed'?'Retry failed safely':null,report:attempt})
  const detail=()=>({...paper,intelligence_status:started?(terminal?'running':'completed'):'completed',intelligence_task:started?running():{id:'published-task',paper_id:paper.id,status:'completed',phase:'complete',completed_steps:3,total_steps:3,report:published,error:null},intelligence_report:published,analysis:{...paper.analysis,provider:'FixtureProvider',mode:'remote',card:{...paper.analysis?.card,one_sentence_summary:{content:'Published card must remain visible',evidence_ids:[]}}}})
  await page.route('**/api/papers?*',async route=>{const json=await (await route.fetch()).json();json.items=json.items.map((p:any)=>p.id===paper.id?detail():p);await route.fulfill({json})})
  await page.route(`**/api/papers/${paper.id}`,route=>route.fulfill({json:detail()}))
  await page.route('**/api/intelligence/tasks{,?*}',async route=>{
    if(route.request().method()==='POST'){started=true;await route.fulfill({json:{tasks:[running()]}});return}
    terminal=true;await route.fulfill({json:{tasks:[terminalTask()]}})
  })
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:paper.title}).locator('.paper-name > button').click()
  await expect(page.locator('.paper-card')).toContainText('Published card must remain visible')
  await page.getByRole('button',{name:'重新分析全文',exact:true}).click()
  await expect(page.locator('.analysis-control')).toContainText('1 / 3')
  await expect(page.locator('.analysis-control')).toContainText(terminalStatus==='failed'?'分析失败':'已取消')
  await expect(page.locator('.paper-card')).toContainText('Published card must remain visible')
  await page.locator('.analysis-published-report summary').click()
  await expect(page.locator('.analysis-published-report')).toContainText('3 / 3')
  await expect(page.locator('.analysis-published-report')).not.toContainText('1 / 3')
  await expect(page.locator('.analysis-control')).toContainText('1 / 3')
})

for(const failSecondBatch of [false,true])test(`bulk analysis submits paginated selections sequentially${failSecondBatch?' and retains only unqueued papers after failure':''}`,async({page})=>{
  const paper=await realPaper(page)
  await settings(page)
  const papers=Array.from({length:201},(_,i)=>({...paper,id:`bulk-paper-${i}`,title:`Bulk Research ${String(i).padStart(3,'0')}`,intelligence_status:'unanalyzed',intelligence_task:null,collection_ids:[]}))
  const offsets:number[]=[]
  await page.route('**/api/papers?*',route=>{
    const offset=Number(new URL(route.request().url()).searchParams.get('offset')??0)
    offsets.push(offset)
    return route.fulfill({json:{items:papers.slice(offset,offset+200),total:papers.length}})
  })
  const submitted:string[][]=[],tasks=new Map<string,any>()
  let releaseFirst:()=>void=()=>{}
  await page.route('**/api/intelligence/tasks{,?*}',async route=>{
    if(route.request().method()==='GET'){
      const task=tasks.get(new URL(route.request().url()).searchParams.get('paper_id')??'')
      await route.fulfill({json:{tasks:task?[task]:[]}});return
    }
    const ids=route.request().postDataJSON().paper_ids as string[]
    submitted.push(ids)
    if(submitted.length===1)await new Promise<void>(resolve=>{releaseFirst=resolve})
    if(failSecondBatch&&submitted.length===2){await route.fulfill({status:503,json:{detail:'Second batch temporarily unavailable'}});return}
    const batch=ids.map(id=>({id:`bulk-task-${id}`,paper_id:id,status:'queued',phase:'queued',completed_steps:0,total_steps:4,report:{},error:null}))
    for(const task of batch)tasks.set(task.paper_id,task)
    await route.fulfill({json:{tasks:batch}})
  })
  await page.goto('/')
  await expect(page.locator('.paper-row')).toHaveCount(201)
  expect([...new Set(offsets)]).toEqual([0,200])
  await page.getByRole('checkbox',{name:'选择当前列表',exact:true}).check()
  await page.getByRole('button',{name:'分析所选论文',exact:true}).click()
  await expect.poll(()=>submitted.length).toBe(1)
  expect(submitted[0]).toHaveLength(200)
  await page.waitForTimeout(150)
  expect(submitted).toHaveLength(1)
  releaseFirst()
  await expect.poll(()=>submitted.length).toBe(2)
  expect(submitted[1]).toEqual([papers[200].id])
  const first=page.locator('.paper-row').filter({hasText:papers[0].title}),last=page.locator('.paper-row').filter({hasText:papers[200].title})
  await expect(first).toContainText('等待分析')
  await expect(first.getByRole('checkbox')).not.toBeChecked()
  if(failSecondBatch){
    await expect(page.getByRole('alert')).toContainText('未提交的论文仍保留选中')
    await expect(page.getByRole('alert')).toContainText('Second batch temporarily unavailable')
    await expect(page.locator('.batch-analysis-bar')).toContainText('1 已选择')
    await expect(last.getByRole('checkbox')).toBeChecked()
    await page.getByRole('button',{name:'分析所选论文',exact:true}).click()
    await expect.poll(()=>submitted.length).toBe(3)
    expect(submitted[2]).toEqual([papers[200].id])
  }
  await expect(last).toContainText('等待分析')
  await expect(last.getByRole('checkbox')).not.toBeChecked()
  await expect(page.getByRole('button',{name:'分析所选论文',exact:true})).toBeDisabled()
})

test('a delayed terminal response from an old task cannot replace a newer task for the same paper',async({page})=>{
  const paper=await realPaper(page)
  await settings(page)
  const old={id:'old-attempt',paper_id:paper.id,status:'running',phase:'extracting',completed_steps:1,total_steps:3,report:{},error:null}
  let current:any=old,oldRequested=false,newPolls=0,releaseOld:()=>void=()=>{}
  await page.route('**/api/papers?*',async route=>{const json=await (await route.fetch()).json();json.items=json.items.map((p:any)=>p.id===paper.id?{...p,intelligence_status:current.status,intelligence_task:current}:p);await route.fulfill({json})})
  await page.route(`**/api/papers/${paper.id}`,route=>route.fulfill({json:{...paper,intelligence_status:current.status,intelligence_task:current}}))
  await page.route('**/api/intelligence/tasks{,?*}',async route=>{
    if(route.request().method()==='POST'){
      expect(route.request().postDataJSON().paper_ids).toEqual([paper.id])
      current={...old,id:'new-attempt',status:'queued',phase:'queued',completed_steps:0,total_steps:5}
      await route.fulfill({json:{tasks:[current]}});return
    }
    if(!oldRequested){
      oldRequested=true
      await new Promise<void>(resolve=>{releaseOld=resolve})
      await route.fulfill({json:{tasks:[{...old,status:'failed',phase:'failed',error:'Old attempt failed'}]}}).catch(()=>{})
    }else{
      newPolls++
      current={...current,status:'running',phase:'extracting',completed_steps:2}
      await route.fulfill({json:{tasks:[current]}})
    }
  })
  await page.goto('/')
  const row=page.locator('.paper-row').filter({hasText:paper.title})
  await expect(row).toContainText('1 / 3')
  await expect.poll(()=>oldRequested).toBe(true)
  await row.getByRole('checkbox').check()
  await page.getByRole('button',{name:'分析所选论文',exact:true}).click()
  await expect(row).toContainText('0 / 5')
  releaseOld()
  await expect.poll(()=>newPolls).toBeGreaterThan(0)
  await expect(row).toContainText('2 / 5')
  await expect(row).not.toContainText('分析失败')
})

test('a delayed cancellation response cannot stop polling a newer task for the same paper',async({page})=>{
  const paper=await realPaper(page)
  await settings(page)
  const old={id:'old-cancel-attempt',paper_id:paper.id,status:'running',phase:'extracting',completed_steps:1,total_steps:3,report:{},error:null}
  let current:any=old,cancelRequested=false,newPolls=0,releaseCancel:()=>void=()=>{}
  await page.route('**/api/papers?*',async route=>{
    const json=await (await route.fetch()).json()
    json.items=json.items.map((p:any)=>p.id===paper.id?{...p,intelligence_status:current.status,intelligence_task:current}:p)
    await route.fulfill({json})
  })
  await page.route(`**/api/papers/${paper.id}`,route=>route.fulfill({json:{...paper,intelligence_status:current.status,intelligence_task:current}}))
  await page.route('**/api/intelligence/tasks{,?*}',async route=>{
    if(route.request().method()==='POST'){
      expect(route.request().postDataJSON().paper_ids).toEqual([paper.id])
      current={...old,id:'new-after-cancel',status:'queued',phase:'queued',completed_steps:0,total_steps:5}
      await route.fulfill({json:{tasks:[current]}});return
    }
    if(current.id==='new-after-cancel'){
      newPolls++
      current={...current,status:'running',phase:'extracting',completed_steps:2}
    }
    await route.fulfill({json:{tasks:[current]}})
  })
  await page.route(`**/api/intelligence/tasks/${old.id}/cancel`,async route=>{
    cancelRequested=true
    const cancelled={...old,status:'cancelled',phase:'cancelled'}
    current=cancelled
    await new Promise<void>(resolve=>{releaseCancel=resolve})
    await route.fulfill({json:cancelled})
  })
  await page.goto('/')
  const row=page.locator('.paper-row').filter({hasText:paper.title})
  await expect(row).toContainText('1 / 3')
  await row.getByRole('button',{name:'取消任务',exact:true}).click()
  await expect.poll(()=>cancelRequested).toBe(true)
  await row.getByRole('checkbox').check()
  await page.getByRole('button',{name:'分析所选论文',exact:true}).click()
  await expect(row).toContainText('0 / 5')
  const pollsBeforeRelease=newPolls
  releaseCancel()
  await expect.poll(()=>newPolls).toBeGreaterThan(pollsBeforeRelease+1)
  await expect(row).toContainText('2 / 5')
  await expect(row).not.toContainText('已取消')
})
