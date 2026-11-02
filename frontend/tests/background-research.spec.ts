import { test, expect } from '@playwright/test'

test('collection opens a quiet essay workspace and scope survives navigation', async ({page,request}) => {
  await page.route('**/api/research/quota',route=>route.fulfill({json:{quota:[{name:'primary',used_percent:35,window_minutes:300,resets_at:2000000000}],checked_at:1792837500,available:true,budget:{allowed:false,reason:'daily_budget',allowance:10.5,observed_use:11,remaining:0,resumes_at:2000000000}}}))
  const c=await (await request.post('/api/collections',{data:{name:'Memory essay setup'}})).json()
  await page.goto('/')
  await page.locator('.collection-nav').getByRole('button',{name:c.name,exact:true}).click()
  await page.getByRole('button',{name:'专题文章',exact:true}).click()
  await expect(page.getByRole('heading',{name:/让读过的论文，\s*形成自己的认识。/})).toBeVisible()
  await page.getByRole('button',{name:'安排这个专题',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'专题研究设置'})
  await dialog.getByRole('button',{name:'刷新额度',exact:true}).click()
  await expect(dialog.getByLabel('官方剩余额度')).toContainText('剩余 65%')
  await expect(dialog.getByLabel('今日后台预算')).toContainText('今日已留足，稍后继续')
  await expect(dialog.getByLabel('今日后台预算')).toContainText('10.5')
  await expect(dialog.getByRole('checkbox',{name:'跟进阅读疑问',exact:true})).toBeVisible()
  await dialog.getByRole('textbox',{name:'研究方向',exact:true}).fill('不同记忆机制分别解决什么问题？')
  // Scope can be saved without an official profile; no generation starts.
  await dialog.getByRole('button',{name:'保存研究方向',exact:true}).click()
  await expect(dialog).not.toBeVisible()
  expect((await (await request.get(`/api/research/collections/${c.id}`)).json()).scope.focus).toContain('不同记忆机制')
  await page.getByRole('button',{name:'文献',exact:true}).click()
  await page.getByRole('button',{name:'专题文章',exact:true}).click()
  await expect(page.locator('.essay-empty')).toContainText('不同记忆机制')
  await page.screenshot({path:'test-artifacts/research-empty.png'})
})

test('essay sources, versions, export and narrow dark reading are usable', async ({page,request}) => {
  const c=await (await request.post('/api/collections',{data:{name:'Essay reading fixture'}})).json()
  const source={id:'S1',paper_id:'paper-001',title:'Original memory study',page:2,section:'Method',chunk_id:'chunk-1',text:'Memory changes decisions.',quote:'Memory changes decisions.',claim:'Stored experience guides action.'}
  const revisions=[{id:'v2',number:2,title:'记忆在什么时候改变决策？',dek:'从保存经历到改变行动，三个机制工作的层次并不相同。',changes:'补充了检索的边界。',model:'fixture',created_at:'2026-10-24T09:00:00Z'},
    {id:'v1',number:1,title:'记忆的第一次整理',dek:'旧版导语。',changes:'建立初版。',model:'fixture',created_at:'2026-10-23T09:00:00Z'}]
  await page.route(`**/api/research/collections/${c.id}*`,route=>{
    const old=route.request().url().includes('revision_id=v1')
    return route.fulfill({json:{scope:{enabled:true,focus:'比较记忆的作用位置'},revisions,task:null,
      revision:{...revisions[old?1:0],markdown:'## 记忆的工作位置\n\n一次经历只有重新进入决策，才真正成为可用的记忆。[1](#source-S1)\n\n## 证据的边界\n\n不同实验的成绩不能直接比较。[2](#source-S2 "evidence") [3](<#source-S3>) [4][memory]\n\n[memory]: #source-S4\n',sources:[source,...[2,3,4].map(n=>({...source,id:`S${n}`,page:n+1}))],coverage:[]}}})
  })
  await page.goto('/')
  await page.locator('.collection-nav').getByRole('button',{name:c.name,exact:true}).click()
  await page.getByRole('button',{name:'专题文章',exact:true}).click()
  await expect(page.getByRole('heading',{name:revisions[0].title,exact:true})).toBeVisible()
  await page.getByRole('button',{name:'查看原文 1'}).first().click()
  await expect(page.getByRole('dialog',{name:'原文出处'})).toContainText('Memory changes decisions.')
  await page.getByRole('dialog',{name:'原文出处'}).getByRole('button',{name:'关闭',exact:true}).click()
  await expect(page.getByRole('button',{name:'查看原文 1'}).first()).toBeFocused()
  await page.getByLabel('文章版本').selectOption('v1')
  await expect(page.getByRole('heading',{name:revisions[1].title,exact:true})).toBeVisible()
  await page.getByRole('button',{name:'文献',exact:true}).click()
  await page.getByRole('button',{name:'专题文章',exact:true}).click()
  await expect(page.getByRole('heading',{name:revisions[1].title,exact:true})).toBeVisible()
  const download=page.waitForEvent('download')
  await page.getByRole('button',{name:'导出文章',exact:true}).click()
  const file=await download
  expect(file.suggestedFilename()).toContain('.md')
  const stream=await file.createReadStream()
  const chunks:Buffer[]=[]
  for await(const chunk of stream!)chunks.push(Buffer.from(chunk))
  const markdown=Buffer.concat(chunks).toString('utf8')
  expect(markdown).toContain('[1](#source-S1)')
  expect(markdown).toContain('**[1] · Original memory study · p.2**')
  for(const n of [2,3,4]){
    expect(markdown).toContain(`**[${n}] · Original memory study · p.${n+1}**`)
    expect(markdown).toContain(`<a id="source-S${n}"></a>`)
  }
  expect(markdown).toContain('<a id="source-S1"></a>')
  expect(markdown).toContain('> Memory changes decisions.')
  await page.setViewportSize({width:1080,height:800})
  await page.screenshot({path:'test-artifacts/research-article.png',fullPage:true})
  await page.getByRole('button',{name:'主题',exact:true}).click()
  await page.setViewportSize({width:720,height:900})
  await page.screenshot({path:'test-artifacts/research-article-dark-narrow.png',fullPage:true})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
})
