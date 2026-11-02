import { test, expect } from '@playwright/test'

test('topic agenda explains work, opens saved results and allows cancelling queued work', async ({page,request}) => {
  const c=await (await request.post('/api/collections',{data:{name:'Agenda reading'}})).json()
  const base={collection_id:c.id,calls:0,error:null,created_at:'2026-10-25T08:00:00Z',updated_at:'2026-10-25T08:00:00Z',usage:{}}
  const tasks=[
    {...base,id:'investigation-1',kind:'investigation',stage:'published',status:'completed',title:'上下文腾空后如何找回旧消息？',question:'追踪检索过程',rationale:'已有解释没有说明调用顺序',paper_ids:['p1'],section_hints:['Memory'],existing_id:'f1',outcome_ids:['f1']},
    {...base,id:'investigation-2',kind:'investigation',stage:'discover',status:'queued',title:'反思过时后会发生什么？',question:'检查失效机制',rationale:'核对附录中的更新规则',paper_ids:['p1'],section_hints:['Appendix'],existing_id:null,outcome_ids:[],origin:{kind:'note',id:'note1',paper_id:'p1',page:7,selected_text:'reflection'}},
  ]
  const items=[{id:'f1',collection_id:c.id,kind:'gap',title:'消息检索的具体顺序',body:'先搜索持久历史，再将命中结果放入当前上下文。',next_step:'对照函数调用顺序。',sources:[],status:'unread',review_count:0,due_at:null,model:'fixture',...base}]
  await page.route(`**/api/research/collections/${c.id}/findings`,r=>r.fulfill({json:{scope:{enabled:true,focus:'Memory',work_types:['gaps']},items,task:null,due_count:0,agenda:{planner:{...base,id:'plan1',kind:'agenda',stage:'planned',status:'completed'},tasks}}}))
  await page.route('**/api/research/tasks/investigation-2/cancel',route=>{tasks[1].status='cancelled';return route.fulfill({json:tasks[1]})})
  await page.goto('/')
  await page.locator('.collection-nav').getByRole('button',{name:c.name,exact:true}).click()
  await page.getByRole('button',{name:'研究线索',exact:true}).click()
  await page.locator('.research-agenda>summary').click()
  await expect(page.getByText('已有解释没有说明调用顺序',{exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'回到阅读位置',exact:true})).toBeVisible()
  await expect(page.getByText('来自问题笔记 · 第 7 页',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'查看研究结果',exact:true}).click()
  await expect(page.getByRole('heading',{name:'消息检索的具体顺序',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'取消：反思过时后会发生什么？',exact:true}).click()
  await expect(page.locator('.agenda-task').last()).toContainText('已取消')
  await page.setViewportSize({width:430,height:850})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:'test-artifacts/research-agenda-mobile.png',fullPage:true})
})

test('reading-only work checks questions and returns from the original passage', async ({page,request}) => {
  const c=await (await request.post('/api/collections',{data:{name:'Reading follow-up'}})).json()
  const task={id:'reading-task',collection_id:c.id,kind:'investigation',stage:'published',status:'completed',calls:2,error:null,
    title:'Why retrieve the earlier conversation?',question:'Explain retrieval',rationale:'Return to the original question.',paper_ids:['paper-001'],section_hints:[],existing_id:null,outcome_ids:['reading-answer'],usage:{},
    created_at:'2026-10-25T08:00:00Z',updated_at:'2026-10-25T08:00:00Z',origin:{kind:'chat',id:'turn1',paper_id:'paper-001',page:2,selected_text:''}}
  const item={id:'reading-answer',collection_id:c.id,kind:'reading',title:'The retrieval sequence',body:'Search the earlier history, then bring the result into context.',next_step:'Trace the original passage.',sources:[],status:'unread',review_count:0,due_at:null,model:'fixture',created_at:task.created_at,updated_at:task.updated_at}
  const data={scope:{enabled:true,focus:'Reading questions',work_types:['reading']},items:[item],task:null,due_count:0,agenda:{planner:null,tasks:[task]}}
  let scans=0,baseRuns=0
  await page.route(`**/api/research/collections/${c.id}/findings`,route=>{
    if(route.request().method()==='POST')baseRuns++
    return route.fulfill({json:data})
  })
  await page.route(`**/api/research/collections/${c.id}/reading`,route=>{scans++;return route.fulfill({json:{tasks:[task]}})})
  await page.goto('/')
  await page.locator('.collection-nav').getByRole('button',{name:c.name,exact:true}).click()
  await page.getByRole('button',{name:'研究线索',exact:true}).click()
  await page.getByRole('button',{name:'检查阅读问题',exact:true}).click()
  await expect.poll(()=>scans).toBe(1)
  expect(baseRuns).toBe(0)
  await page.locator('.research-agenda>summary').click()
  await page.getByRole('button',{name:'查看研究结果',exact:true}).click()
  await page.getByRole('button',{name:'回到阅读位置',exact:true}).click()
  await expect(page.getByRole('button',{name:'返回研究线索',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'返回研究线索',exact:true}).click()
  await expect(page.getByRole('heading',{name:item.title,exact:true})).toBeVisible()
})
