import {test,expect} from '@playwright/test'

test('quota reserves can be edited from the monitor, persist and retain drafts on failure',async({page})=>{
 let settings={enabled:false,profile_id:null,idle_seconds:180,start_remaining:50,stop_remaining:35,long_reserve:30,calls_per_hour:6,maintenance_enabled:false,maintenance_interval_minutes:720,maintenance_calls_per_run:3,maintenance_scope:'library'}
 let fail=false
 const status=()=>({settings,reason:'quota_reserve',quota:[{name:'primary',used_percent:0,window_minutes:300,resets_at:1999999999},{name:'secondary',used_percent:77,window_minutes:10080,resets_at:1999999999}],quota_checked_at:1793611800,tasks:[],scope_ids:[],maintenance:null,translation_jobs:[],analysis_tasks:[]})
 await page.route('**/api/research/status',route=>route.fulfill({json:status()}))
 await page.route('**/api/research/quota-policy',route=>{
  expect(route.request().method()).toBe('PATCH')
  const payload=route.request().postDataJSON()
  expect(Object.keys(payload).sort()).toEqual(['long_reserve','start_remaining','stop_remaining'])
  if(fail)return route.fulfill({status:503,json:{detail:'暂时无法保存，请重试'}})
  settings={...settings,...payload}
  return route.fulfill({json:settings})
 })
 await page.goto('/')
 await page.getByRole('button',{name:/后台任务/}).click()
 await page.getByRole('button',{name:'调整保留线',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'额度保留线',exact:true})
 await expect(dialog).toContainText('23%')
 const long=dialog.getByRole('spinbutton',{name:'长窗口至少保留（%）',exact:true})
 await long.fill('10')
 await dialog.getByRole('button',{name:'保存保留线',exact:true}).click()
 await expect(dialog.getByRole('status')).toContainText('已保存')
 expect(settings.long_reserve).toBe(10)
 expect(settings.enabled).toBe(false)
 await dialog.getByRole('button',{name:'关闭',exact:true}).click()
 await page.reload()
 await page.getByRole('button',{name:/后台任务/}).click()
 await page.getByRole('button',{name:'调整保留线',exact:true}).click()
 await expect(long).toHaveValue('10')
 await long.fill('0')
 fail=true
 await dialog.getByRole('button',{name:'保存保留线',exact:true}).click()
 await expect(dialog.getByRole('alert')).toContainText('暂时无法保存')
 await expect(long).toHaveValue('0')
 fail=false
 await dialog.getByRole('button',{name:'保存保留线',exact:true}).click()
 await expect(dialog.getByRole('status')).toContainText('已保存')
 expect(settings.long_reserve).toBe(0)
 await page.setViewportSize({width:520,height:900})
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
 await dialog.screenshot({path:'test-artifacts/quota-controls-narrow.png'})
})
