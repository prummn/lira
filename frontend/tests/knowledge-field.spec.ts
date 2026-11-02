import { expect, test } from '@playwright/test'
import type { KnowledgeCandidate, KnowledgeRelation } from '../src/types'

test('method evolution renders an evidence map and opens a pending relation', async ({ page }) => {
  const evidence=[{chunk_id:'source',page:4,section:'Method',quote:'ReAct compared to BUTLER.',bbox:null,page_width:null,page_height:null}]
  const core={id:'react',paper_id:'source',entity_id:'entity-react',entity_type:'method',name:'ReAct',normalized_name:'react',aliases:[],description:null,role:'proposed',confidence:.9,status:'confirmed',evidence,conflict:{},run_id:null,model_version:null,prompt_version:null,layer:'primary',importance:'core'}
  const pending={id:'butler',paper_id:'source',relation:'compares_with',source_name:'ReAct',source_normalized_name:'react',target_name:'BUTLER',target_normalized_name:'butler',source_candidate_id:'react',target_candidate_id:null,description:'Comparison awaiting review',confidence:.9,status:'unresolved',evidence,conflict:{},run_id:null,model_version:null,prompt_version:null,family:'comparison',importance:'supporting'}
  const supporting={...core,id:'compiler',entity_id:'compiler',name:'Benchmark compiler',normalized_name:'benchmark compiler',role:'used',importance:'supporting'}
  await page.route('**/api/knowledge/overview*',route=>route.fulfill({json:{candidates:[core,supporting],relations:[pending]}}))
  await page.goto('/')
  await expect(page.locator('.paper-row')).not.toHaveCount(0)
  await page.getByRole('button', { name: '知识摄取', exact: true }).click()
  await page.getByRole('button', { name: '方法演进', exact: true }).click()
  await expect(page.locator('.knowledge-evolution-map')).toBeVisible()
  await expect(page.locator('.knowledge-map-methods').getByRole('button',{name:/Benchmark compiler/})).toHaveCount(0)
  await expect(page.locator('.knowledge-map-node[data-layer="primary"]').filter({ hasText: 'ReAct' })).toBeVisible()
  await expect(page.locator('.knowledge-map-pending')).toContainText('BUTLER')
  for (const box of await page.locator('.knowledge-map-footer svg').evaluateAll(nodes => nodes.map(node => {
    const rect = node.getBoundingClientRect(); return { width: rect.width, height: rect.height }
  }))) {
    expect(box.width).toBeLessThanOrEqual(16)
    expect(box.height).toBeLessThanOrEqual(16)
  }
  await page.getByRole('button', { name: 'BUTLER', exact: true }).click()
  await expect(page.locator('.knowledge-entity-dossier')).toBeVisible()
})

test('crowded method neighborhoods stay inside the canvas and expose parallel evidence separately', async ({ page }) => {
  const evidence = [{chunk_id:'source',page:4,section:'Method',quote:'We use the actor and compare against it.',bbox:null,page_width:null,page_height:null}]
  const candidate = (id:string,name:string,layer:KnowledgeCandidate['layer'],paper='focus'):KnowledgeCandidate => ({
    id,paper_id:paper,entity_id:id,entity_type:layer==='evaluation'?'benchmark':'method',name,normalized_name:name.toLowerCase(),
    aliases:[],description:null,role:layer==='primary'?'proposed':'used',confidence:.95,status:'confirmed',evidence,
    conflict:{},run_id:null,model_version:null,prompt_version:null,layer,importance:'core',
  })
  const candidates = [candidate('core','Reflective method','primary'),candidate('prior','Reason and act','primary','prior'),
    ...Array.from({length:18},(_,i)=>candidate(`bench-${i}`,`Evaluation benchmark ${i+1}`,'evaluation')),
    candidate('rejected','Rejected method','primary')]
  candidates[candidates.length-1].status='rejected'
  const relation = (id:string,target:KnowledgeCandidate,kind='evaluated_on'):KnowledgeRelation => ({
    id,paper_id:'focus',relation:kind,source_name:'Reflective method',source_normalized_name:'reflective method',
    target_name:target.name,target_normalized_name:target.normalized_name,source_candidate_id:'core',target_candidate_id:target.id,
    description:`Evidence for ${kind}`,confidence:.95,status:'confirmed',evidence,conflict:{},run_id:null,model_version:null,prompt_version:null,
    family:kind==='evaluated_on'?'evaluation':kind==='requires_concept'?'dependency':'comparison',importance:'supporting',
  })
  const relations = [relation('reuse',candidates[1],'requires_concept'),relation('compare',candidates[1],'compares_with'),
    ...candidates.slice(2,-1).map((c,i)=>relation(`evaluation-${i}`,c))]
  await page.route('**/api/knowledge/overview*',route=>route.fulfill({json:{candidates,relations}}))
  let globalRelationsRequests=0
  page.on('request',request=>{if(request.url().includes('/api/knowledge/relations?'))globalRelationsRequests++})
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'方法演进',exact:true}).click()
  await page.locator('.knowledge-map-controls').getByRole('button',{name:/评测支撑\s*18/}).click()
  await expect(page.locator('.knowledge-map-node')).toHaveCount(20)
  await expect(page.getByRole('button',{name:'Rejected method',exact:true})).toHaveCount(0)
  expect(globalRelationsRequests).toBe(0)
  const layout = await page.locator('.knowledge-map-svg').evaluate(svg=>{
    const v=(svg as SVGSVGElement).viewBox.baseVal
    const nodes=Array.from(svg.querySelectorAll<SVGGElement>('.knowledge-map-node')).map(n=>{
      const r=n.querySelector('rect')!.getBBox(),m=n.transform.baseVal.consolidate()!.matrix
      return {x:r.x+m.e,y:r.y+m.f,w:r.width,h:r.height}
    })
    return {w:v.width,h:v.height,nodes}
  })
  for(const node of layout.nodes){expect(node.x).toBeGreaterThanOrEqual(0);expect(node.y).toBeGreaterThanOrEqual(0);expect(node.x+node.w).toBeLessThanOrEqual(layout.w);expect(node.y+node.h).toBeLessThanOrEqual(layout.h)}
  for(let a=0;a<layout.nodes.length;a++)for(let b=a+1;b<layout.nodes.length;b++){
    const x=layout.nodes[a],y=layout.nodes[b]
    expect(x.x+x.w<=y.x||y.x+y.w<=x.x||x.y+x.h<=y.y||y.y+y.h<=x.y).toBeTruthy()
  }
  await page.getByRole('button',{name:/Reflective method → Reason and act/}).click()
  await expect(page.locator('.knowledge-map-inspector')).toContainText('Evidence for requires_concept')
  await expect(page.locator('.knowledge-map-inspector')).toContainText('Evidence for compares_with')
  await expect(page.locator('.knowledge-map-inspector blockquote')).toHaveCount(2)
  await expect(page.locator('.knowledge-map-inspector blockquote').first()).toBeInViewport()
  await page.locator('.knowledge-map-methods').getByRole('button',{name:'Reason and act',exact:true}).click()
  await expect(page.locator('.knowledge-map-node.node-core')).toHaveAttribute('aria-label','Reason and act')
  await page.setViewportSize({width:800,height:900})
  await expect(page.locator('.knowledge-map-svg')).toBeVisible()
  expect(await page.locator('.knowledge-map-scroll').evaluate(el=>el.scrollWidth>el.clientWidth)).toBeTruthy()
})

test('catalog opens an entity dossier with papers, evidence and external links', async ({ page }) => {
  const entity={id:'hotpotqa',name:'HotPotQA',entity_type:'benchmark',normalized_name:'hotpotqa',aliases:[],description:'A multi-hop question answering benchmark.',status:'active'}
  await page.route('**/api/knowledge/entities',route=>route.fulfill({json:{items:[entity]}}))
  await page.route('**/api/knowledge/entities/hotpotqa',route=>route.fulfill({json:{...entity,candidates:[],papers:[{paper_id:'react',title:'ReAct',role:'used',status:'confirmed',evidence_count:1}],relations:[],evidence:[],links:[{kind:'official',label:'官网',url:'https://hotpotqa.github.io/',source:'reference'}]}}))
  await page.goto('/')
  await expect(page.locator('.paper-row')).not.toHaveCount(0)
  await page.getByRole('button', { name: '知识摄取', exact: true }).click()
  await page.getByRole('button', { name: '对象目录', exact: true }).click()
  await page.getByRole('button', { name: 'HotPotQA', exact: true }).click()
  await expect(page.locator('.knowledge-entity-dossier')).toContainText('HotPotQA')
  await expect(page.locator('.knowledge-dossier-papers')).toContainText('ReAct')
  await expect(page.locator('.knowledge-dossier-links')).toContainText(/官网|GitHub|搜索/)
})

test('local component roles survive canonical merging and reciprocal links remain inspectable',async({page})=>{
  const base={entity_type:'method',aliases:[],description:null,confidence:.9,status:'confirmed',evidence:[{chunk_id:'c',page:2,quote:'The local component is reused.'}],conflict:{},run_id:null,model_version:null,prompt_version:null,importance:'core'}
  const candidates=[
    {...base,id:'focus',paper_id:'a',entity_id:'focus',name:'Focus framework',normalized_name:'focus framework',role:'proposed',layer:'primary'},
    {...base,id:'other',paper_id:'b',entity_id:'other',name:'Supporting method',normalized_name:'supporting method',role:'proposed',layer:'primary'},
    {...base,id:'local',paper_id:'a',entity_id:'other',name:'Supporting method',normalized_name:'supporting method',role:'component',layer:'component'},
  ]
  const relation={...base,paper_id:'a',id:'forward',relation:'requires_concept',source_name:'Focus framework',source_normalized_name:'focus framework',target_name:'Supporting method',target_normalized_name:'supporting method',source_candidate_id:'focus',target_candidate_id:'local',description:'Forward reuse evidence',family:'dependency'}
  const reverse={...relation,paper_id:'b',id:'reverse',relation:'compares_with',source_name:relation.target_name,source_normalized_name:relation.target_normalized_name,target_name:relation.source_name,target_normalized_name:relation.source_normalized_name,source_candidate_id:'other',target_candidate_id:'focus',description:'Reverse comparison evidence',family:'comparison'}
  await page.route('**/api/knowledge/overview*',route=>route.fulfill({json:{candidates,relations:[relation,reverse]}}))
  await page.route('**/api/graph*',route=>route.fulfill({json:{nodes:[],edges:[{id:'inferred',source:'a',target:'b',relation:'cites',relation_source:'llm_inferred',description:'Unverified model inference'}]}}))
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'方法演进',exact:true}).click()
  await expect(page.locator('.knowledge-map-node[data-layer="component"]')).toHaveAttribute('aria-label','Supporting method')
  await expect(page.locator('.knowledge-map-edge')).toHaveCount(1)
  await page.getByRole('button',{name:/Focus framework ↔ Supporting method/}).click()
  await expect(page.locator('.knowledge-map-inspector')).toContainText('Forward reuse evidence')
  await expect(page.locator('.knowledge-map-inspector')).toContainText('Reverse comparison evidence')
  await expect(page.locator('.map-relation-direction')).toHaveText(['Focus framework → Supporting method','Supporting method → Focus framework'])
  await expect(page.locator('.knowledge-map-citations')).toHaveCount(0)
  await page.locator('.knowledge-map-controls').getByRole('button',{name:/方法组件/}).click()
  await expect(page.locator('.knowledge-map-node')).toHaveCount(1)
})

test('a recovered paper citation opens the original PDF at its source page',async({page,request})=>{
  const papers=(await (await request.get('/api/papers')).json()).items
  const source=papers.find((p:{page_count:number})=>p.page_count>=2),target=papers.find((p:{id:string})=>p.id!==source.id)
  const evidence={chunk_id:'reference-chunk',page:2,quote:'A locally observed reference.'}
  const core={id:'core',paper_id:source.id,entity_id:'entity',entity_type:'method',name:'Core method',normalized_name:'core method',aliases:[],description:null,role:'proposed',confidence:.9,status:'confirmed',evidence:[evidence],conflict:{},run_id:null,model_version:null,prompt_version:null,layer:'primary',importance:'core'}
  await page.route('**/api/knowledge/overview*',route=>route.fulfill({json:{candidates:[core],relations:[]}}))
  await page.route('**/api/graph*',route=>route.fulfill({json:{nodes:[{id:source.id,label:source.title,year:2023,authors:[]},{id:target.id,label:target.title,year:2022,authors:[]}],edges:[{id:'citation',source:source.id,target:target.id,relation:'cites',relation_source:'explicit',reference_label:'30',description:evidence.quote,evidence:[evidence]}]}}))
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'方法演进',exact:true}).click()
  await page.locator('.knowledge-map-citations summary').click()
  await expect(page.locator('.knowledge-map-citations')).toContainText('引用 [30]')
  await expect(page.locator('.knowledge-map-citations blockquote')).toHaveText(evidence.quote)
  await page.locator('.knowledge-map-citations').getByRole('button',{name:/原文证据/}).click()
  await expect(page.locator('.pdfv-page-input')).toHaveValue('2')
})
