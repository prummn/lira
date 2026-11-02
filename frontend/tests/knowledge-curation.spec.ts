import { expect, test, type Page, type APIRequestContext } from '@playwright/test'

async function fixture(page:Page, request:APIRequestContext) {
  const papers=(await (await request.get('/api/papers')).json()).items
  const a=papers[0], b=papers.find((p:{id:string;page_count:number})=>p.id!==a.id&&p.page_count>=2)
  const ev=(p:typeof a)=>({paper_id:p.id,paper_title:p.title,chunk_id:`c-${p.id}`,page:2,quote:'Reflexion uses ReAct.',section:'Method',bbox:null,page_width:null,page_height:null})
  const candidate=(id:string,name:string)=>({id,paper_id:b.id,entity_id:id,entity_type:'method',name,normalized_name:name.toLowerCase(),aliases:[],description:'Definition',role:'component',confidence:.9,status:'confirmed',evidence:[ev(b)],conflict:{},run_id:null,model_version:null,prompt_version:null})
  const candidates=[candidate('react','ReAct'),candidate('reflexion','Reflexion')]
  let relation={id:'r',paper_id:b.id,relation:'requires_concept',source_name:'Reflexion',source_normalized_name:'reflexion',target_name:'ReAct',target_normalized_name:'react',source_candidate_id:'reflexion',target_candidate_id:'react',source_entity_id:'reflexion',target_entity_id:'react',description:'Uses a reasoning actor.',confidence:.9,status:'candidate',evidence:[ev(b)],conflict:{},run_id:null,model_version:null,prompt_version:null}
  const manualRelations:typeof relation[]=[]
  let detail={id:'react',entity_type:'method',name:'ReAct',normalized_name:'react',aliases:[],description:'Reasoning and acting.',status:'active',candidates,papers:[{paper_id:a.id,title:a.title,role:'proposed',status:'confirmed',evidence_count:1},{paper_id:b.id,title:b.title,role:'component',status:'confirmed',evidence_count:1}],relations:[relation],evidence:[ev(a),ev(b)],links:[],history:[]} as Record<string,any>
  const other={id:'duplicate',entity_type:'method',name:'Reason and act',normalized_name:'reason and act',aliases:[],description:'Duplicate',status:'active',paper_count:1,relation_count:0}
  let mergePosts=0
  await page.route('**/api/knowledge/entities**',async route=>{
    const path=new URL(route.request().url()).pathname
    if(path.endsWith('/merge-preview')) return route.fulfill({json:{source_id:'react',source_name:detail.name,target_id:'duplicate',target_name:other.name,candidate_count:2,paper_count:2,relation_count:1,aliases:['ReAct']}})
    if(path.endsWith('/merge')) {mergePosts++;detail={...detail,id:'duplicate',name:other.name};return route.fulfill({json:detail})}
    if(path.endsWith('/entities')) return route.fulfill({json:{items:[{...detail,paper_count:2,relation_count:1},other]}})
    if(route.request().method()==='PATCH') detail={...detail,...route.request().postDataJSON(),links:route.request().postDataJSON().links.map((link:object)=>({...link,source:'user'}))}
    return route.fulfill({json:{...detail,relations:[relation,...manualRelations]}})
  })
  await page.route('**/api/knowledge/overview*',route=>route.fulfill({json:{candidates,relations:[relation]}}))
  await page.route('**/api/papers/*/knowledge/relations',route=>{
    const body=route.request().postDataJSON()
    const row={...relation,...body,id:'manual-relation',status:'candidate',source_name:candidates.find(c=>c.id===body.source_candidate_id)!.name,target_name:candidates.find(c=>c.id===body.target_candidate_id)!.name}
    manualRelations.push(row)
    return route.fulfill({status:201,json:row})
  })
  await page.route('**/api/papers/*/knowledge',route=>route.fulfill({json:{paper_id:b.id,candidates,relations:[relation],paper_status:'candidates',counts:{candidate:1}}}))
  await page.route('**/api/knowledge/relations/r**',route=>{
    const path=new URL(route.request().url()).pathname
    if(route.request().method()==='PATCH') {
      const body=route.request().postDataJSON()
      relation={...relation,...body,source_name:candidates.find(c=>c.id===body.source_candidate_id)!.name,target_name:candidates.find(c=>c.id===body.target_candidate_id)!.name,status:'candidate'}
    } else relation={...relation,status:path.endsWith('/reject')?'rejected':path.endsWith('/restore')?'candidate':'confirmed'}
    return route.fulfill({json:relation})
  })
  await page.goto('/')
  await expect(page.locator('.paper-row').first()).toBeVisible()
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'对象目录',exact:true}).click()
  await page.getByRole('button',{name:'ReAct',exact:true}).click()
  return {b,mergePosts:()=>mergePosts}
}

test('canonical editing persists and evidence opens its owning paper and page',async({page,request})=>{
  const {b}=await fixture(page,request)
  const dossier=page.locator('.knowledge-entity-dossier')
  await dossier.getByRole('button',{name:'编辑档案',exact:true}).click()
  await dossier.getByLabel('统一名称', {exact:true}).fill('Reasoning + Acting')
  await dossier.getByLabel('其他名称与缩写',{exact:true}).fill('ReAct\nReason and act')
  await dossier.getByRole('button',{name:'添加资料链接'}).click()
  await dossier.getByLabel('链接名称',{exact:true}).fill('Original paper')
  await dossier.getByLabel('网址',{exact:true}).fill('https://arxiv.org/abs/2210.03629')
  await dossier.getByRole('button',{name:'保存',exact:true}).click()
  await expect(dossier.getByRole('heading',{name:'Reasoning + Acting',exact:true})).toBeVisible()
  await dossier.getByRole('button',{name:'关闭',exact:true}).click()
  await page.reload()
  await expect(page.locator('.paper-row').first()).toBeVisible()
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'对象目录',exact:true}).click()
  await page.getByRole('button',{name:'Reasoning + Acting',exact:true}).click()
  await expect(dossier).toContainText('Reason and act')
  await expect(dossier.getByRole('link',{name:/Original paper/})).toHaveAttribute('href','https://arxiv.org/abs/2210.03629')
  await dossier.getByRole('tab',{name:'原文证据',exact:true}).click()
  await dossier.locator('.dossier-evidence-row').filter({hasText:b.title}).click()
  await expect(page.locator('.pdfv-page-input')).toHaveValue('2')
  await expect(page.locator('.reader-title')).toContainText(b.title)
})

test('relationship review supports correction, ignore and restoration without closing object',async({page,request})=>{
  await fixture(page,request)
  const dossier=page.locator('.knowledge-entity-dossier')
  await dossier.getByRole('tab',{name:/^关系/}).click()
  await dossier.getByRole('button',{name:'修正关系',exact:true}).click()
  await dossier.getByRole('button',{name:'交换方向',exact:true}).click()
  await dossier.getByLabel('关系类型',{exact:true}).selectOption('compares_with')
  await dossier.getByRole('button',{name:'保存',exact:true}).click()
  await expect(dossier.locator('.curation-relation-path')).toContainText('实验对照')
  await dossier.getByRole('button',{name:'确认关系',exact:true}).click()
  await expect(dossier.locator('.curation-relation-status')).toHaveText('已确认')
  await dossier.getByRole('button',{name:'忽略关系',exact:true}).click()
  await dossier.getByRole('button',{name:/已忽略/}).click()
  await dossier.getByRole('button',{name:'恢复审阅',exact:true}).click()
  await dossier.getByRole('button',{name:'待审阅',exact:true}).click()
  await expect(dossier.locator('.curation-relation-status')).toHaveText('待确认')
  await page.keyboard.press('Escape')
  await expect(dossier).toHaveCount(0)
  await expect(page.getByRole('button',{name:'ReAct',exact:true})).toBeFocused()
})

test('merge requires a concrete preview and explicit confirmation',async({page,request})=>{
  const state=await fixture(page,request)
  const dossier=page.locator('.knowledge-entity-dossier')
  await dossier.getByRole('button',{name:'编辑档案',exact:true}).click()
  await dossier.getByRole('button',{name:'合并重复对象',exact:true}).click()
  await dossier.getByLabel('保留哪一个对象',{exact:true}).selectOption('duplicate')
  await dossier.getByRole('button',{name:'预览合并影响',exact:true}).click()
  await expect(dossier.locator('.curation-merge-preview')).toContainText('Reason and act')
  expect(state.mergePosts()).toBe(0)
  await dossier.getByRole('button',{name:'确认合并到此对象',exact:true}).click()
  await expect(dossier.getByRole('heading',{name:'Reason and act',exact:true})).toBeVisible()
  expect(state.mergePosts()).toBe(1)
})

test('a slow relationship action prevents dossier navigation until the saved state arrives',async({page,request})=>{
  await fixture(page,request)
  let release!:()=>void
  const gate=new Promise<void>(resolve=>{release=resolve})
  await page.route('**/api/knowledge/relations/r/reject',async route=>{await gate;await route.fulfill({json:{id:'r',paper_id:'a',relation:'requires_concept',source_name:'Reflexion',target_name:'ReAct',status:'rejected',evidence:[]}})})
  const dossier=page.locator('.knowledge-entity-dossier')
  await dossier.getByRole('tab',{name:/^关系/}).click()
  await dossier.getByRole('button',{name:'忽略关系',exact:true}).click()
  await expect(dossier.getByRole('tab',{name:'概览',exact:true})).toBeDisabled()
  await expect(dossier.getByRole('button',{name:'编辑档案',exact:true})).toBeDisabled()
  release()
  await expect(dossier.getByRole('tab',{name:'概览',exact:true})).toBeEnabled()
})

test('a missing relationship can be added with a paper-local supporting quote',async({page,request})=>{
  const {b}=await fixture(page,request)
  const dossier=page.locator('.knowledge-entity-dossier')
  await dossier.getByRole('tab',{name:/^关系/}).click()
  await dossier.getByRole('button',{name:'补充关系',exact:true}).click()
  await dossier.getByLabel('证据所属论文',{exact:true}).selectOption(b.id)
  await dossier.getByLabel('起点对象',{exact:true}).selectOption('reflexion')
  await dossier.getByLabel('终点对象',{exact:true}).selectOption('react')
  await dossier.getByLabel('关系类型',{exact:true}).selectOption('compares_with')
  await dossier.getByLabel('关系说明',{exact:true}).fill('A manually reviewed comparison')
  await dossier.getByLabel('支持这条关系的原句',{exact:true}).fill('Reflexion uses ReAct.')
  const sent=page.waitForRequest(req=>req.url().endsWith(`/papers/${b.id}/knowledge/relations`)&&req.method()==='POST')
  await dossier.getByRole('button',{name:'保存并待审阅',exact:true}).click()
  const body=(await sent).postDataJSON()
  expect(body.source_candidate_id).toBe('reflexion')
  expect(body.evidence[0].quote).toBe('Reflexion uses ReAct.')
  await expect(dossier.locator('.curation-relation').filter({hasText:'A manually reviewed comparison'})).toBeVisible()
})
