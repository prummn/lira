import { expect, test, type Page } from '@playwright/test'

const citation = (paper = 'library-0', page = 2, id = `${paper}-${page}`) => ({
  id, paper_id: paper, title: paper === 'library-0' ? 'ReAct: Reasoning and Acting' : 'Reflexion: Verbal Reinforcement',
  source_id: id, source_text: 'Reasoning traces help the model induce, track, and update action plans.', source_type: 'paper', page, section: 'Experiments',
})
const answer = (long = false) => ({
  answer: '先比较反思与交互的作用。', provider: 'UI fixture', mode: 'remote', model: 'fixture',
  items: [{kind:'comparison',content:'## 先比较反思与交互的作用\n\nReAct 将推理与行动交替，Reflexion 将反馈转化为后续尝试的经验。\n\n'
    + (long ? Array.from({length:22},(_,i)=>`### 比较维度 ${i+1}\n\n通过同一任务的实验条件，区分方法的能力与证据的边界。\n\n`).join('') : '')
    + '| 方法 | 重点 |\n| --- | --- |\n| ReAct | 推理与行动 |\n| Reflexion | 经验与反思 |\n\n可以用 $QK^T$ 表示一个计算步骤。',
    citations:[citation(),citation(),citation('library-0',3),citation('library-1')] }],
  citations:[citation(),citation('library-0',3),citation('library-1')], insufficient_evidence:false,
  limitations:[],retrieved_paper_ids:['library-0','library-1'],queries:['reasoning'],
  coverage:{scope_papers:320,catalog_papers:200,catalog_truncated:true},usage:{total_tokens:400,model_calls:2},cached:false,
})

async function workspace(page: Page, options: {saved?:boolean; count?:number} = {}) {
  const count = options.count ?? 320
  const papers = Array.from({length:count},(_,index)=>({id:`library-${index}`,
    title:index===0?'ReAct: Reasoning and Acting':index===1?'Reflexion: Verbal Reinforcement':`Research paper ${String(index).padStart(3,'0')}`,
    authors:index===0?['Shunyu Yao']:['Research Author'],year:index===0?2022:2023,venue:'ICLR',abstract:'Research fixture',
    doi:null,arxiv_id:null,reading_status:'unread',is_favorite:false,analysis_status:'ready',tags:index===0?['agents']:[],
    collection_ids:index<10?['agents']:[],page_count:12,is_demo:false,pdf_available:true,intelligence_status:'unanalyzed'}))
  papers.push({...papers[0],id:'demo',title:'Demo excluded',is_demo:true})
  await page.route('**/api/papers?*',route=>{
    const query=new URL(route.request().url()).searchParams
    const offset=Number(query.get('offset')??0),limit=Number(query.get('limit')??200)
    return route.fulfill({json:{items:papers.slice(offset,offset+limit),total:papers.length}})
  })
  await page.route('**/api/collections',route=>route.fulfill({json:{items:[{id:'agents',name:'Agent research',paper_count:10,color:'#aa7755'}]}}))
  await page.route('**/api/settings',route=>route.fulfill({json:{provider:'UI fixture',mode:'remote',configured:true,intelligence_available:true}}))
  const chats=new Map<string,any>()
  const makeChat=(id:string,context={})=>({id,kind:'librarian',paper_id:null,context,title:'研究对话',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),turn_count:0,turns:[]})
  if(options.saved){
    const saved={...makeChat('saved-chat'),title:'比较 ReAct 与 Reflexion',turn_count:1,
      turns:[{id:'saved-turn',question:'这两篇论文有什么区别？',status:'completed',response:answer(),error:null,created_at:new Date().toISOString()}]}
    chats.set(saved.id,saved)
  }
  await page.route(/\/api\/conversations(?:\/[^?]+)?(?:\?.*)?$/,route=>{
    const url=new URL(route.request().url())
    if(route.request().method()==='POST'){
      const body=route.request().postDataJSON(),saved=makeChat(`chat-${chats.size}`,body.context)
      chats.set(saved.id,saved);return route.fulfill({status:201,json:saved})
    }
    if(url.pathname==='/api/conversations'){
      const context=url.searchParams.get('context')??'{}'
      return route.fulfill({json:{items:[...chats.values()].filter(c=>JSON.stringify(c.context)===context),has_more:false}})
    }
    return route.fulfill({json:chats.get(url.pathname.split('/').at(-1)!)})
  })
  const bodies:any[]=[]
  const save=(body:any,response:any)=>{
    const saved=chats.get(body.conversation_id)
    saved.turns.push({id:body.request_id,question:body.question,response,status:'completed',error:null,created_at:new Date().toISOString()})
    saved.turn_count=saved.turns.length;saved.title=body.question
  }
  await page.route('**/api/intelligence/ask',route=>{
    const body=route.request().postDataJSON();bodies.push(body)
    const response=answer();save(body,response);return route.fulfill({json:response})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'AI 文献员',exact:true}).click()
  const input=page.getByRole('textbox',{name:'向文献员提问'})
  await expect(input).toBeEnabled()
  return {input,bodies,save,chats,makeChat}
}

test('librarian gives one readable input the space and keeps controls within a laptop viewport',async({page})=>{
  await page.setViewportSize({width:1080,height:720})
  const {input}=await workspace(page)
  await expect(input).toBeFocused()
  await expect(input).toBeInViewport({ratio:1})
  await expect(page.locator('.librarian-scope-panel')).toHaveCount(0)
  expect(await input.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16)
  const box=(await input.boundingBox())!
  expect(box.width).toBeGreaterThan(600)
  await expect(page.getByRole('button',{name:'检索范围',exact:true})).toContainText('320')
  expect(await page.locator('.librarian-wrap').evaluate(el=>el.scrollHeight-el.clientHeight)).toBeLessThanOrEqual(1)
  await page.screenshot({path:'test-artifacts/librarian-empty-1080.png',animations:'disabled'})
})

test('scope selection searches a large library, stages edits, and excludes demo papers',async({page})=>{
  await workspace(page,{saved:true})
  const trigger=page.getByRole('button',{name:'检索范围',exact:true})
  await trigger.click()
  const dialog=page.getByRole('dialog',{name:'检索范围',exact:true})
  await dialog.getByRole('combobox',{name:'检索范围',exact:true}).selectOption('selected')
  const search=dialog.getByRole('searchbox',{name:'查找论文'})
  await expect(dialog.locator('.librarian-scope-list label')).toHaveCount(60)
  await search.fill('shunyu yao')
  await expect(dialog.getByRole('checkbox')).toHaveCount(1)
  await dialog.getByRole('checkbox',{name:/ReAct/}).check()
  await expect(page.locator('.librarian-turn')).toHaveCount(1)
  await dialog.getByRole('button',{name:'取消',exact:true}).click()
  await expect(trigger).toContainText('320')
  await trigger.click()
  await dialog.getByRole('combobox',{name:'检索范围',exact:true}).selectOption('selected')
  await search.fill('agents')
  await dialog.getByRole('checkbox',{name:/ReAct/}).check()
  await dialog.getByRole('button',{name:'应用范围',exact:true}).click()
  await expect(dialog).not.toBeVisible()
  await expect(trigger).toContainText('1')
  await expect(page.locator('.librarian-turn')).toHaveCount(0)
  await trigger.click()
  await dialog.getByRole('combobox',{name:'检索范围',exact:true}).selectOption('agents')
  await dialog.getByRole('button',{name:'应用范围',exact:true}).click()
  await expect(trigger).toContainText('Agent research')
  await expect(trigger).toContainText('10')
})

test('custom scope enforces the fifty-paper cap and can remove selected papers while filtering',async({page})=>{
  await workspace(page)
  await page.getByRole('button',{name:'检索范围',exact:true}).click()
  const dialog=page.getByRole('dialog')
  await dialog.getByRole('combobox',{name:'检索范围',exact:true}).selectOption('selected')
  const checks=dialog.locator('.librarian-scope-list input[type=checkbox]')
  for(let i=0;i<50;i++)await checks.nth(i).check()
  await expect(checks.nth(50)).toBeDisabled()
  await dialog.getByRole('button',{name:/只看已选/}).click()
  await expect(checks).toHaveCount(50)
  await dialog.getByRole('searchbox',{name:'查找论文'}).fill('Reflexion')
  await expect(checks).toHaveCount(1)
  await dialog.locator('.librarian-scope-list label').click()
  await expect(checks).toHaveCount(0)
  await dialog.getByRole('button',{name:'清空选择',exact:true}).click()
  await expect(dialog.getByRole('button',{name:'应用范围',exact:true})).toBeDisabled()
})

test('long answers start at the question, keep the composer visible, and accept safe follow-ups',async({page})=>{
  await page.setViewportSize({width:1080,height:720})
  const {input,bodies,save}=await workspace(page)
  let release!:()=>void
  await page.route('**/api/intelligence/ask',async route=>{
    const body=route.request().postDataJSON();bodies.push(body)
    if(bodies.length===1)await new Promise<void>(resolve=>{release=resolve})
    const response=answer(bodies.length===1);save(body,response)
    await route.fulfill({json:response})
  })
  await input.fill('请比较这两种方法')
  await input.dispatchEvent('keydown',{key:'Enter',isComposing:true,keyCode:229})
  expect(bodies).toHaveLength(0)
  await input.press('Shift+Enter')
  expect(await input.inputValue()).toContain('\n')
  await input.fill('请比较这两种方法')
  await input.press('Enter')
  try{
    await expect.poll(()=>bodies.length).toBe(1)
    await expect(page.locator('.librarian-user-question')).toHaveText('请比较这两种方法')
    await input.press('Enter')
    expect(bodies).toHaveLength(1)
    await input.fill('我尚未发送的追问')
    release()
    await expect(page.locator('.librarian-answer')).toBeVisible()
    await expect(page.locator('.librarian-user-question').first()).toBeInViewport({ratio:1})
    await expect(input).toBeInViewport({ratio:1})
    await expect(input).toBeFocused()
    await expect(input).toHaveValue('我尚未发送的追问')
    await input.press('Enter')
    await expect(page.locator('.librarian-answer')).toHaveCount(2)
    expect(bodies[1].history).toHaveLength(2)
    await expect(input).toHaveValue('')
    await expect(page.locator('.librarian-user-question').last()).toBeInViewport({ratio:1})
    await page.screenshot({path:'test-artifacts/librarian-conversation-1080.png',animations:'disabled'})
  }finally{release?.()}
})

test('cross-paper answers provide a grouped source directory and visible actual coverage gaps',async({page})=>{
  await workspace(page,{saved:true})
  const directory=page.locator('.librarian-sources')
  await directory.locator('summary').click()
  await expect(directory.locator('.librarian-source-paper')).toHaveCount(2)
  await expect(directory).toContainText('ReAct: Reasoning and Acting')
  await expect(directory).toContainText('Reflexion: Verbal Reinforcement')
  await page.locator('.answer-reference').first().click()
  await expect(page.locator('.answer-source-panel')).toContainText('ReAct: Reasoning and Acting')
  await expect(page.locator('.librarian-coverage-note')).toContainText('200 / 320')
  await expect(page.locator('.librarian-answer .research-markdown').first()).toHaveCSS('font-size','16px')
  await page.screenshot({path:'test-artifacts/librarian-sources-light.png',animations:'disabled'})
  await page.locator('html').evaluate(el=>el.classList.add('theme-dark'))
  await page.screenshot({path:'test-artifacts/librarian-sources-dark.png',animations:'disabled'})
})

test('narrow screens keep the input, history menu and scope dialog inside the viewport',async({page})=>{
  await page.setViewportSize({width:390,height:650})
  const {input}=await workspace(page,{saved:true})
  await expect(input).toBeInViewport({ratio:1})
  await page.locator('.conversation-history > summary').click()
  const menu=page.locator('.conversation-history-menu')
  await expect(menu).toBeInViewport({ratio:1})
  await page.keyboard.press('Escape')
  await expect(menu).not.toBeVisible()
  await page.getByRole('button',{name:'检索范围',exact:true}).click()
  const dialog=page.getByRole('dialog')
  await dialog.getByRole('combobox',{name:'检索范围',exact:true}).selectOption('selected')
  await expect(dialog.getByRole('button',{name:'应用范围',exact:true})).toBeInViewport({ratio:1})
  await expect(dialog.getByRole('searchbox',{name:'查找论文'})).toBeInViewport({ratio:1})
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole('button',{name:'检索范围',exact:true})).toBeFocused()
  await page.screenshot({path:'test-artifacts/librarian-mobile.png',animations:'disabled'})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
})

test('failure and stopping keep the draft and ignore a late answer',async({page})=>{
  const {input,bodies,save}=await workspace(page)
  let release!:()=>void
  await page.route('**/api/intelligence/ask',async route=>{
    const body=route.request().postDataJSON();bodies.push(body)
    if(bodies.length===1)return route.fulfill({status:504,json:{detail:'连接超时，请重试'}})
    if(bodies.length===2)await new Promise<void>(resolve=>{release=resolve})
    const response={...answer(),answer:bodies.length===2?'旧答案':'新答案'}
    save(body,response);await route.fulfill({json:response}).catch(()=>{})
  })
  await input.fill('需要保留的问题')
  await input.press('Enter')
  await expect(page.getByRole('alert')).toContainText('连接超时')
  await expect(input).toHaveValue('需要保留的问题')
  await input.press('Enter')
  try{
    await expect.poll(()=>bodies.length).toBe(2)
    await page.getByRole('button',{name:'停止等待',exact:true}).click()
    await expect(input).toHaveValue('需要保留的问题')
    await expect(page.locator('.librarian-notice')).toContainText('后台')
    await input.fill('修改后的问题')
    await input.press('Enter')
    await expect(page.locator('.librarian-answer')).toHaveCount(1)
    release()
    await expect(page.locator('.librarian-user-question')).toHaveText('修改后的问题')
    await expect(input).toHaveValue('')
  }finally{release?.()}
})

test('a short landscape viewport keeps the scope actions and keyboard loop reachable',async({page})=>{
  await page.setViewportSize({width:760,height:360})
  const {input}=await workspace(page)
  await expect(input).toBeInViewport({ratio:1})
  await page.getByRole('button',{name:'检索范围',exact:true}).click()
  const dialog=page.getByRole('dialog')
  await dialog.getByRole('combobox',{name:'检索范围',exact:true}).selectOption('selected')
  await expect(dialog.getByRole('searchbox',{name:'查找论文'})).toBeInViewport({ratio:1})
  await expect(dialog.getByRole('button',{name:'取消',exact:true})).toBeInViewport({ratio:1})
  await dialog.getByRole('button',{name:'取消',exact:true}).focus()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button',{name:'关闭',exact:true})).toBeFocused()
})

test('stopping while an archive is being created reuses it for subsequent questions',async({page})=>{
  const {input,bodies,chats,makeChat}=await workspace(page)
  let release!:()=>void,creates=0
  await page.route('**/api/conversations',async route=>{
    const body=route.request().postDataJSON(),saved=makeChat(`created-${++creates}`,body.context)
    chats.set(saved.id,saved)
    if(creates===1)await new Promise<void>(resolve=>{release=resolve})
    await route.fulfill({status:201,json:saved})
  })
  await input.fill('第一次问题');await input.press('Enter')
  try{
    await expect.poll(()=>creates).toBe(1)
    await page.getByRole('button',{name:'停止等待',exact:true}).click()
    await input.fill('第二次问题');await input.press('Enter')
    release()
    await expect(page.locator('.librarian-answer')).toHaveCount(1)
    await input.fill('继续追问');await input.press('Enter')
    await expect(page.locator('.librarian-answer')).toHaveCount(2)
    expect(creates).toBe(1)
    expect(bodies.map(body=>body.conversation_id)).toEqual(['created-1','created-1'])
  }finally{release?.()}
})

test('a reply finishing in the background keeps focus inside the open scope dialog',async({page})=>{
  const {input,bodies,save}=await workspace(page)
  let release!:()=>void
  await page.route('**/api/intelligence/ask',async route=>{
    const body=route.request().postDataJSON();bodies.push(body)
    await new Promise<void>(resolve=>{release=resolve})
    const response=answer();save(body,response);await route.fulfill({json:response})
  })
  await input.fill('查找相关方法');await input.press('Enter')
  try{
    await expect.poll(()=>bodies.length).toBe(1)
    await page.getByRole('button',{name:'检索范围',exact:true}).click()
    const dialog=page.getByRole('dialog')
    const select=dialog.getByRole('combobox',{name:'检索范围',exact:true})
    await select.selectOption('selected')
    const search=dialog.getByRole('searchbox',{name:'查找论文'})
    await search.fill('ReAct');release()
    await expect(page.locator('.librarian-answer')).toBeVisible()
    await expect(search).toBeFocused()
  }finally{release?.()}
})

test('bibliography labels AI and personal sources and shows both independent coverage gaps',async({page})=>{
  const {input,save}=await workspace(page)
  await page.route('**/api/intelligence/ask',route=>{
    const body=route.request().postDataJSON(),response:any=answer()
    response.items[0].citations=[{...citation(),source_type:'ai',page:null},{...citation('library-1'),source_type:'user'}]
    response.coverage.comparison_complete=false
    save(body,response);return route.fulfill({json:response})
  })
  await input.fill('回顾已有资料');await input.press('Enter')
  const directory=page.locator('.librarian-sources')
  await directory.locator('summary').click()
  await expect(directory.locator('li').filter({hasText:'ReAct'})).toContainText('AI 整理')
  await expect(directory.locator('li').filter({hasText:'Reflexion'})).toContainText('个人笔记')
  await expect(directory.locator('li').filter({hasText:'Reflexion'})).toContainText('2')
  await expect(page.locator('.librarian-coverage-note')).toContainText('200 / 320')
  await expect(page.locator('.librarian-coverage-note')).toContainText('尚未覆盖全部候选论文')
})
