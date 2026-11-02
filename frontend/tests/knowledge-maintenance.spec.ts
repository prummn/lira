import { expect, test } from '@playwright/test'

test('scope progress includes import-triggered jobs even when the last batch is empty',async({page,request})=>{
  const paper=(await(await request.get('/api/papers')).json()).items[0]
  let checked=false
  await page.route('**/api/knowledge/maintenance/backlog?**',route=>route.fulfill({json:{
    pending_papers:checked?0:1,review_papers:checked?1:0,checked_papers:checked?1:0,
    pending_objects:40,pending_relations:32,items:[{paper_id:paper.id,title:'SWE-smith',
      status:checked?'needs_review':'queued',run_id:'paper-curation',pending_objects:40,pending_relations:32,error:null}],
  }}))
  await page.route(/\/api\/knowledge\/maintenance\/runs/,route=>route.fulfill({json:{items:[]}}))
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'AI 知识整理',exact:true}).click()
  const summary=page.locator('.maintenance-scope-summary')
  await expect(summary.locator('span').first().locator('strong')).toHaveText('1')
  await expect(summary).toContainText('40')
  await expect(summary).toContainText('32')
  await expect(page.locator('.maintenance-auto-queue')).toContainText('SWE-smith')
  await expect(page.locator('.maintenance-auto-queue')).toContainText('已排队，等待后台调度')
  checked=true
  await expect(summary.locator('span').first().locator('strong')).toHaveText('0',{timeout:10000})
  await expect(page.locator('.maintenance-auto-queue')).toContainText('已检查，仍有待确认条目')
  await page.setViewportSize({width:520,height:900})
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
})

test('knowledge maintenance keeps the issue queue and evidence action visible', async ({ page, request }) => {
  const papers = (await (await request.get('/api/papers')).json()).items as Array<{id:string;title:string}>
  const paper = papers[0]
  const evidence = {paper_id:paper.id, paper_title:paper.title, chunk_id:'maintenance-chunk', page:2, section:'Method', quote:'The method retrieves a relevant experience.', bbox:null, page_width:null, page_height:null}
  const issue = {id:'maintenance-issue', run_id:'maintenance-run', kind:'identity', severity:'warning', status:'proposed', confidence:1, confidence_basis:{deterministic:true}, auto_eligible:true, subject_ids:['candidate-a','candidate-b'], evidence:[evidence], external_leads:[], summary:'同一篇论文中存在 2 条相同对象记录', reasoning:'对象分类和规范化名称完全一致。', proposed_action:{type:'reconcile_paper',paper_id:paper.id}, source_fingerprint:'fingerprint', applied_change_ids:[], created_at:new Date().toISOString(), updated_at:new Date().toISOString()}
  let detail = {id:'maintenance-run',scope_type:'library',scope_id:null,status:'complete',allow_external:false,model_name:'maintenance-model',prompt_version:'fixture',source_fingerprint:'fingerprint',started_at:null,finished_at:new Date().toISOString(),error_message:null,safe_count:1,review_count:0,conflict_count:0,applied_count:0,usage:{total_tokens:0},issues:[issue]}
  await page.route(/\/api\/knowledge\/maintenance\/runs/, async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/apply-safe')) {
      detail = {...detail, applied_count:1, safe_count:0, issues:[{...issue,status:'auto_applied',applied_change_ids:['change-a']}]}
      return route.fulfill({json:{run:detail,results:[{id:issue.id,status:'auto_applied'}]}})
    }
    if (path.endsWith('/maintenance-run')) return route.fulfill({json:detail})
    return route.fulfill({json:{items:[detail]}})
  })
  await page.route(/\/api\/knowledge\/maintenance\/issues\//, async route => {
    detail = {...detail, applied_count:1, safe_count:0, issues:[{...issue,status:'auto_applied',applied_change_ids:['change-a']}]}
    return route.fulfill({json:{issue:detail.issues[0],run:detail}})
  })
  await page.goto('/')
  await expect(page.locator('.paper-row').first()).toBeVisible()
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'AI 知识整理',exact:true}).click()
  const workbench = page.getByTestId('knowledge-maintenance')
  await expect(workbench).toBeVisible()
  await expect(workbench).toContainText('可自动修复')
  await expect(workbench).toContainText('同一篇论文中存在 2 条相同对象记录')
  await expect(workbench.locator('.maintenance-evidence-row')).toContainText('The method retrieves a relevant experience.')
  await workbench.getByRole('button',{name:'应用这条建议',exact:true}).click()
  await expect(workbench).toContainText('已自动整理')
  await workbench.locator('.maintenance-history > summary').click()
  await expect(workbench.getByRole('button',{name:'撤销这次修复',exact:true})).toBeVisible()
})

test('AI curation leads with completed paper audits and keeps unresolved details collapsed',async({page,request})=>{
  const paper=(await (await request.get('/api/papers')).json()).items[0]
  const base={run_id:'curation',kind:'coverage',severity:'info',confidence:1,confidence_basis:{},auto_eligible:false,subject_ids:[],evidence:[],external_leads:[],reasoning:'A source check.',proposed_action:{type:'curate_paper'},source_fingerprint:'v1',applied_change_ids:[],created_at:new Date().toISOString(),updated_at:new Date().toISOString()}
  const issues=[{...base,id:'done',status:'auto_applied',summary:'Finished source audit'},{...base,id:'pending',status:'needs_review',summary:'A relationship needs more evidence'}]
  const run={id:'curation',scope_type:'library',scope_id:null,status:'complete',allow_external:false,model_name:'curator',prompt_version:'v1',source_fingerprint:'v1',started_at:null,finished_at:new Date().toISOString(),error_message:null,safe_count:0,review_count:1,conflict_count:0,applied_count:1,usage:{auto_actions:3,paper_audits:[{paper_id:paper.id,title:paper.title,source_chars:12000,source_chunks:14,coverage:'main_text',objects_added:2,objects_confirmed:4,relations_added:1,relations_confirmed:2,aliases_linked:1,protected:0,deferred:1,summary:'Added a benchmark and linked its alias.',checked_at:new Date().toISOString()}]},issues}
  await page.route(/\/api\/knowledge\/maintenance\/runs/,route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith('/curation')?run:{items:[run]}}))
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'AI 知识整理',exact:true}).click()
  await expect(page.locator('.maintenance-completed')).toContainText(paper.title)
  await expect(page.locator('.maintenance-completed')).toContainText('Added a benchmark and linked its alias.')
  await expect(page.locator('.maintenance-completed')).toContainText('正文')
  const counts=page.locator('.maintenance-completed dl > div')
  await expect(counts.filter({has:page.locator('dt',{hasText:'知识对象'})}).locator('dd')).toHaveText('4')
  await expect(counts.filter({has:page.locator('dt',{hasText:'关系',exact:true})}).locator('dd')).toHaveText('2')
  await expect(page.locator('.maintenance-metrics').locator('button').first()).toContainText('已自动整理')
  await expect(page.locator('.maintenance-metrics button').first().locator('strong')).toHaveText('3')
  const pending=page.locator('.maintenance-pending')
  await expect(pending.locator('summary')).toContainText('待继续核对')
  await expect(pending).not.toHaveAttribute('open','')
  await page.screenshot({path:'test-artifacts/knowledge-ai-curation.png',fullPage:true})
  await pending.locator('summary').click()
  await expect(pending).toContainText('A relationship needs more evidence')
  await page.locator('.maintenance-metrics button').first().click()
  await expect(pending.locator('summary')).toContainText('待继续核对')
})

test('an active AI curation run refreshes its completed results without another click',async({page})=>{
  const run={id:'active-curation',scope_type:'library',scope_id:null,status:'queued',allow_external:false,model_name:'curator',prompt_version:'v1',source_fingerprint:'v1',started_at:null,finished_at:null,error_message:null,safe_count:0,review_count:0,conflict_count:0,applied_count:0,usage:{},issues:[]}
  let finished=false
  await page.route(/\/api\/knowledge\/maintenance\/runs/,route=>{
    if(new URL(route.request().url()).pathname.endsWith('/active-curation')) {
      return route.fulfill({json:!finished?run:{...run,status:'complete',finished_at:new Date().toISOString(),applied_count:2}})
    }
    return route.fulfill({json:{items:[run]}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'AI 知识整理',exact:true}).click()
  await expect(page.locator('.maintenance-status-strip')).toContainText('排队中')
  finished=true
  await expect(page.locator('.maintenance-status-strip')).toContainText('本轮完成',{timeout:10000})
  await expect(page.locator('.maintenance-metrics button').first().locator('strong')).toHaveText('2')
})

test('starting AI curation includes public publication metadata verification',async({page})=>{
  let submitted:Record<string,unknown>|undefined
  const run={id:'new-curation',scope_type:'library',scope_id:null,status:'complete',allow_external:true,model_name:null,prompt_version:'v1',source_fingerprint:'v1',started_at:null,finished_at:new Date().toISOString(),error_message:null,safe_count:0,review_count:0,conflict_count:0,applied_count:0,usage:{},issues:[]}
  await page.route(/\/api\/knowledge\/maintenance\/runs/,route=>{
    if(route.request().method()==='POST'){submitted=route.request().postDataJSON();return route.fulfill({json:run})}
    return route.fulfill({json:{items:[]}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'AI 知识整理',exact:true}).click()
  await page.locator('.maintenance-hero-actions').getByRole('button',{name:'整理当前范围',exact:true}).click()
  await expect.poll(()=>submitted?.allow_external).toBe(true)
  await expect(page.locator('.maintenance-hero')).toContainText('公开发表信息')
})
