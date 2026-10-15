import { test, expect } from '@playwright/test'

test.afterEach(async({request})=>{
  const state=await (await request.get('/api/settings/profiles')).json()
  for(const profile of state.profiles)if(['Official fixture','Relay fixture'].includes(profile.name))await request.delete(`/api/settings/profiles/${profile.id}`)
})

test('save two connections, switch, preserve each key, and configure an ordered backup', async ({ page }) => {
  // This isolated backend never contacts a real model: use Save without testing.
  await page.goto('/')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模型连接', exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: '配置名称', exact: true }).fill('Official fixture')
  await page.getByRole('textbox', { name: '模型 API 地址', exact: true }).fill('https://official.example/v1')
  await page.getByRole('textbox', { name: '模型名称', exact: true }).fill('research-official')
  await page.getByRole('textbox', { name: 'API key', exact: true }).fill('official-fixture-secret')
  await page.getByRole('button', { name: '仅保存', exact: true }).click()
  const first = page.locator('.model-profile-row').filter({ hasText: 'Official fixture' })
  await expect(first).toContainText('正在使用')
  await page.getByRole('button', { name: '新增连接', exact: true }).click()
  await page.getByRole('textbox', { name: '配置名称', exact: true }).fill('Relay fixture')
  await page.getByRole('textbox', { name: '模型 API 地址', exact: true }).fill('https://relay.example/v1')
  await page.getByRole('textbox', { name: '模型名称', exact: true }).fill('research-relay')
  await page.getByRole('textbox', { name: 'API key', exact: true }).fill('relay-fixture-secret')
  await page.getByRole('button', { name: '仅保存', exact: true }).click()
  const relay = page.locator('.model-profile-row').filter({ hasText: 'Relay fixture' })
  await relay.getByRole('button', { name: '启用', exact: true }).click()
  await expect(relay).toContainText('正在使用')
  await first.getByRole('button', { name: '加入备用', exact: true }).click()
  await page.getByRole('checkbox', { name: '分析遇到暂时故障时自动使用备用连接' }).check()
  await page.reload()
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await expect(relay).toContainText('正在使用')
  await expect(first).toContainText('备用 1')
  await relay.getByRole('button', { name: '编辑', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'API key', exact: true })).toHaveValue('')
  await expect(page.getByRole('textbox', { name: 'API key', exact: true })).toHaveAttribute('placeholder', /留空/)
  await expect(page.locator('body')).not.toContainText('fixture-secret')
  await expect(page.getByRole('checkbox', { name: '分析遇到暂时故障时自动使用备用连接' })).toBeChecked()
})

test('a slow connection test allows switching and delayed route responses preserve newer edits',async({page})=>{
  const common={base_url:'https://fixture.example/v1',model:'fixture-model',api_key_configured:true,wire_api:'responses',reasoning_effort:'high',timeout:600,max_concurrency:1,completion_parameter:'max_completion_tokens',json_mode:'json_object'}
  const first={...common,id:'official',name:'Official fixture'}, second={...common,id:'relay',name:'Relay fixture'}
  let state={profiles:[first,second],active_id:first.id,fallback_ids:[],auto_fallback:false}
  let releaseSave!:()=>void, releaseRoute!:()=>void
  const saveGate=new Promise<void>(resolve=>{releaseSave=resolve}),routeGate=new Promise<void>(resolve=>{releaseRoute=resolve})
  await page.route('**/api/settings',route=>route.fulfill({json:{provider:'FixtureProvider',mode:'remote',configured:true,translation_available:true}}))
  await page.route('**/api/settings/profiles',route=>route.fulfill({json:state}))
  await page.route('**/api/settings/profiles/official',async route=>{
    expect(route.request().postDataJSON().test_connection).toBe(true)
    await saveGate
    const updated={...first,name:'Official renamed'}
    state={...state,profiles:[updated,second]}
    await route.fulfill({json:updated})
  })
  await page.route('**/api/settings/routing',async route=>{
    state={...state,...route.request().postDataJSON()}
    const olderSnapshot=structuredClone(state)
    await routeGate
    await route.fulfill({json:olderSnapshot})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'设置',exact:true}).click()
  await page.getByRole('textbox',{name:'配置名称',exact:true}).fill('Official renamed')
  await page.getByRole('button',{name:'测试连接并保存',exact:true}).click()
  const relay=page.locator('.model-profile-row').filter({hasText:'Relay fixture'})
  await relay.getByRole('button',{name:'启用',exact:true}).click()
  await expect(relay).toContainText('正在使用')
  await expect(relay.getByRole('button',{name:'删除 Relay fixture',exact:true})).toBeDisabled()
  releaseSave()
  await expect(page.locator('.model-profile-row').filter({hasText:'Official renamed'})).toBeVisible()
  releaseRoute()
  await expect(page.locator('.model-save-success')).toContainText('已切换')
  await expect(page.locator('.model-profile-row').filter({hasText:'Official renamed'})).toBeVisible()
  await expect(relay).toContainText('正在使用')
})

test('a save begun during switching cannot restore the route from a delayed profiles response',async({page})=>{
  const common={base_url:'https://fixture.example/v1',model:'fixture-model',api_key_configured:true,wire_api:'responses',reasoning_effort:'high',timeout:600,max_concurrency:1,completion_parameter:'max_completion_tokens',json_mode:'json_object'}
  const first={...common,id:'official',name:'Official fixture'},second={...common,id:'relay',name:'Relay fixture'}
  const initial={profiles:[first,second],active_id:first.id,fallback_ids:[],auto_fallback:false}
  let saved=false
  let releaseRoute!:()=>void,releaseProfiles!:()=>void,profilesRequested!:()=>void
  const routeGate=new Promise<void>(resolve=>{releaseRoute=resolve})
  const profilesGate=new Promise<void>(resolve=>{releaseProfiles=resolve})
  const pendingProfiles=new Promise<void>(resolve=>{profilesRequested=resolve})
  await page.route('**/api/settings',route=>route.fulfill({json:{provider:'FixtureProvider',mode:'remote',configured:true,translation_available:true}}))
  await page.route('**/api/settings/profiles',async route=>{
    if(saved){profilesRequested();await profilesGate}
    await route.fulfill({json:initial})
  })
  await page.route('**/api/settings/profiles/official',async route=>{
    saved=true
    await route.fulfill({json:first})
  })
  await page.route('**/api/settings/routing',async route=>{
    const next={...initial,...route.request().postDataJSON()}
    await routeGate
    await route.fulfill({json:next})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'设置',exact:true}).click()
  const relay=page.locator('.model-profile-row').filter({hasText:'Relay fixture'})
  await relay.getByRole('button',{name:'启用',exact:true}).click()
  await expect(relay).toContainText('正在使用')
  await page.getByRole('button',{name:'仅保存',exact:true}).click()
  await pendingProfiles
  releaseRoute()
  await expect(page.locator('.model-save-success')).toContainText('已切换')
  releaseProfiles()
  await expect(page.getByRole('button',{name:'仅保存',exact:true})).toBeEnabled()
  await expect(relay).toContainText('正在使用')
})
