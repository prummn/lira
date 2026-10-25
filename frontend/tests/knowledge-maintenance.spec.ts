import { expect, test } from '@playwright/test'

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
  await page.getByRole('button',{name:'网络维护',exact:true}).click()
  const workbench = page.getByTestId('knowledge-maintenance')
  await expect(workbench).toBeVisible()
  await expect(workbench).toContainText('可自动修复')
  await expect(workbench).toContainText('同一篇论文中存在 2 条相同对象记录')
  await expect(workbench.locator('.maintenance-evidence-row')).toContainText('The method retrieves a relevant experience.')
  await workbench.getByRole('button',{name:'应用这条建议',exact:true}).click()
  await expect(workbench).toContainText('已处理')
  await expect(workbench.getByRole('button',{name:'撤销这次修复',exact:true})).toBeVisible()
})
