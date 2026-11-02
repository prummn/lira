import { test, expect } from '@playwright/test'

const catalog={default_model:'official-sol',models:[
  {id:'official-sol',model:'official-sol',display_name:'Official Sol',description:'A capable model for research.',is_default:true,default_reasoning_effort:'medium',supported_reasoning_efforts:[{effort:'low',description:'Fast'},{effort:'medium',description:'Balanced'},{effort:'high',description:'Thorough'},{effort:'max',description:'Maximum'},{effort:'ultra',description:'Ultra'}]},
  {id:'official-lite',model:'official-lite',display_name:'Official Lite',description:'Focused work.',is_default:false,default_reasoning_effort:'low',supported_reasoning_efforts:[{effort:'low',description:'Fast'},{effort:'medium',description:'Balanced'}]},
]}
test.beforeEach(async({page})=>{
  await page.route('**/api/settings/codex/models*',route=>route.fulfill({json:catalog}))
})

test('account concurrency saves independently, persists after reload and fits a narrow window', async ({page}) => {
  let limit=1
  const profile={id:'shared-codex',provider_kind:'codex',name:'Official account',base_url:'https://chatgpt.com',model:'official-sol',api_key_configured:false,reasoning_effort:'high',wire_api:'responses',timeout:600,max_concurrency:1,completion_parameter:'max_completion_tokens',json_mode:'json_object'}
  const state=()=>({profiles:[profile],active_id:profile.id,fallback_ids:[],auto_fallback:false,codex_max_concurrency:limit})
  await page.route('**/api/settings/profiles',route=>route.fulfill({json:state()}))
  await page.route('**/api/settings/codex',route=>route.fulfill({json:{available:true,authenticated:true,pending:false,email:'reader@example.com',plan:'plus',limits:[],login_url:null}}))
  await page.route('**/api/settings/codex/concurrency',route=>{
    expect(route.request().method()).toBe('PUT')
    limit=route.request().postDataJSON().max_concurrency
    return route.fulfill({json:state()})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'设置',exact:true}).click()
  const select=page.getByRole('combobox',{name:'官方账号并发',exact:true})
  await expect(select).toHaveValue('1')
  await select.selectOption('4')
  await expect(select).toBeEnabled()
  await expect(select).toHaveValue('4')
  expect(limit).toBe(4)
  await page.reload()
  await page.getByRole('button',{name:'设置',exact:true}).click()
  await expect(select).toHaveValue('4')
  await page.setViewportSize({width:520,height:900})
  await select.scrollIntoViewIfNeeded()
  const box=await select.boundingBox()
  expect(box).toBeTruthy()
  expect(box!.x).toBeGreaterThanOrEqual(0)
  expect(box!.x+box!.width).toBeLessThanOrEqual(520)
  await page.locator('.codex-concurrency').screenshot({path:'test-artifacts/codex-concurrency-narrow.png'})
  await page.getByRole('combobox',{name:'连接方式',exact:true}).selectOption('api')
  await expect(select).toHaveCount(0)
})

test('sign in with ChatGPT, show quota and save a subscription without an API key', async ({ page }) => {
  let account = { available: true, authenticated: false, pending: false, email: null as string|null,
    plan: null as string|null, limits: [] as object[], login_url: null as string|null }
  let profiles: object[] = []
  let signedIn = false
  await page.route('**/api/settings/profiles', async route => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      expect(body.provider_kind).toBe('codex')
      expect(body.api_key).toBeNull()
      expect(body.base_url).toBe('https://chatgpt.com')
      const saved = { ...body, id: 'codex-fixture', api_key_configured: false }
      profiles = [saved]
      await route.fulfill({ status: 201, json: saved })
    } else await route.fulfill({ json: { profiles, active_id: profiles.length ? 'codex-fixture' : null, fallback_ids: [], auto_fallback: false } })
  })
  await page.route('**/api/settings/codex', async route => {
    if (signedIn) account = { ...account, authenticated: true, pending: false, email: 'reader@example.com', plan: 'plus', login_url: null,
      limits: [{ name: 'primary', used_percent: 25, window_minutes: 300, resets_at: 1800000000 }] }
    await route.fulfill({ json: account })
  })
  await page.route('**/api/settings/codex/login', async route => {
    account = { ...account, pending: route.request().method() !== 'DELETE', login_url: 'https://auth.openai.com/authorize?fixture=1' }
    await route.fulfill({ json: account })
  })
  await page.route('**/api/settings/codex/logout', async route => {
    signedIn = false
    account = { ...account, authenticated: false, email: null, plan: null, limits: [] }
    await route.fulfill({ json: account })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('combobox', { name: '连接方式', exact: true }).selectOption('codex', { timeout: 8000 })
  await expect(page.getByRole('textbox', { name: 'API key', exact: true })).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: '模型 API 地址', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '登录 ChatGPT', exact: true }).click()
  const link = page.getByRole('link', { name: '前往官方页面登录', exact: true })
  await expect(link).toHaveAttribute('href', /^https:\/\/auth.openai.com\//)
  await expect(page.getByRole('button', { name: '取消登录', exact: true })).toBeVisible()
  signedIn = true
  await expect(page.getByText('reader@example.com', { exact: true })).toBeVisible({ timeout: 10000 })
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '25')
  await page.getByRole('textbox', { name: '配置名称', exact: true }).fill('ChatGPT subscription')
  await page.getByRole('button', { name: '仅保存', exact: true }).click()
  await expect(page.locator('.model-profile-row').filter({ hasText: 'ChatGPT subscription' })).toContainText('Codex 订阅')
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '登录 ChatGPT', exact: true })).toBeVisible()
})

test('missing CLI explains what to install and API connections remain editable', async ({ page }) => {
  await page.route('**/api/settings/profiles', route => route.fulfill({ json: { profiles: [], active_id: null, fallback_ids: [], auto_fallback: false } }))
  await page.route('**/api/settings/codex', route => route.fulfill({ json: { available: false, authenticated: false, pending: false, email: null, plan: null, limits: [], login_url: null, error: '未找到官方 Codex CLI' } }))
  await page.goto('/')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('combobox', { name: '连接方式', exact: true }).selectOption('codex', { timeout: 8000 })
  await expect(page.getByText('npm install -g @openai/codex', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '登录 ChatGPT', exact: true })).toBeDisabled()
  await page.getByRole('combobox', { name: '连接方式', exact: true }).selectOption('api')
  await expect(page.getByRole('textbox', { name: 'API key', exact: true })).toBeVisible()
})

test('a temporary account service failure offers refresh without asking for another login', async ({ page }) => {
  let recovered = false
  await page.route('**/api/settings/profiles', route => route.fulfill({ json: { profiles: [], active_id: null, fallback_ids: [], auto_fallback: false } }))
  await page.route('**/api/settings/codex', route => route.fulfill({ json: recovered
    ? { available: true, authenticated: true, pending: false, email: 'reader@example.com', plan: 'plus', limits: [], login_url: null }
    : { available: true, authenticated: false, pending: false, email: null, plan: null, limits: [], login_url: null, error: 'Codex 账户服务响应超时，请刷新后重试', error_code: 'transport_timeout', retryable: true } }))
  await page.goto('/')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('combobox', { name: '连接方式', exact: true }).selectOption('codex')
  await expect(page.getByRole('alert')).toContainText('Codex 账户服务响应超时')
  await expect(page.getByRole('button', { name: '登录 ChatGPT', exact: true })).toHaveCount(0)
  recovered = true
  await page.getByRole('button', { name: '刷新账户与额度', exact: true }).click()
  await expect(page.getByText('reader@example.com', { exact: true })).toBeVisible()
})

test('official model selection follows the catalog and only offers supported efforts',async({page})=>{
  let saved:any
  await page.route('**/api/settings/profiles',route=>{
    if(route.request().method()==='POST'){
      saved={...route.request().postDataJSON(),id:'new-codex',api_key_configured:false}
      return route.fulfill({status:201,json:saved})
    }
    return route.fulfill({json:{profiles:saved?[saved]:[],active_id:saved?.id??null,fallback_ids:[],auto_fallback:false}})
  })
  await page.route('**/api/settings/codex',route=>route.fulfill({json:{available:true,authenticated:true,pending:false,email:'reader@example.com',plan:'plus',limits:[],login_url:null}}))
  await page.goto('/');await page.getByRole('button',{name:'设置',exact:true}).click()
  await page.getByRole('combobox',{name:'连接方式',exact:true}).selectOption('codex')
  const model=page.getByRole('combobox',{name:'模型名称',exact:true}),effort=page.getByRole('combobox',{name:'推理强度',exact:true})
  await expect(model).toHaveValue('official-sol')
  await expect(model.locator('option')).toContainText(['Official Sol','Official Lite'])
  await expect(effort.locator('option[value="minimal"]')).toHaveCount(0)
  await expect(effort.locator('option[value="ultra"]')).toHaveCount(1)
  await effort.selectOption('ultra')
  await model.selectOption('official-lite')
  await expect(effort).toHaveValue('disabled')
  await expect(effort.locator('option[value="ultra"]')).toHaveCount(0)
  await effort.selectOption('medium')
  await page.getByRole('textbox',{name:'配置名称',exact:true}).fill('Official account')
  await page.locator('.codex-model-picker').screenshot({path:'test-artifacts/codex-model-picker.png'})
  await page.getByRole('button',{name:'测试连接并保存',exact:true}).click()
  await expect(page.locator('.model-save-success')).toContainText('连接已通过测试并保存')
  expect(saved.model).toBe('official-lite');expect(saved.reasoning_effort).toBe('medium')
  expect(saved.test_connection).toBe(true)
})

test('a saved unavailable model is shown explicitly and catalog failure can be retried without losing the draft',async({page})=>{
  let fails=true
  const profile={id:'old-codex',provider_kind:'codex',name:'My account',base_url:'https://chatgpt.com',model:'retired-model',api_key_configured:false,reasoning_effort:'high',wire_api:'responses',timeout:600,max_concurrency:1,completion_parameter:'max_completion_tokens',json_mode:'json_object'}
  await page.route('**/api/settings/profiles',route=>route.fulfill({json:{profiles:[profile],active_id:profile.id,fallback_ids:[],auto_fallback:false}}))
  await page.route('**/api/settings/codex',route=>route.fulfill({json:{available:true,authenticated:true,pending:false,email:'reader@example.com',plan:'plus',limits:[],login_url:null}}))
  await page.route('**/api/settings/codex/models*',route=>route.fulfill(fails?{status:503,json:{detail:'官方目录暂时不可用'}}:{json:catalog}))
  await page.goto('/');await page.getByRole('button',{name:'设置',exact:true}).click()
  await expect(page.locator('.codex-model-picker')).toContainText('官方目录暂时不可用')
  await expect(page.getByRole('button',{name:'测试连接并保存',exact:true})).toBeDisabled()
  await page.getByRole('textbox',{name:'配置名称',exact:true}).fill('保留我的配置名称')
  fails=false;await page.getByRole('button',{name:'刷新官方模型',exact:true}).click()
  const model=page.getByRole('combobox',{name:'模型名称',exact:true})
  await expect(model).toHaveValue('retired-model')
  await expect(page.locator('.codex-model-picker')).toContainText('不在当前官方列表')
  await expect(page.getByRole('textbox',{name:'配置名称',exact:true})).toHaveValue('保留我的配置名称')
  await expect(page.getByRole('button',{name:'仅保存',exact:true})).toBeDisabled()
  await model.selectOption('official-sol')
  await expect(page.getByRole('button',{name:'测试连接并保存',exact:true})).toBeEnabled()
})

test('an empty catalog can recover and an unsupported saved effort needs an explicit choice',async({page})=>{
  let empty=true
  const profile={id:'codex-effort',provider_kind:'codex',name:'My account',base_url:'https://chatgpt.com',model:'official-lite',api_key_configured:false,reasoning_effort:'ultra',wire_api:'responses',timeout:600,max_concurrency:1,completion_parameter:'max_completion_tokens',json_mode:'json_object'}
  await page.route('**/api/settings/profiles',route=>route.fulfill({json:{profiles:[profile],active_id:profile.id,fallback_ids:[],auto_fallback:false}}))
  await page.route('**/api/settings/codex',route=>route.fulfill({json:{available:true,authenticated:true,pending:false,email:'reader@example.com',plan:'plus',limits:[],login_url:null}}))
  await page.route('**/api/settings/codex/models*',route=>route.fulfill({json:empty?{models:[],default_model:null}:catalog}))
  await page.goto('/');await page.getByRole('button',{name:'设置',exact:true}).click()
  await expect(page.locator('.codex-model-picker')).toContainText('官方暂未返回可选模型')
  await expect(page.getByRole('button',{name:'仅保存',exact:true})).toBeDisabled()
  empty=false;await page.getByRole('button',{name:'刷新官方模型',exact:true}).click()
  const effort=page.getByRole('combobox',{name:'推理强度',exact:true})
  await expect(effort).toHaveValue('ultra')
  await expect(page.locator('.codex-model-picker')).toContainText('已保存的推理强度不受当前模型支持')
  await expect(page.getByRole('button',{name:'仅保存',exact:true})).toBeDisabled()
  await effort.selectOption('disabled')
  await expect(page.getByRole('button',{name:'仅保存',exact:true})).toBeEnabled()
  await page.locator('.model-profile-row').getByRole('button',{name:'编辑',exact:true}).click()
  await expect(effort).toHaveValue('ultra')
  await effort.selectOption('low')
  await expect(page.getByRole('button',{name:'仅保存',exact:true})).toBeEnabled()
})

test('refreshing an authenticated account refreshes its model capabilities',async({page})=>{
  let changed=false,requests=0
  const profile={id:'codex-refresh',provider_kind:'codex',name:'My account',base_url:'https://chatgpt.com',model:'official-sol',api_key_configured:false,reasoning_effort:'high',wire_api:'responses',timeout:600,max_concurrency:1,completion_parameter:'max_completion_tokens',json_mode:'json_object'}
  await page.route('**/api/settings/profiles',route=>route.fulfill({json:{profiles:[profile],active_id:profile.id,fallback_ids:[],auto_fallback:false}}))
  await page.route('**/api/settings/codex',route=>route.fulfill({json:{available:true,authenticated:true,pending:false,email:changed?'another@example.com':'reader@example.com',plan:'plus',limits:[],login_url:null}}))
  await page.route('**/api/settings/codex/models*',route=>{
    requests++
    return route.fulfill({json:changed?{...catalog,models:[catalog.models[1]],default_model:'official-lite'}:catalog})
  })
  await page.goto('/');await page.getByRole('button',{name:'设置',exact:true}).click()
  await expect(page.getByRole('button',{name:'仅保存',exact:true})).toBeEnabled()
  await page.locator('.model-profile-row').getByRole('button',{name:'编辑',exact:true}).click()
  await expect(page.getByRole('button',{name:'仅保存',exact:true})).toBeEnabled()
  const before=requests
  changed=true;await page.getByRole('button',{name:'刷新账户与额度',exact:true}).click()
  await expect(page.locator('.codex-model-picker')).toContainText('不在当前官方列表')
  expect(requests).toBeGreaterThan(before)
  await expect(page.getByRole('button',{name:'仅保存',exact:true})).toBeDisabled()
  await expect(page.getByText('another@example.com',{exact:true})).toBeVisible()
})

test('a late model catalog cannot change a different connection draft',async({page})=>{
  const one={id:'codex-one',provider_kind:'codex',name:'First',base_url:'https://chatgpt.com',model:'official-sol',api_key_configured:false,reasoning_effort:'high',wire_api:'responses',timeout:600,max_concurrency:1,completion_parameter:'max_completion_tokens',json_mode:'json_object'}
  const two={...one,id:'codex-two',name:'Second',model:'official-lite',reasoning_effort:'low'}
  let release:()=>void=()=>{},started:()=>void=()=>{}
  const pending=new Promise<void>(resolve=>{release=resolve}),began=new Promise<void>(resolve=>{started=resolve})
  let calls=0
  await page.route('**/api/settings/profiles',route=>route.fulfill({json:{profiles:[one,two],active_id:one.id,fallback_ids:[],auto_fallback:false}}))
  await page.route('**/api/settings/codex',route=>route.fulfill({json:{available:true,authenticated:true,pending:false,email:'reader@example.com',plan:'plus',limits:[],login_url:null}}))
  await page.route('**/api/settings/codex/models*',async route=>{
    calls++
    if(calls===1){started();await pending}
    await route.fulfill({json:catalog}).catch(()=>{})
  })
  await page.goto('/');await page.getByRole('button',{name:'设置',exact:true}).click();await began
  await page.locator('.model-profile-row').filter({hasText:'Second'}).getByRole('button',{name:'编辑',exact:true}).click()
  await expect(page.getByRole('combobox',{name:'模型名称',exact:true})).toHaveValue('official-lite')
  release()
  await expect(page.getByRole('textbox',{name:'配置名称',exact:true})).toHaveValue('Second')
  await expect(page.getByRole('combobox',{name:'推理强度',exact:true})).toHaveValue('low')
  await page.getByRole('combobox',{name:'连接方式',exact:true}).selectOption('api')
  await expect(page.getByRole('textbox',{name:'模型名称',exact:true})).toHaveValue('gpt-6.1-sol')
})
