import { test, expect } from '@playwright/test'

test('analysis stays visible through progress, navigation, reload and partial completion',async({page,request})=>{
  const paper=(await (await request.get('/api/papers')).json()).items[0]
  const task={id:'analysis-monitor',paper_id:paper.id,paper_title:paper.title,status:'queued',phase:'queued',completed_steps:0,total_steps:0,error:null}
  await page.route('**/api/research/status',async route=>{
    const response=await route.fetch(),state=await response.json()
    await route.fulfill({json:{...state,settings:{...state.settings,enabled:false},scheduler:{official:{configured:4,effective:4,active:2,waiting:1},active:2,waiting:1},translation_jobs:[],analysis_tasks:[{...task}]}})
  })
  await page.goto('/')
  const entry=page.getByRole('button',{name:'后台任务',exact:true})
  await expect(entry).toContainText('1 项')
  await entry.click()
  const monitor=page.getByRole('region',{name:'后台任务'})
  await expect(monitor.getByLabel('官方并发')).toContainText('2 / 4')
  const row=monitor.getByRole('article',{name:paper.title,exact:true})
  await expect(row).toContainText('论文分析')
  await expect(row).toContainText('等待执行')
  await expect(row).not.toContainText('0 / 0')
  await expect(monitor).not.toContainText('没有待处理')
  task.phase='awaiting_translation'
  await monitor.getByRole('button',{name:'刷新进度',exact:true}).click()
  await expect(row).toContainText('预译正文后继续分析')
  await expect(row).not.toContainText('0 / 0')
  task.status='running';task.phase='structure'
  await monitor.getByRole('button',{name:'刷新进度',exact:true}).click()
  await expect(row).toContainText('整理论文结构')
  await expect(row.getByRole('progressbar')).toHaveCount(0)
  task.phase='extract';task.completed_steps=2;task.total_steps=7
  await expect(row).toContainText('2 / 7',{timeout:10000})
  await expect(row).toContainText('逐段读取原文')
  await expect(entry.locator('.research-status-dot')).toHaveClass(/is-working/)
  await page.screenshot({path:'test-artifacts/analysis-monitor-light.png'})
  await row.getByRole('button',{name:'打开论文',exact:true}).click()
  await page.getByRole('button',{name:'返回后台任务',exact:true}).click()
  await expect(row).toContainText('2 / 7')
  await page.reload()
  await entry.click()
  await expect(row).toContainText('2 / 7')
  task.status='partial';task.phase='complete';task.completed_steps=7
  await monitor.getByRole('button',{name:'刷新进度',exact:true}).click()
  await expect(monitor.getByRole('heading',{name:'最近结束',exact:true})).toBeVisible()
  await expect(row).toContainText('部分完成')
  await expect(row.getByRole('button',{name:'重试分析',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'主题',exact:true}).click()
  await page.setViewportSize({width:430,height:850})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:'test-artifacts/analysis-monitor-dark-mobile.png'})
})

test('analysis cancellation and retry update the monitor through existing task APIs',async({page,request})=>{
  const paper=(await (await request.get('/api/papers')).json()).items[0]
  let task={id:'analysis-actions',paper_id:paper.id,paper_title:paper.title,status:'running',phase:'extract',completed_steps:1,total_steps:5,error:null as string|null,report:{}}
  const actions:string[]=[]
  await page.route('**/api/research/status',async route=>{
    const response=await route.fetch()
    await route.fulfill({json:{...await response.json(),translation_jobs:[],analysis_tasks:[{...task}]}})
  })
  await page.route('**/api/intelligence/tasks/analysis-actions/cancel',async route=>{
    actions.push('cancel');task={...task,status:'cancelled',phase:'cancelled'}
    await route.fulfill({json:task})
  })
  await page.route('**/api/intelligence/tasks{,?*}',async route=>{
    if(route.request().method()==='POST'){
      expect(route.request().postDataJSON()).toEqual({paper_ids:[paper.id],force:true})
      actions.push('retry');task={...task,id:'analysis-retry',status:'queued',phase:'queued',completed_steps:0,total_steps:0,error:null}
    }
    await route.fulfill({json:{tasks:[{...task}]}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'后台任务',exact:true}).click()
  const monitor=page.getByRole('region',{name:'后台任务'})
  const row=monitor.getByRole('article',{name:paper.title,exact:true})
  await row.getByRole('button',{name:'取消任务',exact:true}).click()
  await expect(row).toContainText('已取消')
  task.status='failed';task.error='模型连接暂时中断，已保留原有分析'
  await monitor.getByRole('button',{name:'刷新进度',exact:true}).click()
  await expect(row).toContainText(task.error)
  await row.getByRole('button',{name:'重试分析',exact:true}).click()
  await expect(row).toContainText('等待执行')
  await expect(row).not.toContainText('模型连接暂时中断')
  await expect(monitor.getByRole('heading',{name:'进行中',exact:true})).toBeVisible()
  expect(actions).toEqual(['cancel','retry'])
})

test('cancelling an analysis discovered by the monitor also refreshes an older library snapshot',async({page,request})=>{
  const paper=(await (await request.get('/api/papers')).json()).items[0]
  let cancelled=false
  const task={id:'monitor-newer-task',paper_id:paper.id,paper_title:paper.title,status:'running',phase:'extract',completed_steps:1,total_steps:5,error:null,report:{}}
  await page.route('**/api/papers?*',async route=>{
    const response=await route.fetch(),state=await response.json()
    state.items=state.items.map((p:any)=>p.id===paper.id?{...p,intelligence_status:cancelled?'cancelled':'unanalyzed',intelligence_task:cancelled?{...task,status:'cancelled',phase:'cancelled'}:null}:p)
    await route.fulfill({json:state})
  })
  await page.route('**/api/research/status',async route=>{
    const response=await route.fetch()
    await route.fulfill({json:{...await response.json(),translation_jobs:[],analysis_tasks:[{...task,status:cancelled?'cancelled':'running'}]}})
  })
  await page.route('**/api/intelligence/tasks/monitor-newer-task/cancel',async route=>{
    cancelled=true
    await route.fulfill({json:{...task,status:'cancelled',phase:'cancelled'}})
  })
  await page.goto('/')
  const row=page.locator('.paper-row').filter({hasText:paper.title})
  await expect(row).toContainText('未进行智能分析')
  await page.getByRole('button',{name:'后台任务',exact:true}).click()
  await page.getByRole('region',{name:'后台任务'}).getByRole('article',{name:paper.title,exact:true}).getByRole('button',{name:'取消任务',exact:true}).click()
  await expect(page.getByRole('region',{name:'后台任务'})).toContainText('已取消')
  await page.getByRole('button',{name:'文献库',exact:true}).click()
  await expect(row).toContainText('已取消')
})

test('an older running service uses already polled library tasks until the monitor API is upgraded',async({page,request})=>{
  const paper=(await (await request.get('/api/papers')).json()).items[0]
  const task={id:'legacy-analysis',paper_id:paper.id,status:'running',phase:'extract',completed_steps:3,total_steps:8,error:null,report:{}}
  let globalTaskReads=0
  await page.route('**/api/research/status',async route=>{
    const response=await route.fetch(),state=await response.json()
    delete state.analysis_tasks
    await route.fulfill({json:{...state,translation_jobs:[]}})
  })
  await page.route('**/api/papers?*',async route=>{
    const response=await route.fetch(),state=await response.json()
    state.items=state.items.map((p:any)=>p.id===paper.id?{...p,intelligence_status:task.status,intelligence_task:{...task}}:p)
    await route.fulfill({json:state})
  })
  await page.route('**/api/intelligence/tasks{,?*}',async route=>{
    if(!new URL(route.request().url()).searchParams.get('paper_id'))globalTaskReads++
    await route.fulfill({json:{tasks:[{...task}]}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'后台任务',exact:true}).click()
  const row=page.getByRole('region',{name:'后台任务'}).getByRole('article',{name:paper.title,exact:true})
  await expect(row).toContainText('3 / 8')
  task.completed_steps=4
  await expect(row).toContainText('4 / 8',{timeout:10000})
  expect(globalTaskReads).toBe(0)
})

test('a recent quota snapshot remains visible during a temporary query failure',async({page})=>{
  await page.route('**/api/research/status',async route=>{
    const response=await route.fetch()
    await route.fulfill({json:{...await response.json(),quota:[{name:'primary',used_percent:12,window_minutes:300,resets_at:2000000000}],
      quota_error_code:'transport_timeout',quota_checked_at:1792976400,quota_using_recent:true,translation_jobs:[]}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'后台任务',exact:true}).click()
  const monitor=page.getByRole('region',{name:'后台任务'})
  await expect(monitor.getByLabel('官方剩余额度')).toContainText('88%')
  await expect(monitor).toContainText('按两分钟内的官方结果继续')
  await expect(monitor).not.toContainText('全文预译在确认额度后继续')
})

test('quota query failure is distinct from exhausted quota and clears on recovery',async({page})=>{
  let recovered=false
  let quotaReads=0
  await page.route('**/api/research/quota',async route=>{quotaReads++;recovered=true;await route.fulfill({json:{quota:[],available:true,checked_at:1792976400,quota_error_code:null}})})
  await page.route('**/api/research/status',async route=>{
    const response=await route.fetch()
    await route.fulfill({json:{...await response.json(),quota:recovered?[{name:'primary',used_percent:12,window_minutes:300,resets_at:2000000000}]:[],
      quota_error_code:recovered?null:'transport_timeout',quota_checked_at:1792976400,
      translation_jobs:[{id:'quota-job',paper_id:'p',paper_title:'Quota diagnosis',mode:'full',status:'queued',
        reason:recovered?null:'quota_timeout',error:null,model_name:'official',completed:1,total:3,failed:0,in_flight:false}]}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'后台任务',exact:true}).click()
  const monitor=page.getByRole('region',{name:'后台任务'})
  await expect(monitor.getByLabel('官方剩余额度')).toContainText('额度查询超时')
  await expect(monitor).toContainText('不代表额度不足')
  await expect(monitor.locator('.background-job-reason')).toContainText('额度查询超时')
  await expect(monitor).not.toContainText('等待确认官方连接额度')
  await monitor.getByRole('button',{name:'重试额度查询',exact:true}).click()
  await expect(monitor.getByLabel('官方剩余额度')).toContainText('88%')
  await expect(monitor).not.toContainText('额度查询超时')
  expect(quotaReads).toBe(1)
})

test('translation progress is visible outside the reader without blocking background work',async({page,request})=>{
  const papers=await (await request.get('/api/papers')).json()
  const paper=papers.items[0]
  let monitorReads=0
  const presence:boolean[]=[]
  const actions:string[]=[]
  const job={id:'monitor-job',paper_id:paper.id,paper_title:paper.title,mode:'full',status:'queued',reason:'reading',error:null,model_name:'fixture',completed:1,total:3,failed:0,scope_total:3,scope_skipped:8,scope_reason:'appendix_or_references',in_flight:false,created_at:'2026-10-26T01:00:00Z',updated_at:'2026-10-26T01:00:00Z'}
  await page.route('**/api/research/presence',async route=>{presence.push(route.request().postDataJSON().reading);await route.fulfill({json:{ok:true}})})
  await page.route('**/api/research/status',async route=>{
    monitorReads++
    const response=await route.fetch()
    await route.fulfill({json:{...await response.json(),translation_jobs:[{...job}],quota:[{name:'primary',used_percent:12,window_minutes:300,resets_at:2000000000}],quota_checked_at:1792976400}})
  })
  await page.route('**/api/translation-jobs/monitor-job/*',async route=>{
    const action=route.request().url().split('/').pop()!
    actions.push(action)
    job.status=action==='pause'?'paused':action==='cancel'?'cancelled':'queued'
    job.reason=action==='pause'?'user_paused':null as any
    await route.fulfill({json:{...job,items:[]}})
  })
  await page.addInitScript(id=>localStorage.setItem('riw-last-paper',id),paper.id)
  await page.goto('/')
  await page.getByRole('button',{name:'正在阅读',exact:true}).click()
  await expect.poll(()=>presence.includes(true)).toBe(true)
  await page.getByRole('button',{name:'后台任务',exact:true}).click()
  const monitor=page.getByRole('region',{name:'后台任务'})
  await expect(monitor).toBeVisible()
  await expect.poll(()=>presence.at(-1)).toBe(false)
  await expect(monitor).toContainText(paper.title)
  await expect(monitor).toContainText('1 / 3')
  await expect(monitor).toContainText('正文范围')
  await expect(monitor).toContainText('已跳过 8 段附录/参考文献')
  const reads=monitorReads
  job.completed=2;job.status='running';job.reason=null as any
  await expect(monitor).toContainText('2 / 3',{timeout:10000})
  expect(monitorReads).toBeGreaterThan(reads)
  await monitor.getByRole('button',{name:'暂停翻译',exact:true}).click()
  await expect(monitor).toContainText('已暂停')
  await monitor.getByRole('button',{name:'继续翻译',exact:true}).click()
  expect(actions).toEqual(['pause','resume'])
  job.completed=3;job.status='completed'
  await expect(monitor).toContainText('3 / 3',{timeout:10000})
  await expect(monitor.getByRole('heading',{name:'最近结束',exact:true})).toBeVisible()
  await expect(monitor.locator('.background-job-reason')).toContainText('批量翻译完成')
  await page.screenshot({path:'test-artifacts/background-tasks-light.png'})
  await page.getByRole('button',{name:'主题',exact:true}).click()
  await page.setViewportSize({width:430,height:850})
  await expect(monitor).toContainText(paper.title)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:'test-artifacts/background-tasks-dark-mobile.png'})
  await monitor.getByRole('button',{name:'打开论文',exact:true}).click()
  await expect.poll(()=>presence.at(-1)).toBe(true)
})

test('task monitor opens while the library is still loading',async({page})=>{
  let release!:()=>void
  const held=new Promise<void>(resolve=>{release=resolve})
  await page.route('**/api/papers?*',async route=>{await held;await route.continue()})
  try {
    await page.goto('/')
    await page.getByRole('button',{name:'后台任务',exact:true}).click()
    await expect(page.getByRole('region',{name:'后台任务'})).toBeVisible({timeout:3000})
  } finally {release()}
})

test('scope labels distinguish a new job without a boundary from legacy and selected jobs',async({page})=>{
  const base={paper_id:'p',mode:'full',status:'completed',reason:null,error:null,model_name:'fixture',completed:3,total:3,failed:0,in_flight:false}
  await page.route('**/api/research/status',async route=>{
    const response=await route.fetch()
    await route.fulfill({json:{...await response.json(),translation_jobs:[
      {...base,id:'unclassified',paper_title:'No section boundary',scope_total:3,scope_skipped:0,scope_reason:null},
      {...base,id:'legacy',paper_title:'Earlier pretranslation',scope_total:0,scope_skipped:0,scope_reason:null},
      {...base,id:'manual',paper_title:'Explicit appendix selection',mode:'selected',scope_total:3,scope_skipped:9,scope_reason:'appendix_or_references'},
    ]}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'后台任务',exact:true}).click()
  const monitor=page.getByRole('region',{name:'后台任务'})
  await expect(monitor.getByRole('article',{name:'No section boundary'})).toContainText('未识别到附录/参考文献边界，保留全部段落')
  await expect(monitor.getByRole('article',{name:'Earlier pretranslation'}).locator('.translation-queue-scope')).toHaveCount(0)
  await expect(monitor.getByRole('article',{name:'Explicit appendix selection'}).locator('.translation-queue-scope')).toHaveCount(0)
})
