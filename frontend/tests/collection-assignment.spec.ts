import { test, expect, type Page, type APIRequestContext } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

async function fixture(request: APIRequestContext, label: string) {
  const paper = await (await request.post('/api/papers', {data: {title: `Memory study ${label}`, author_names: ['Alice Researcher'], year: 2026}})).json()
  const other = await (await request.post('/api/papers', {data: {title: `Other study ${label}`}})).json()
  const collection = await (await request.post('/api/collections', {data: {name: `Memory初探 ${label}`}})).json()
  return {paper, other, collection}
}
const rowFor = (page: Page, title: string) => page.locator('.paper-row').filter({has: page.getByRole('button', {name: title, exact: true})})
const dialogFor = (page: Page) => page.getByRole('dialog', {name: '加入集合', exact: true})

test.describe('LibraryPage mock 删除', () => {
  async function deletionFixture(page: Page, options: { failFirst?: boolean; partial?: boolean; scope?: string; language?: string } = {}) {
    const original = ['待删除论文甲', '待删除论文乙', '保留论文丙'].map((title, index) => ({
      id: `delete-fixture-${index}`, title, authors: ['Mock Author'], year: 2026, venue: 'Mock venue',
      reading_status: 'unread', is_favorite: false, analysis_status: 'ready', tags: [],
      collection_ids: ['delete-fixture-collection'], page_count: 2, is_demo: false,
      pdf_available: false, intelligence_status: 'unanalyzed',
    }))
    let papers = [...original]
    let collections = [{ id: 'delete-fixture-collection', name: 'Mock 专题', description: '', color: '#536f89', paper_count: papers.length }]
    const collectionCalls: { method: string; pathname: string; body: unknown }[] = []
    const calls: { method: string; pathname: string; body: unknown }[] = []
    const reads = { papers: 0, collections: 0, activity: 0 }
    await page.addInitScript(({scope,language}) => {localStorage.setItem('riw-language', language ?? 'zh-CN');if(scope)localStorage.setItem('riw-librarian-scope',JSON.stringify({scope,selectedIds:['delete-fixture-0']}))}, options)
    // 所有 API 都在浏览器内响应，未列出的请求也不得进入真实库。
    await page.route('**/api/**', async route => {
      const request = route.request()
      const pathname = new URL(request.url()).pathname
      const method = request.method()
      if (method === 'DELETE' && pathname.startsWith('/api/collections/')) {
        collectionCalls.push({method,pathname,body:null})
        if(options.failFirst && collectionCalls.length===1)return route.fulfill({status:503,json:{detail:'集合删除失败，请重试'}})
        const id=decodeURIComponent(pathname.split('/').at(-1)!)
        collections=collections.filter(collection=>collection.id!==id)
        papers=papers.map(paper=>({...paper,collection_ids:paper.collection_ids.filter(value=>value!==id)}))
        return route.fulfill({status:204})
      }
      if (method === 'DELETE' || (method === 'POST' && pathname === '/api/papers/batch-delete')) {
        const body = request.postData() ? request.postDataJSON() : null
        calls.push({ method, pathname, body })
        if (options.failFirst && calls.length === 1) {
          return route.fulfill({ status: 503, json: { detail: '删除测试失败，请重试' } })
        }
        const ids: string[] = method === 'DELETE' ? [pathname.split('/').at(-1)!] : body.paper_ids
        const deleted_ids = options.partial ? ids.slice(0, 1) : ids
        papers = papers.filter(paper => !deleted_ids.includes(paper.id))
        return route.fulfill({ json: { deleted_ids } })
      }
      if (method === 'GET' && pathname === '/api/papers') {
        reads.papers++
        return route.fulfill({ json: { items: papers, total: papers.length } })
      }
      if (method === 'POST' && pathname === '/api/collections') {
        const body = request.postDataJSON()
        collectionCalls.push({ method, pathname, body })
        const collection = { id: `mock-collection-${collections.length}`, name: body.name, description: body.description ?? '', color: body.color, paper_count: 0 }
        collections.push(collection)
        return route.fulfill({ status: 201, json: collection })
      }
      if (method === 'GET' && pathname === '/api/collections') {
        reads.collections++
        return route.fulfill({ json: { items: collections.map(collection => collection.id === 'delete-fixture-collection' ? { ...collection, paper_count: papers.length } : collection) } })
      }
      if (method === 'GET' && pathname === '/api/settings') {
        return route.fulfill({ json: { provider: 'Mock', mode: 'local', configured: false, intelligence_available: false } })
      }
      if (method === 'GET' && pathname === '/api/activity') {
        reads.activity++
        return route.fulfill({ json: { days: [], total: 0, streak: 0, active_days_30: 0 } })
      }
      if (method === 'POST' && pathname === '/api/research/presence') return route.fulfill({ json: { ok: true } })
      return route.fulfill({ status: 503, json: { detail: `未配置的 mock API: ${method} ${pathname}` } })
    })
    await page.goto('/')
    await expect(page.locator('.paper-row')).toHaveCount(3)
    // React StrictMode runs mount effects twice in the development server.
    await expect.poll(() => reads.activity).toBeGreaterThanOrEqual(2)
    const initialReads = { ...reads }
    return { original, calls, collectionCalls, reads, initialReads, row: (index: number) => rowFor(page, original[index].title) }
  }

  test('隔离 mock：未选择、选中数量与清除提示正确，全选保留无障碍名称', async ({ page }) => {
    const { row, calls, collectionCalls } = await deletionFixture(page)
    const bar = page.locator('.batch-analysis-bar')
    const selection = bar.locator('label span')
    const selectAll = bar.getByRole('checkbox', { name: '选择当前列表', exact: true })
    await expect(selection).toHaveText('未选择')
    await expect(selectAll).not.toBeChecked()
    await row(0).getByRole('checkbox').check()
    await expect(selection).toHaveText('1 已选择')
    await expect(selectAll).toHaveAccessibleName('选择当前列表')
    await row(1).getByRole('checkbox').check()
    await expect(selection).toHaveText('2 已选择')
    await selectAll.check()
    await expect(selection).toHaveText('3 已选择')
    await expect(selectAll).toBeChecked()
    await expect(selectAll).toHaveAccessibleName('选择当前列表')
    await bar.getByRole('button', { name: '取消选择', exact: true }).click()
    await expect(selection).toHaveText('未选择')
    await expect(selectAll).not.toBeChecked()
    await expect(selectAll).toHaveAccessibleName('选择当前列表')
    await expect(page.locator('.paper-row input[type="checkbox"]:checked')).toHaveCount(0)
    expect(calls).toEqual([])
    expect(collectionCalls).toEqual([])
  })

  test('隔离 mock：新建集合保存所选颜色，重新读取后侧栏颜色持久化', async ({ page }) => {
    const { collectionCalls, reads, initialReads } = await deletionFixture(page)
    await page.getByRole('button', { name: '新建集合', exact: true }).first().click()
    const dialog = page.getByRole('dialog', { name: '新建集合', exact: true })
    const color = dialog.getByLabel('集合颜色', { exact: true })
    await expect(color).toHaveAttribute('type', 'color')
    await expect(color).toHaveAttribute('aria-label', '集合颜色')
    await expect(color).toHaveValue('#536f89')
    await expect(dialog.getByText('为该集合的灵魂添笔色彩', {exact:true})).toBeVisible()
    await expect(dialog.locator('.collection-color-control .collection-dot')).toHaveCount(0)
    await expect(dialog.locator('.collection-color-brush svg')).toBeVisible()
    await expect(dialog.locator('.collection-color-brush svg path')).toHaveCount(1)
    await expect(dialog.locator('.collection-color-brush svg path')).toHaveAttribute('fill', 'currentColor')
    await expect(dialog.locator('.collection-color-brush svg [stroke], .collection-color-brush svg [opacity], .collection-color-brush svg linearGradient')).toHaveCount(0)
    await expect(color).toHaveCSS('opacity','0')
    await expect(color).toHaveCSS('position','absolute')
    await expect(color).toHaveCSS('border-top-width','0px')
    await dialog.getByRole('textbox', { name: '名称', exact: true }).fill('持久颜色专题')
    await color.fill('#e35d6a')
    await expect(color).toHaveValue('#e35d6a')
    expect(collectionCalls).toEqual([])
    await dialog.getByRole('button', { name: '创建', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    expect(collectionCalls).toEqual([{ method: 'POST', pathname: '/api/collections', body: { name: '持久颜色专题', description: '', color: '#e35d6a' } }])
    await expect.poll(() => reads.collections).toBeGreaterThan(initialReads.collections)
    const dot = page.locator('.collection-nav').getByRole('button', { name: '持久颜色专题', exact: true }).locator('.collection-dot')
    await expect(dot).toHaveCSS('background-color', 'rgb(227, 93, 106)')
    const readsBeforeReload = reads.collections
    const response = page.waitForResponse(response => new URL(response.url()).pathname === '/api/collections' && response.request().method() === 'GET')
    await page.reload()
    expect((await (await response).json()).items).toContainEqual(expect.objectContaining({ name: '持久颜色专题', color: '#e35d6a' }))
    await expect.poll(() => reads.collections).toBeGreaterThan(readsBeforeReload)
    await expect(dot).toHaveCSS('background-color', 'rgb(227, 93, 106)')
    expect(collectionCalls).toHaveLength(1)
  })

  test('隔离 mock：新建集合选择颜色后取消不发送保存请求', async ({ page }) => {
    const { collectionCalls, reads, initialReads } = await deletionFixture(page)
    await page.getByRole('button', { name: '新建集合', exact: true }).first().click()
    const dialog = page.getByRole('dialog', { name: '新建集合', exact: true })
    const color = dialog.getByLabel('集合颜色', { exact: true })
    await expect(color).toHaveAttribute('type', 'color')
    await expect(color).toHaveAttribute('aria-label', '集合颜色')
    await expect(color).toHaveValue('#536f89')
    await dialog.getByRole('textbox', { name: '名称', exact: true }).fill('取消颜色专题')
    await color.fill('#e35d6a')
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    expect(collectionCalls).toEqual([])
    expect(reads.collections).toBe(initialReads.collections)
    await expect(page.locator('.collection-nav').getByRole('button', { name: '取消颜色专题', exact: true })).toHaveCount(0)
  })

  test('隔离 mock：集合与其他页面没有新建入口，全部论文空集合分配可创建', async ({page})=>{
    const {original,collectionCalls}=await deletionFixture(page)
    const nav=page.locator('.collection-nav')
    await nav.getByRole('button',{name:'Mock 专题',exact:true}).click()
    await expect(page.getByRole('button',{name:'新建集合',exact:true})).toHaveCount(0)
    await page.locator('.batch-analysis-bar').getByRole('checkbox').check()
    await page.locator('.batch-analysis-bar').getByRole('button',{name:'加入集合',exact:true}).click()
    await expect(dialogFor(page).getByRole('button',{name:'新建集合',exact:true})).toHaveCount(0)
    await dialogFor(page).getByRole('button',{name:'取消',exact:true}).click()
    await page.getByRole('button',{name:'添加已有论文',exact:true}).click()
    const existing=page.getByRole('dialog',{name:'添加已有论文',exact:true})
    await expect(existing.getByRole('button',{name:'新建集合',exact:true})).toHaveCount(0)
    await existing.getByRole('button',{name:'取消',exact:true}).click()
    await nav.getByRole('button',{name:'全部论文',exact:true}).click()
    await expect(page.getByRole('button',{name:'新建集合',exact:true})).toHaveCount(2)
    await page.getByRole('button',{name:'知识摄取',exact:true}).click()
    await expect(page.getByRole('button',{name:'新建集合',exact:true})).toHaveCount(0)
    await nav.getByRole('button',{name:'全部论文',exact:true}).click()
    await page.route('**/api/collections',route=>route.fulfill({json:{items:[]}}))
    await page.reload()
    await rowFor(page,original[0].title).getByRole('checkbox').check()
    await page.locator('.batch-analysis-bar').getByRole('button',{name:'加入集合',exact:true}).click()
    await dialogFor(page).getByRole('button',{name:'新建集合',exact:true}).click()
    await expect(page.getByRole('dialog',{name:'新建集合',exact:true})).toBeVisible()
    expect(collectionCalls).toEqual([])
  })

  test('隔离 mock：删除集合取消保留所有论文，不发请求',async({page})=>{
    const {calls,collectionCalls}=await deletionFixture(page)
    await page.locator('.collection-nav').getByRole('button',{name:'Mock 专题',exact:true}).click()
    await page.getByRole('button',{name:'删除该集合',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:'删除该集合',exact:true})
    await expect(dialog.locator(':scope > p')).toHaveText('是否确认删除集合“Mock 专题”')
    await dialog.getByRole('button',{name:'取消',exact:true}).click()
    await expect(dialog).not.toBeVisible()
    await expect(page.locator('.paper-row')).toHaveCount(3)
    expect(calls).toEqual([]);expect(collectionCalls).toEqual([])
  })

  test('隔离 mock：删除集合 204 返回全部论文，清除 scope，不删除论文',async({page})=>{
    const {calls,collectionCalls,reads,initialReads}=await deletionFixture(page,{scope:'delete-fixture-collection'})
    await page.locator('.collection-nav').getByRole('button',{name:'Mock 专题',exact:true}).click()
    await page.locator('.batch-analysis-bar').getByRole('checkbox').check()
    await page.getByRole('button',{name:'删除该集合',exact:true}).click()
    await page.getByRole('dialog',{name:'删除该集合',exact:true}).getByRole('button',{name:'确认',exact:true}).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.locator('.collection-nav').getByRole('button',{name:'Mock 专题',exact:true})).toHaveCount(0)
    await expect(page.locator('.collection-nav').getByRole('button',{name:'全部论文',exact:true})).toHaveClass(/active/)
    await expect(page.locator('.paper-row')).toHaveCount(3)
    await expect(page.locator('.batch-analysis-bar')).toContainText('未选择')
    await expect.poll(()=>page.evaluate(()=>JSON.parse(localStorage.getItem('riw-librarian-scope')!))).toEqual({scope:'',selectedIds:[]})
    expect(reads.papers).toBe(initialReads.papers+1)
    expect(reads.collections).toBe(initialReads.collections+1)
    expect(calls).toEqual([])
    expect(collectionCalls).toEqual([{method:'DELETE',pathname:'/api/collections/delete-fixture-collection',body:null}])
  })

  test('隔离 mock：集合删除失败可重试，busy 禁止重复与全部关闭方式',async({page})=>{
    const {calls,collectionCalls}=await deletionFixture(page,{failFirst:true})
    await page.locator('.collection-nav').getByRole('button',{name:'Mock 专题',exact:true}).click()
    await page.getByRole('button',{name:'删除该集合',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:'删除该集合',exact:true})
    await dialog.getByRole('button',{name:'确认',exact:true}).click()
    await expect(dialog.getByRole('alert')).toContainText('集合删除失败，请重试')
    await expect(page.locator('.paper-row')).toHaveCount(3)
    let release!:()=>void
    const pending=new Promise<void>(resolve=>{release=resolve})
    await page.route('**/api/collections/delete-fixture-collection',async route=>{await pending;await route.fallback()})
    try {
      await dialog.getByRole('button',{name:'确认',exact:true}).click()
      await expect(dialog.getByRole('button',{name:'确认',exact:true})).toBeDisabled()
      await expect(dialog.getByRole('button',{name:'取消',exact:true})).toBeDisabled()
      await dialog.getByRole('button',{name:'关闭',exact:true}).click()
      await page.keyboard.press('Escape')
      await page.locator('.modal-backdrop').click({position:{x:5,y:5}})
      await expect(dialog).toBeVisible()
    } finally {release()}
    await expect(dialog).not.toBeVisible()
    await expect(page.locator('.paper-row')).toHaveCount(3)
    expect(calls).toEqual([])
    expect(collectionCalls).toHaveLength(2)
    expect(collectionCalls[1]).toEqual(collectionCalls[0])
  })

  test('隔离 mock：英文颜色提示与删除确认',async({page})=>{
    await deletionFixture(page,{language:'en-US'})
    await page.getByRole('button',{name:'New collection',exact:true}).first().click()
    const create=page.getByRole('dialog',{name:'New collection',exact:true})
    await expect(create.getByLabel('Collection color',{exact:true})).toHaveAttribute('type','color')
    await expect(create).toContainText('Add a stroke of color to this collection’s soul')
    await create.getByRole('button',{name:'Cancel',exact:true}).click()
    await page.locator('.collection-nav').getByRole('button',{name:'Mock 专题',exact:true}).click()
    await page.getByRole('button',{name:'Delete collection',exact:true}).click()
    await expect(page.getByRole('dialog',{name:'Delete collection',exact:true}).locator(':scope > p')).toHaveText('Delete collection “Mock 专题”?')
  })

  test('单篇删除按钮位于打开箭头之后，取消确认不发送请求', async ({ page }) => {
    const { original, row, calls, reads, initialReads } = await deletionFixture(page)
    const actions = row(0).locator('.row-actions')
    const button = actions.getByRole('button', { name: `${original[0].title} 删除论文`, exact: true })
    await expect(button).toBeVisible()
    await expect(actions.locator('button').nth(2)).toHaveAccessibleName('打开论文')
    await expect(actions.locator('button').nth(3)).toHaveAccessibleName(`${original[0].title} 删除论文`)
    expect(await button.evaluate(element => element.previousElementSibling?.querySelector('svg')?.classList.contains('lucide-arrow-up-right'))).toBe(true)
    await button.click()
    const dialog = page.getByRole('dialog', { name: '删除论文', exact: true })
    await expect(dialog.locator(':scope > p')).toHaveText(`是否确认删除论文“${original[0].title}”`)
    await expect(dialog.locator('.delete-paper-list')).toHaveCount(0)
    await expect(dialog.getByText(original[0].title, { exact: false })).toHaveCount(1)
    await expect(dialog).not.toContainText('永久删除')
    await expect(dialog).not.toContainText('此操作无法撤销')
    expect(calls).toEqual([])
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await expect(row(0)).toBeVisible()
    await expect(page.locator('.paper-row')).toHaveCount(3)
    expect(calls).toEqual([])
    expect(reads.papers).toBe(initialReads.papers)
    await expect(page.locator('.reader-toolbar')).toHaveCount(0)
  })

  test('单篇确认只发送 DELETE，成功刷新列表、专题计数及活动', async ({ page }) => {
    const { original, row, calls, reads, initialReads } = await deletionFixture(page)
    await row(0).getByRole('button', { name: `${original[0].title} 删除论文`, exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '删除论文', exact: true })
    expect(calls).toEqual([])
    await dialog.getByRole('button', { name: '确认', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await expect(row(0)).toHaveCount(0)
    await expect(page.locator('.paper-row')).toHaveCount(2)
    await expect(row(1)).toBeVisible()
    await expect(page.locator('.collection-nav').getByRole('button', { name: 'Mock 专题', exact: true }).locator('small')).toHaveText('2')
    await expect.poll(() => reads.papers).toBe(initialReads.papers + 1)
    await expect.poll(() => reads.collections).toBe(initialReads.collections + 1)
    await expect.poll(() => reads.activity).toBe(initialReads.activity + 1)
    expect(calls).toEqual([{ method: 'DELETE', pathname: `/api/papers/${original[0].id}`, body: null }])
  })

  test('批量选择后取消不请求，确认仅删除所选并刷新清空选择', async ({ page }) => {
    const { original, row, calls, reads, initialReads } = await deletionFixture(page)
    const batch = page.getByRole('button', { name: '批量删除', exact: true })
    await expect(batch).toBeDisabled()
    await row(0).getByRole('checkbox').check()
    await row(1).getByRole('checkbox').check()
    await expect(page.locator('.batch-analysis-bar')).toContainText('2 已选择')
    await batch.click()
    const dialog = page.getByRole('dialog', { name: '批量删除', exact: true })
    await expect(dialog.locator(':scope > p')).toHaveText('是否确认删除以下 2 篇论文')
    await expect(dialog).not.toContainText('永久删除')
    await expect(dialog).not.toContainText('此操作无法撤销')
    await expect(dialog.locator('.delete-paper-list li')).toHaveText(original.slice(0, 2).map(paper => paper.title))
    expect(calls).toEqual([])
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    expect(calls).toEqual([])
    await expect(row(0).getByRole('checkbox')).toBeChecked()
    await expect(row(1).getByRole('checkbox')).toBeChecked()
    await batch.click()
    await dialog.getByRole('button', { name: '确认', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await expect(page.locator('.paper-row')).toHaveCount(1)
    await expect(row(2)).toBeVisible()
    await expect(row(2).getByRole('checkbox')).not.toBeChecked()
    await expect(batch).toBeDisabled()
    await expect(page.locator('.batch-analysis-bar')).not.toContainText('已选择')
    await expect.poll(() => reads.papers).toBe(initialReads.papers + 1)
    expect(calls).toEqual([{ method: 'POST', pathname: '/api/papers/batch-delete', body: { paper_ids: original.slice(0, 2).map(paper => paper.id) } }])
  })

  test('批量删除失败保留弹窗、列表和选择，可使用相同请求重试', async ({ page }) => {
    const { original, row, calls, reads, initialReads } = await deletionFixture(page, { failFirst: true })
    await row(0).getByRole('checkbox').check()
    await row(1).getByRole('checkbox').check()
    await page.getByRole('button', { name: '批量删除', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '批量删除', exact: true })
    const confirm = dialog.getByRole('button', { name: '确认', exact: true })
    await confirm.click()
    await expect(dialog.getByRole('alert')).toContainText('删除测试失败，请重试')
    await expect(confirm).toBeEnabled()
    await expect(page.locator('.paper-row')).toHaveCount(3)
    await expect(row(0).getByRole('checkbox')).toBeChecked()
    await expect(row(1).getByRole('checkbox')).toBeChecked()
    await expect(page.locator('.batch-analysis-bar')).toContainText('2 已选择')
    await expect(dialog.locator('.delete-paper-list li')).toHaveText(original.slice(0, 2).map(paper => paper.title))
    expect(reads.papers).toBe(initialReads.papers)
    expect(calls).toHaveLength(1)
    await confirm.click()
    await expect(dialog).not.toBeVisible()
    await expect(page.locator('.paper-row')).toHaveCount(1)
    expect(calls).toHaveLength(2)
    expect(calls[1]).toEqual(calls[0])
    await expect(page.getByRole('button', { name: '批量删除', exact: true })).toBeDisabled()
  })

  for (const batch of [false, true]) {
    test(`${batch ? '批量' : '单篇'}删除处理中禁止重复确认及关闭`, async ({ page }) => {
      const { original, row, calls } = await deletionFixture(page)
      let release!: () => void
      const pending = new Promise<void>(resolve => { release = resolve })
      await page.route(batch ? '**/api/papers/batch-delete' : `**/api/papers/${original[0].id}`, async route => {
        await pending
        await route.fallback()
      })
      if (batch) {
        await row(0).getByRole('checkbox').check()
        await row(1).getByRole('checkbox').check()
        await page.getByRole('button', { name: '批量删除', exact: true }).click()
      } else {
        await row(0).getByRole('button', { name: `${original[0].title} 删除论文`, exact: true }).click()
      }
      const dialog = page.getByRole('dialog', { name: batch ? '批量删除' : '删除论文', exact: true })
      try {
        await dialog.getByRole('button', { name: '确认', exact: true }).click()
        await expect(dialog.getByRole('button', { name: '正在删除…', exact: true })).toBeDisabled()
        await expect(dialog.getByRole('button', { name: '取消', exact: true })).toBeDisabled()
        await dialog.getByRole('button', { name: '关闭', exact: true }).click()
        await expect(dialog).toBeVisible()
        await page.keyboard.press('Escape')
        await expect(dialog).toBeVisible()
        await page.locator('.modal-backdrop').click({ position: { x: 5, y: 5 } })
        await expect(dialog).toBeVisible()
      } finally {
        release()
      }
      await expect(dialog).not.toBeVisible()
      expect(calls).toHaveLength(1)
      await expect(page.locator('.paper-row')).toHaveCount(batch ? 1 : 2)
    })
  }

  test('批量响应按 deleted_ids 清除选择，未删除论文仍保持选中', async ({ page }) => {
    const { original, row, calls } = await deletionFixture(page, { partial: true })
    await row(0).getByRole('checkbox').check()
    await row(1).getByRole('checkbox').check()
    await page.getByRole('button', { name: '批量删除', exact: true }).click()
    await page.getByRole('dialog', { name: '批量删除', exact: true }).getByRole('button', { name: '确认', exact: true }).click()
    await expect(row(0)).toHaveCount(0)
    await expect(row(1).getByRole('checkbox')).toBeChecked()
    await expect(row(2).getByRole('checkbox')).not.toBeChecked()
    await expect(page.locator('.batch-analysis-bar')).toContainText('1 已选择')
    await expect(page.getByRole('button', { name: '批量删除', exact: true })).toBeEnabled()
    expect(calls[0].body).toEqual({ paper_ids: original.slice(0, 2).map(paper => paper.id) })
  })
})

test('unfiled paper has an explicit action; search, cancel, save and reload preserve membership', async ({page, request}) => {
  const {paper, collection} = await fixture(request, 'single')
  await page.goto('/')
  const row = rowFor(page, paper.title)
  await row.getByRole('button', {name: `${paper.title} 加入集合`, exact: true}).click()
  let dialog = dialogFor(page)
  await dialog.getByRole('searchbox', {name: '搜索集合'}).fill(collection.name)
  await dialog.getByRole('radio', {name: collection.name, exact: true}).check()
  await dialog.getByRole('button', {name: '取消', exact: true}).click()
  expect((await (await request.get(`/api/papers/${paper.id}`)).json()).collection_ids).toEqual([])
  await expect(row.getByRole('button', {name: `${paper.title} 加入集合`, exact: true})).toBeFocused()
  await row.getByRole('button', {name: `${paper.title} 加入集合`, exact: true}).click()
  dialog = dialogFor(page)
  await dialog.getByRole('radio', {name: collection.name, exact: true}).check()
  await page.screenshot({path: 'test-artifacts/collection-destination.png'})
  await dialog.getByRole('button', {name: '确认加入', exact: true}).click()
  await expect(dialog).not.toBeVisible()
  await expect(row.locator('.collection-summary')).toContainText(collection.name)
  await page.reload()
  await page.locator('.collection-nav').getByRole('button', {name: collection.name, exact: true}).click()
  await expect(rowFor(page, paper.title)).toBeVisible()
  await expect(page.locator('.collection-nav').getByRole('button', {name: collection.name, exact: true})).toContainText('1')
})

test('selected papers can join another topic without losing earlier membership', async ({page, request}) => {
  const {paper, other, collection} = await fixture(request, 'batch')
  const prior = await (await request.post('/api/collections', {data: {name: 'Earlier topic'}})).json()
  await request.put(`/api/collections/${prior.id}/papers/${paper.id}`)
  await page.goto('/')
  await rowFor(page, paper.title).getByRole('checkbox').check()
  await rowFor(page, other.title).getByRole('checkbox').check()
  await page.locator('.batch-analysis-bar').getByRole('button', {name: '加入集合', exact: true}).click()
  const dialog = dialogFor(page)
  await expect(dialog).toContainText('2 篇论文')
  await dialog.getByRole('radio', {name: collection.name, exact: true}).check()
  await dialog.getByRole('button', {name: '确认加入', exact: true}).click()
  await expect(dialog).not.toBeVisible()
  await expect(rowFor(page, paper.title).locator('.collection-summary')).toContainText(collection.name)
  expect((await (await request.get(`/api/papers/${paper.id}`)).json()).collection_ids.sort()).toEqual([prior.id, collection.id].sort())
  expect((await (await request.get(`/api/collections/${collection.id}`)).json()).paper_count).toBe(2)
})

test('empty collection adds existing papers; filtering keeps selection and saved papers disappear from candidates', async ({page, request}) => {
  const {paper, other, collection} = await fixture(request, 'from-topic')
  await page.goto('/')
  await page.locator('.collection-nav').getByRole('button', {name: collection.name, exact: true}).click()
  await page.getByRole('button', {name: '添加已有论文', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: '添加已有论文', exact: true})
  await dialog.getByRole('searchbox', {name: '搜索已有论文'}).fill(paper.title)
  await dialog.getByRole('checkbox', {name: paper.title, exact: true}).check()
  await dialog.getByRole('searchbox', {name: '搜索已有论文'}).fill(other.title)
  await dialog.getByRole('checkbox', {name: other.title, exact: true}).check()
  await dialog.getByRole('searchbox', {name: '搜索已有论文'}).fill('')
  await page.setViewportSize({width: 1080, height: 800})
  await page.screenshot({path: 'test-artifacts/collection-existing-papers.png'})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await dialog.getByRole('button', {name: '确认加入', exact: true}).click()
  await expect(dialog).not.toBeVisible()
  await expect(rowFor(page, paper.title)).toBeVisible()
  await expect(rowFor(page, other.title)).toBeVisible()
  await page.getByRole('button', {name: '添加已有论文', exact: true}).click()
  await dialog.getByRole('searchbox', {name: '搜索已有论文'}).fill(paper.title)
  await expect(dialog.getByRole('checkbox', {name: paper.title, exact: true})).toHaveCount(0)
  await expect(dialog).toContainText('没有可添加的论文')
})

test('save errors keep selection for retry; pending saves cannot be dismissed or repeated', async ({page, request}) => {
  const {paper, collection} = await fixture(request, 'retry')
  await page.goto('/')
  await rowFor(page, paper.title).getByRole('button', {name: `${paper.title} 加入集合`, exact: true}).click()
  const dialog = dialogFor(page)
  await dialog.getByRole('radio', {name: collection.name, exact: true}).check()
  let attempts = 0
  let finish: (() => void) | undefined
  await page.route(`**/api/collections/${collection.id}/papers`, async route => {
    attempts++
    if (attempts === 1) return route.fulfill({status: 503, json: {detail: '保存测试失败，请重试'}})
    await new Promise<void>(resolve => {finish = resolve})
    await route.continue()
  })
  await dialog.getByRole('button', {name: '确认加入', exact: true}).click()
  await expect(dialog.getByRole('alert')).toContainText('保存测试失败')
  expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
  await expect(dialog.getByRole('radio', {name: collection.name, exact: true})).toBeChecked()
  await dialog.getByRole('button', {name: '确认加入', exact: true}).click()
  await expect.poll(() => !!finish).toBe(true)
  await page.keyboard.press('Tab')
  expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', {name: '取消', exact: true})).toBeDisabled()
  finish!()
  await expect(dialog).not.toBeVisible()
  expect(attempts).toBe(2)
})

test('reader offers the same collection action without leaving the PDF', async ({page, request}) => {
  const {collection} = await fixture(request, 'reader')
  const imported = await request.post('/api/papers/import', {multipart: {file: {name: 'collection-reader.pdf', mimeType: 'application/pdf', buffer: Buffer.concat([await readFile(path.resolve('test-artifacts/import-fixture.pdf')), Buffer.from('\n% collection reader\n')])}}})
  expect(imported.status()).toBe(201)
  const paper = await imported.json()
  await page.goto('/')
  await rowFor(page, paper.title).locator('.paper-name > button').click()
  await page.locator('.reader-toolbar').getByRole('button', {name: '加入集合', exact: true}).click()
  const dialog = dialogFor(page)
  await dialog.getByRole('radio', {name: collection.name, exact: true}).check()
  await dialog.getByRole('button', {name: '确认加入', exact: true}).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.locator('.pdfv-page-shell[data-page-number="1"] .pdfv-canvas')).toBeVisible()
  expect((await (await request.get(`/api/papers/${paper.id}`)).json()).collection_ids).toContain(collection.id)
  await page.locator('.reader-toolbar').getByRole('button', {name: '加入集合', exact: true}).click()
  await expect(dialog.getByRole('radio', {name: collection.name, exact: true})).toBeDisabled()
  await expect(dialog).toContainText('已在集合中')
})

test('membership management can remove a topic without removing the paper', async ({page, request}) => {
  const {paper, collection} = await fixture(request, 'remove')
  await request.put(`/api/collections/${collection.id}/papers/${paper.id}`)
  await page.goto('/')
  await rowFor(page, paper.title).locator('.collection-summary').click()
  const dialog = page.getByRole('dialog', {name: '所属集合', exact: true})
  await dialog.getByRole('checkbox', {name: collection.name, exact: true}).uncheck()
  await expect.poll(async () => (await (await request.get(`/api/papers/${paper.id}`)).json()).collection_ids).toEqual([])
  await dialog.getByRole('button', {name: '关闭', exact: true}).click()
  await expect(rowFor(page, paper.title).getByRole('button', {name: `${paper.title} 加入集合`, exact: true})).toBeVisible()
})

test('unfiled papers retain a direct tag editor', async ({page, request}) => {
  const {paper} = await fixture(request, 'tags')
  await page.goto('/')
  await rowFor(page, paper.title).getByRole('button', {name: `${paper.title} 编辑标签`, exact: true}).click()
  const dialog = page.getByRole('dialog', {name: '所属集合', exact: true})
  await dialog.getByRole('textbox', {name: '标签', exact: true}).fill('memory, long-term')
  await dialog.getByRole('button', {name: '保存', exact: true}).click()
  await expect(dialog).not.toBeVisible()
  const stored = await (await request.get(`/api/papers/${paper.id}`)).json()
  expect(stored.tags).toEqual(['memory', 'long-term'])
  expect(stored.collection_ids).toEqual([])
  await page.reload()
  await expect(rowFor(page, paper.title).locator('.paper-tags')).toContainText('long-term')
})

test('empty collection list offers creation and English dark mode remains readable', async ({page, request}) => {
  const {paper} = await fixture(request, 'empty-list')
  await page.addInitScript(() => {localStorage.setItem('riw-language', 'en-US'); localStorage.setItem('riw-theme', 'dark')})
  await page.route('**/api/collections', route => route.fulfill({json: {items: [], total: 0}}))
  await page.goto('/')
  await page.setViewportSize({width: 1080, height: 800})
  await rowFor(page, paper.title).getByRole('button', {name: `${paper.title} Add to collection`, exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'Add to collection', exact: true})
  await expect(dialog).toContainText('Create a collection first')
  await expect(dialog.getByRole('button', {name: 'Confirm addition', exact: true})).toBeDisabled()
  await page.screenshot({path: 'test-artifacts/collection-empty-dark.png'})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await dialog.getByRole('button', {name: 'New collection', exact: true}).click()
  await expect(page.getByRole('dialog', {name: 'New collection', exact: true})).toBeVisible()
})
