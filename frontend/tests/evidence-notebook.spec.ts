import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { buildEvidenceIndex, type CardEntryDescriptor } from '../src/components/evidence-model'
import type { Evidence } from '../src/types'

test('evidence index collapses repeated links and preserves reverse claim relationships', () => {
  const evidence:Evidence[] = Array.from({ length:239 }, (_, index) => {
    const source = index % 66
    return {
      id:`e-${index}`,
      claim:`Claim ${index % 3}`,
      source_text:`Original source sentence ${source}`,
      page:(source % 12) + 1,
      section:source < 30 ? 'Method' : 'Results',
      confidence:.9,
      source_type:index===66?'explicit':'llm_summary',
      chunk_id:`chunk-${source}`,
    }
  })
  const entries:CardEntryDescriptor[] = [
    { id:'method-0', field:'method', label:'核心方法', content:'Claim 0', evidenceIds:evidence.filter((_, index)=>index % 3 === 0).map(item=>item.id) },
    { id:'results-0', field:'main_results', label:'主要结果', content:'Claim 1', evidenceIds:evidence.filter((_, index)=>index % 3 === 1).map(item=>item.id) },
  ]
  const groups=buildEvidenceIndex(evidence,entries)
  expect(groups).toHaveLength(66)
  expect(groups[0].evidenceIds.length).toBeGreaterThan(1)
  expect(groups[0].sourceTypes.sort()).toEqual(['explicit','llm_summary'])
  expect(groups.some(group=>group.entries.some(entry=>entry.id==='method-0'))).toBe(true)
  expect(groups.some(group=>group.entries.some(entry=>entry.id==='results-0'))).toBe(true)
})

test('evidence identity keeps same-page identical quotes apart when their coordinates differ', () => {
  const base:Evidence={id:'a',claim:'',source_text:'same quote',page:2,section:'Results',confidence:.9,source_type:'explicit',chunk_id:null,bbox:[10,10,80,24],page_width:100,page_height:100}
  const groups=buildEvidenceIndex([base,{...base,id:'b',bbox:[10,40,80,54]}],[])
  expect(groups).toHaveLength(2)
})

test('paper card exposes one evidence disclosure per conclusion and readable source details', async ({ page, request }) => {
  const bytes=Buffer.concat([await readFile(path.resolve('test-artifacts/import-fixture.pdf')),Buffer.from('\n% Evidence notebook fixture\n')])
  const imported=await request.post('/api/papers/import',{multipart:{file:{name:'evidence-notebook.pdf',mimeType:'application/pdf',buffer:bytes}}})
  expect(imported.ok()).toBeTruthy()
  const paper=await imported.json()
  paper.title='Evidence Notebook Fixture'
  await request.patch(`/api/papers/${paper.id}`,{data:{title:paper.title}})
  const analyzed=await request.post(`/api/papers/${paper.id}/analyze`)
  expect(analyzed.ok()).toBeTruthy()
  await page.goto('/')
  await page.locator('.paper-row').filter({hasText:paper.title}).getByRole('button',{name:paper.title,exact:true}).click()
  await expect(page.locator('.paper-card')).toBeVisible()
  const firstEntry=page.locator('.card-entry').filter({has:page.locator('.evidence-disclosure')}).first()
  await expect(firstEntry.locator('.evidence-disclosure')).toHaveCount(1)
  await expect(firstEntry.locator('.card-citations .text-btn')).toHaveCount(0)
  await firstEntry.locator('.evidence-disclosure summary').click()
  await expect(firstEntry.locator('.evidence-source-quote').first()).toBeVisible()
  await expect(firstEntry.getByRole('button',{name:/在 PDF 中查看/}).first()).toBeVisible()

  await page.getByRole('button',{name:'原文证据',exact:true}).click()
  await expect(page.locator('.evidence-index-notice')).toContainText('不等于自动证明')
  await expect(page.locator('.evidence-source-group').first()).toBeVisible()
  const related=page.locator('.evidence-related-entry').first()
  await expect(related).toBeVisible()
  await related.click()
  await expect(page.getByRole('button',{name:'论文卡片',exact:true})).toHaveClass(/active/)
  await expect(page.locator('.card-entry.source-target')).toBeVisible()
  await expect(page.locator('.card-entry.source-target')).toBeFocused()
})
