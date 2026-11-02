import { expect, test } from '@playwright/test'

test('switching from the whole library stops scheduling old paper detail requests',async({page})=>{
  const scoped='collection-small'
  const paper=(i:number)=>({id:`scope-paper-${i}`,title:`Paper ${i}`,abstract:null,year:2024,venue:'Test venue',doi:null,arxiv_id:null,reading_status:'unread',is_favorite:false,analysis_status:'ready',tags:[],authors:[],collection_ids:i>=12?[scoped]:[],page_count:1,is_demo:false,pdf_available:false,analysis:null,chunks:[],notes:[],evidence:[],created_at:'2026-11-01T00:00:00Z',updated_at:'2026-11-01T00:00:00Z'})
  const papers=Array.from({length:14},(_,i)=>paper(i))
  let release!:()=>void
  const held=new Promise<void>(resolve=>{release=resolve})
  let oldRequests=0
  await page.route(/\/api\/papers(?:\?.*)?$/,route=>route.fulfill({json:{items:papers,total:papers.length}}))
  await page.route('**/api/collections',route=>route.fulfill({json:{items:[{id:scoped,name:'Small collection',description:null,color:'#536f89',paper_count:2}]}}))
  await page.route('**/api/papers/scope-paper-*',async route=>{
    const path=new URL(route.request().url()).pathname
    if(path.endsWith('/knowledge/audit'))return route.fulfill({json:{paper_id:'fixture',coverage:{}}})
    const p=papers.find(p=>path.endsWith('/'+p.id))!
    if(!p.collection_ids.length){oldRequests++;await held}
    return route.fulfill({json:p})
  })
  await page.route('**/api/graph*',route=>route.fulfill({json:{nodes:[],edges:[]}}))
  await page.route('**/api/knowledge/entities*',route=>route.fulfill({json:{items:[]}}))
  await page.route('**/api/knowledge/overview*',route=>route.fulfill({json:{candidates:[],relations:[]}}))
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await expect.poll(()=>oldRequests).toBeGreaterThan(0)
  await page.locator('.collection-picker').selectOption(scoped)
  release()
  await expect(page.locator('.timeline-item')).toHaveCount(2)
  expect(oldRequests).toBeLessThanOrEqual(6)
})
