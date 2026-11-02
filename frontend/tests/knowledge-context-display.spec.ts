import { expect, test } from '@playwright/test'

test('context-only catalog and dossier explain paper-local examples while preserving editable canonical text',async({page})=>{
  const old='Application whose book-import metadata flow is used as a representative DeepSWE task.'
  const reason='BookWorm只作为附录中复现的SWE-Bench Pro示例应用出现。'
  const entity={id:'bookworm',name:'BookWorm',entity_type:'concept',normalized_name:'bookworm',aliases:[],description:old,status:'active',paper_count:1,relation_count:0,contextual_paper_count:1,context_only:true,context_summary:reason}
  const candidate={id:'context-candidate',paper_id:'deep',entity_id:'bookworm',entity_type:'concept',name:'BookWorm',normalized_name:'bookworm',aliases:[],description:old,role:'used',confidence:.99,status:'confirmed',evidence:[],conflict:{_steward_context:{verdict:'incidental',reason}},layer:'comparison',importance:'context'}
  await page.route('**/api/knowledge/entities**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith('/entities')?{items:[entity]}:{...entity,candidates:[candidate],papers:[{paper_id:'deep',title:'DeepSWE paper',role:'used',status:'confirmed',evidence_count:2}],relations:[],evidence:[],links:[],history:[]}}))
  await page.goto('/');await expect(page.locator('.paper-row').first()).toBeVisible()
  await page.getByRole('button',{name:'知识摄取',exact:true}).click();await page.getByRole('button',{name:'对象目录',exact:true}).click()
  const row=page.getByRole('button',{name:'BookWorm',exact:true})
  await expect(row).toContainText('文中示例');await expect(row).toContainText(reason);await expect(row).not.toContainText(old)
  await page.locator('.knowledge-search input').fill('SWE-Bench Pro');await expect(row).toBeVisible();await row.click()
  const dossier=page.getByRole('dialog')
  await expect(dossier.locator('.dossier-context-notes')).toContainText('DeepSWE paper');await expect(dossier.locator('.dossier-context-notes')).toContainText(reason)
  await expect(dossier.locator('.knowledge-dossier-papers')).toContainText('文中示例')
  const preserved=dossier.locator('.curation-preserved-description');await expect(preserved).not.toHaveAttribute('open','');await expect(preserved.locator('p')).toBeHidden()
  await preserved.locator('summary').click();await expect(preserved.locator('p')).toHaveText(old)
  await dossier.getByRole('button',{name:'编辑档案',exact:true}).click();await expect(dossier.getByLabel('定义与说明',{exact:true})).toHaveValue(old)
})

test('mixed-use objects keep their definition and scope context notes to the matching paper',async({page})=>{
  const entity={id:'tool',name:'Shared tool',entity_type:'method',normalized_name:'shared tool',aliases:[],description:'A real research method in another paper.',status:'active',paper_count:2,relation_count:1,contextual_paper_count:1,context_only:false,context_summary:'An appendix example in DeepSWE.'}
  const candidate={id:'context',paper_id:'deep',entity_id:'tool',entity_type:'method',name:'Shared tool',normalized_name:'shared tool',aliases:[],description:null,role:'used',confidence:.99,status:'confirmed',evidence:[],conflict:{_steward_context:{verdict:'incidental',reason:'An appendix example in DeepSWE.'}}}
  await page.route('**/api/knowledge/entities**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith('/entities')?{items:[entity]}:{...entity,candidates:[candidate,{...candidate,id:'actual',paper_id:'real',role:'proposed',conflict:{}}],papers:[{paper_id:'deep',title:'DeepSWE paper',role:'used',status:'confirmed',evidence_count:1},{paper_id:'real',title:'Original method paper',role:'proposed',status:'confirmed',evidence_count:1}],relations:[],evidence:[],links:[]}}))
  await page.goto('/');await expect(page.locator('.paper-row').first()).toBeVisible();await page.getByRole('button',{name:'知识摄取',exact:true}).click();await page.getByRole('button',{name:'对象目录',exact:true}).click()
  const row=page.getByRole('button',{name:'Shared tool',exact:true});await expect(row).toContainText('含文中示例');await expect(row).toContainText(entity.description);await row.click()
  const dossier=page.getByRole('dialog');await expect(dossier.locator('.curation-definition')).toHaveText(entity.description);await expect(dossier.locator('.dossier-context-notes')).toContainText('DeepSWE paper');await expect(dossier.locator('.dossier-context-notes')).not.toContainText('Original method paper')
  await expect(dossier.locator('.dossier-paper-row').filter({hasText:'Original method paper'})).toContainText('本文提出')
})
