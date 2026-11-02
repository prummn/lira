import { expect, test, type Page } from '@playwright/test'
import type { KnowledgeCandidate, Paper, PaperDetail } from '../src/types'

const evidence = [{chunk_id:'source',page:2,section:'Introduction',quote:'We introduce a benchmark for repository issues.',bbox:null,page_width:null,page_height:null}]
const candidate = (id:string,paper_id:string,name:string,type:KnowledgeCandidate['entity_type'],role='proposed'):KnowledgeCandidate => ({
  id,paper_id,entity_id:id,entity_type:type,name,normalized_name:name.toLowerCase(),aliases:[],description:null,role,
  confidence:.95,status:'confirmed',evidence,conflict:{},run_id:null,model_version:null,prompt_version:null,layer:type==='method'?'primary':'evaluation',importance:'core',
})

async function field(page:Page, papers:PaperDetail[], candidates:KnowledgeCandidate[]=[]) {
  await page.route(/\/api\/papers(?:\?.*)?$/,route=>route.fulfill({json:{items:papers}}))
  for(const paper of papers) await page.route(`**/api/papers/${paper.id}`,route=>route.fulfill({json:paper}))
  await page.route('**/api/knowledge/overview*',route=>route.fulfill({json:{candidates,relations:[]}}))
  await page.route('**/api/knowledge/entities*',route=>route.fulfill({json:{items:[]}}))
  await page.route('**/api/papers/*/knowledge/audit',route=>route.fulfill({json:{paper_id:'fixture',coverage:{},issues:[]}}))
  await page.route('**/api/graph*',route=>route.fulfill({json:{nodes:papers.map(p=>({id:p.id,label:p.title,year:p.year,authors:p.authors})),edges:[{id:'edge',source:papers[0].id,target:papers[1].id,relation:'cites',relation_source:'explicit'}]}}))
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
}

const paper = (id:string,title:string,extra:Partial<Paper>={}):PaperDetail => ({
  id,title,abstract:null,year:2023,venue:null,doi:null,arxiv_id:null,reading_status:'unread',is_favorite:false,analysis_status:'completed',
  tags:[],authors:['A. Researcher'],collection_ids:[],page_count:4,is_demo:false,pdf_available:true,knowledge_status:'candidates',
  created_at:'2026-11-01T00:00:00Z',updated_at:'2026-11-01T00:00:00Z',analysis:null,chunks:[],notes:[],evidence:[],...extra,
})

test('timeline names publication gaps and graph relation details start collapsed',async({page})=>{
  await field(page,[paper('preprint','Preprint work',{arxiv_id:'2310.00001'}),paper('unpublished','Publication metadata pending')])
  await expect(page.locator('.timeline-item').filter({hasText:'Preprint work'}).locator('.timeline-meta')).toHaveText('预印本 · arXiv')
  await expect(page.locator('.timeline-item').filter({has:page.getByRole('button',{name:'Publication metadata pending',exact:true})}).locator('.timeline-meta')).toHaveText('发表信息待补充')
  await page.getByRole('button',{name:'引用与方法关系',exact:true}).click()
  const details=page.locator('.graph-relation-details')
  await expect(details.locator('summary')).toContainText('关系明细')
  await expect(details).not.toHaveAttribute('open','')
  await expect(details.locator('.graph-relations')).not.toBeVisible()
  await page.screenshot({path:'test-artifacts/knowledge-relations-collapsed.png'})
  await details.locator('summary').click()
  await expect(details.locator('.graph-relations')).toBeVisible()
})

test('comparison explains missing analysis and keeps prose readable',async({page})=>{
  const analyzed={...paper('ready','Analyzed work'),analysis:{problem:'A concrete research problem.',method:'An evidence based method.',findings:'Observed results.',limitations:'Known constraints.',one_liner:null,concepts:[]}}
  await field(page,[analyzed,paper('failed','Terminal-Bench',{analysis_status:'failed'})])
  await page.getByRole('button',{name:'论文比较',exact:true}).click()
  const missing=page.locator('.comparison-table tbody tr').first().locator('td').nth(1)
  await expect(missing).toContainText('分析未完成')
  await expect(missing.getByRole('button',{name:'打开论文',exact:true})).toBeVisible()
  const typography=await page.locator('.comparison-table td').first().evaluate(el=>({font:parseFloat(getComputedStyle(el).fontSize),line:parseFloat(getComputedStyle(el).lineHeight),width:el.getBoundingClientRect().width}))
  expect(typography.font).toBeGreaterThanOrEqual(15)
  expect(typography.line).toBeGreaterThanOrEqual(26)
  expect(typography.width).toBeGreaterThanOrEqual(300)
  await page.screenshot({path:'test-artifacts/knowledge-comparison-readable.png'})
  await page.setViewportSize({width:390,height:844})
  expect(await page.locator('.comparison-scroll').evaluate(el=>el.scrollWidth>el.clientWidth)).toBeTruthy()
  await page.screenshot({path:'test-artifacts/knowledge-comparison-mobile.png'})
})

test('evolution includes proposed benchmarks and exposes papers missing knowledge',async({page})=>{
  const papers=[paper('react','ReAct: Synergizing Reasoning and Acting'),paper('swe','SWE-bench: Can Language Models Resolve Real-World GitHub Issues?'),paper('terminal','Terminal-Bench',{analysis_status:'failed',knowledge_status:'unread'})]
  const candidates=[candidate('react-core','react','ReAct','method'),candidate('swe-core','swe','SWE-bench','benchmark','used'),candidate('humaneval','react','HumanEval','benchmark','used')]
  await field(page,papers,candidates)
  await page.getByRole('button',{name:'方法演进',exact:true}).click()
  const choices=page.locator('.knowledge-map-methods')
  await expect(choices.getByRole('button',{name:'SWE-bench',exact:true})).toBeVisible()
  await expect(choices.getByRole('button',{name:'HumanEval',exact:true})).toHaveCount(0)
  await choices.getByRole('button',{name:'SWE-bench',exact:true}).click()
  await expect(page.locator('.knowledge-map-node.node-core')).toContainText('评测基准')
  await expect(page.locator('.knowledge-map-coverage')).toContainText('Terminal-Bench')
  await expect(page.locator('.knowledge-map-coverage')).toContainText('分析未完成')
  await expect(page.locator('.knowledge-map-coverage').getByRole('button',{name:'打开论文',exact:true})).toBeVisible()
  await expect(page.locator('.field-tabs').getByRole('button',{name:'概念索引',exact:true})).toHaveCount(0)
  await expect(page.locator('.field-tabs').getByRole('button',{name:'对象目录',exact:true})).toHaveCount(1)
  await page.screenshot({path:'test-artifacts/knowledge-contributions.png',fullPage:true})
})
