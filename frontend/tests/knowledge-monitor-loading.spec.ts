import {expect,test} from '@playwright/test'
import {readFile} from 'node:fs/promises'

test('export fetches complete paper records only when requested',async({page})=>{
  let details=0
  page.on('request',request=>{
    if(/^\/api\/papers\/[^/]+$/.test(new URL(request.url()).pathname))details++
  })
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await expect(page.locator('.timeline-item').first()).toBeVisible()
  expect(details).toBe(0)
  const downloaded=page.waitForEvent('download')
  await page.getByRole('button',{name:'导出 JSON',exact:true}).click()
  const file=await downloaded
  const payload=JSON.parse(await readFile((await file.path())!,'utf-8'))
  expect(payload.papers.some((p:{chunks?:unknown[]})=>p.chunks?.length)).toBe(true)
  expect(details).toBe(payload.papers.length)
})

test('knowledge navigation stays usable while graph and reader data are slow',async({page})=>{
  let release!:()=>void
  const held=new Promise<void>(resolve=>{release=resolve})
  let readerRequests=0,auditRequests=0,graphRequests=0
  await page.route(/\/api\/papers\/[^/?]+(?:\/knowledge\/audit)?$/,async route=>{
    if(route.request().method()!=='GET')return route.continue()
    if(route.request().url().endsWith('/audit'))auditRequests++;else readerRequests++
    await held;await route.continue()
  })
  await page.route('**/api/graph*',async route=>{graphRequests++;await held;await route.continue()})
  try {
    await page.goto('/')
    await page.getByRole('button',{name:'知识摄取',exact:true}).click()
    await expect(page.locator('.timeline-item').first()).toBeVisible({timeout:4000})
    await page.getByRole('button',{name:'AI 知识整理',exact:true}).click()
    await expect(page.locator('.maintenance-hero-actions button').last()).toBeEnabled({timeout:4000})
    expect(readerRequests).toBe(0)
    expect(auditRequests).toBe(0)
    expect(graphRequests).toBe(1)
  } finally {release()}
})

test('curation appears in the global queue, updates checkpoints and opens its scope',async({page})=>{
  let completed=0,status='queued'
  const actions:string[]=[]
  const run={id:'visible-curation',scope_type:'collection',scope_id:'demo-topic',scope_title:'Agents',
    paper_count:8,total:3,completed:0,pending:3,failed:0,status:'queued',reason:'reading',
    active_paper_id:null,active_paper_title:null,error:null,model_name:'official'}
  await page.route('**/api/research/status',async route=>{
    const response=await route.fetch()
    await route.fulfill({json:{...await response.json(),translation_jobs:[],analysis_tasks:[],tasks:[],
      maintenance_tasks:[{...run,status,completed,pending:3-completed,reason:status==='queued'?'reading':null,
        active_paper_title:status==='running'?'ReAct':null}],reason:'reading'}})
  })
  await page.route('**/api/knowledge/maintenance/runs/visible-curation/*',async route=>{
    actions.push(route.request().url().split('/').pop()!)
    status='cancelled';await route.fulfill({json:{id:run.id,status}})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'后台任务',exact:true}).click()
  const job=page.getByRole('article',{name:'Agents'})
  await expect(job).toContainText('AI 知识整理')
  await expect(job).toContainText('0 / 3')
  await expect(job).toContainText('优先保障阅读')
  completed=1;status='running'
  await expect(job).toContainText('1 / 3',{timeout:10000})
  await expect(job).toContainText('ReAct')
  await page.setViewportSize({width:430,height:850})
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await job.getByRole('button',{name:'取消任务',exact:true}).click()
  await expect(job).toContainText('已取消')
  expect(actions).toEqual(['cancel'])
})
