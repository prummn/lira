import { expect, test, type Page } from '@playwright/test'

const issue=(id:string,status:string,extra:Record<string,unknown>={})=>({id,run_id:'contract-run',kind:'coverage',severity:'info',status,confidence:1,confidence_basis:{},auto_eligible:false,subject_ids:[],evidence:[],external_leads:[],summary:id,reasoning:'Source audit',proposed_action:{type:'curate_paper',paper_id:id},source_fingerprint:'v1',applied_change_ids:[],created_at:new Date().toISOString(),updated_at:new Date().toISOString(),...extra})
async function show(page:Page,issues:ReturnType<typeof issue>[],extra:Record<string,unknown>={}) {
  const run={id:'contract-run',scope_type:'library',scope_id:null,status:'complete',allow_external:false,model_name:null,prompt_version:'v1',source_fingerprint:'v1',started_at:null,finished_at:new Date().toISOString(),error_message:null,safe_count:0,review_count:0,conflict_count:0,applied_count:0,usage:{},issues,...extra}
  await page.route(/\/api\/knowledge\/maintenance\/runs/,route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith('/contract-run')?run:{items:[run]}}))
  const queued=issues.filter(item=>item.status==='proposed'&&item.proposed_action.type==='curate_paper')
  await page.route('**/api/knowledge/maintenance/backlog?**',route=>route.fulfill({json:{pending_papers:queued.length,
    checked_papers:0,review_papers:0,pending_objects:0,pending_relations:0,items:queued.map(item=>({
      paper_id:item.id,title:item.summary,status:'queued',run_id:run.id,pending_objects:0,pending_relations:0,error:null,
    }))}}))
  await page.goto('/')
  await page.getByRole('button',{name:'知识摄取',exact:true}).click()
  await page.getByRole('button',{name:'AI 知识整理',exact:true}).click()
  await expect(page.locator('.maintenance-status-strip')).toBeVisible()
}

test('queued paper curation is automatic work and only needs_review enters exceptions',async({page})=>{
  await show(page,[issue('Paper awaiting automatic curation','proposed'),issue('Evidence needs checking','needs_review')],{status:'partial'})
  await expect(page.locator('.maintenance-auto-queue')).toContainText('当前范围的整理进度')
  await expect(page.locator('.maintenance-auto-queue')).toContainText('Paper awaiting automatic curation')
  await expect(page.locator('.maintenance-auto-queue').getByRole('button',{name:'忽略这条建议',exact:true})).toHaveCount(0)
  await expect(page.locator('.maintenance-pending')).not.toContainText('Paper awaiting automatic curation')
  await expect(page.locator('.maintenance-pending')).toContainText('Evidence needs checking')
  await expect(page.locator('.maintenance-metrics button').filter({hasText:'需要审阅'}).locator('strong')).toHaveText('1')
})

test('accepted audits without changes expose no undo while changed records retain undo',async({page})=>{
  await show(page,[issue('Checked with no edits','accepted'),issue('Changed knowledge','auto_applied',{applied_change_ids:['change-1']})])
  await page.locator('.maintenance-history > summary').click()
  await expect(page.locator('.maintenance-detail')).toContainText('Checked with no edits')
  await expect(page.locator('.maintenance-detail').getByRole('button',{name:'撤销这次修复',exact:true})).toHaveCount(0)
  await page.locator('.maintenance-history .maintenance-queue').getByRole('button',{name:/Changed knowledge/}).click()
  await expect(page.locator('.maintenance-detail').getByRole('button',{name:'撤销这次修复',exact:true})).toBeVisible()
})

test('failed curation displays the real run error',async({page})=>{
  await show(page,[],{status:'failed',error_message:'Provider response did not contain a valid curation report.'})
  await expect(page.locator('.maintenance-status-strip')).toContainText('Provider response did not contain a valid curation report.')
})

test('paper audits show contextualized object actions only when present',async({page})=>{
  const audit={source_chars:10000,source_chunks:12,coverage:'main_text',objects_added:0,objects_confirmed:4,relations_added:0,relations_confirmed:2,aliases_linked:0,summary:'Checked the source.'}
  await show(page,[],{usage:{paper_audits:[{...audit,paper_id:'context-paper',title:'Paper with context annotations',objects_contextualized:3},{...audit,paper_id:'legacy-paper',title:'Legacy paper audit'}]}})
  const contextualized=page.locator('.maintenance-completed article').filter({hasText:'Paper with context annotations'})
  await expect(contextualized.locator('dl > div').filter({has:page.locator('dt',{hasText:'上下文标注',exact:true})}).locator('dd')).toHaveText('3')
  await expect(page.locator('.maintenance-completed article').filter({hasText:'Legacy paper audit'})).not.toContainText('上下文标注')
})
