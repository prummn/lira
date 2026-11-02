import { expect, test } from '@playwright/test'

test('every dense map relation has an unobstructed pointer target independent of path order',async({page})=>{
  const ev=[{chunk_id:'e',page:2,section:'Method',quote:'The benchmark compares all systems with the same setup.'}]
  const candidate=(id:string,name:string,layer='baseline')=>({id,paper_id:'paper',entity_id:id,entity_type:'method',name,normalized_name:name.toLowerCase(),aliases:[],description:null,role:layer==='primary'?'proposed':'used',confidence:.99,status:'confirmed',evidence:ev,conflict:{},layer,importance:'core'})
  const core=candidate('core','Dense benchmark','primary')
  const left=Array.from({length:16},(_,i)=>candidate('left-'+i,'Model '+String(i).padStart(2,'0')))
  const parts=Array.from({length:6},(_,i)=>candidate('part-'+i,'Component '+i,'component'))
  const relation=(id:string,source:typeof core,target:typeof core)=>({id,paper_id:'paper',relation:'requires_concept',source_name:source.name,source_normalized_name:source.normalized_name,target_name:target.name,target_normalized_name:target.normalized_name,source_candidate_id:source.id,target_candidate_id:target.id,description:'Evidence '+id,confidence:.99,status:'confirmed',evidence:ev,conflict:{},family:'dependency',importance:'supporting'})
  const relations=[relation('first',core,left[14]),...left.filter((_,i)=>i!==14).map((c,i)=>relation('model-'+i,c,core)),...parts.map((c,i)=>relation('component-'+i,core,c))]
  await page.route('**/api/knowledge/overview*',route=>route.fulfill({json:{candidates:[core,...left,...parts],relations}}))
  await page.goto('/');await expect(page.locator('.paper-row').first()).toBeVisible();await page.getByRole('button',{name:'知识摄取',exact:true}).click();await page.getByRole('button',{name:'方法演进',exact:true}).click()
  await expect(page.locator('.knowledge-map-edge')).toHaveCount(22)
  const controls=page.locator('.knowledge-map-edge-control')
  await expect(controls).toHaveCount(22)
  for(let i=0;i<await controls.count();i++){
    await controls.nth(i).scrollIntoViewIfNeeded()
    const hit=await controls.nth(i).evaluate(el=>{const r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return el===hit||el.contains(hit)})
    expect(hit,'relation '+i+' receives its own pointer click').toBe(true)
  }
  await controls.first().click();await expect(page.locator('.knowledge-map-inspector')).toContainText('Evidence first')
  await page.locator('.knowledge-map-inspector').getByRole('button',{name:'关闭',exact:true}).click()
  await controls.last().click();await expect(page.locator('.knowledge-map-inspector')).toContainText('Evidence component-5')
  await controls.first().focus();await page.keyboard.press('Enter');await expect(page.locator('.knowledge-map-inspector')).toContainText('Evidence first')
})
