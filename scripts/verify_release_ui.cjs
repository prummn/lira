// Exercise the compiled frontend served by the final extracted portable package.
const {chromium,expect}=require('../frontend/node_modules/@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const input=process.argv[2];
if(!input)throw new Error('Provide the isolated verifier state file');
const state=JSON.parse(fs.readFileSync(input,'utf8'));
const work=path.dirname(input);
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(state.url))throw new Error('Verification must use loopback');
(async()=>{
 const browser=await chromium.launch();
 const result={errors:[],failed:[],modelPosts:[],viewports:[]};
 let page;
 try{
  page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>result.errors.push(e.message));
  page.on('requestfailed',r=>{if(!r.failure()?.errorText.includes('ERR_ABORTED'))result.failed.push(r.url())});
  page.on('request',r=>{if(r.method()==='POST'&&/\/(ask|explain|translate|analyze|intelligence\/tasks)(?:[/?]|$)/.test(r.url()))result.modelPosts.push(r.url())});
  const identity=await (await page.request.get(`${state.url}/__lira/instance`)).json();
  expect(identity.instance).toBeTruthy();
  // Validate the freshly generated isolated fixture before opening the UI.
  const papers=await (await page.request.get(`${state.url}/api/papers`)).json();
  expect(papers.total).toBe(1);
  const paper=await (await page.request.get(`${state.url}/api/papers/${state.paper_id}`)).json();
  expect(paper.title).toBe('LIRA portable verification');
  await page.goto(state.url);
  await expect(page.getByRole('button',{name:paper.title,exact:true})).toBeVisible({timeout:30000});
  await page.screenshot({path:path.join(work,'library.png'),fullPage:true});
  const open=async()=>{
   await page.getByRole('button',{name:paper.title,exact:true}).click();
   await expect(page.locator('.reader-page')).toBeVisible();
   await expect(page.locator('.pdfv-canvas').first()).toBeVisible({timeout:30000});
   await expect.poll(()=>page.locator('.pdfv-canvas').first().evaluate(c=>c.width*c.height)).toBeGreaterThan(0);
   await page.getByRole('button',{name:'我的笔记',exact:true}).click();
   await expect(page.getByText('发布验收：独立测试笔记。',{exact:true})).toBeVisible();
  };
  await open();
  for(const width of [1440,1080]){
   await page.setViewportSize({width,height:1000});
   await expect(page.locator('.pdfv-page-placeholder[role="status"]')).toHaveCount(0,{timeout:30000});
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
   expect(overflow).toBe(false);result.viewports.push({width,overflow});
   await page.screenshot({path:path.join(work,`reader-${width}.png`),fullPage:true});
  }
  await page.reload();
  await expect(page.getByRole('button',{name:paper.title,exact:true})).toBeVisible({timeout:30000});
  await open();
  await page.getByRole('button',{name:'设置',exact:true}).click();
  await expect(page.getByRole('heading',{name:'设置',exact:true})).toBeVisible();
  await page.getByRole('combobox',{name:'连接方式',exact:true}).selectOption('codex');
  await expect(page.getByRole('combobox',{name:'官方账号并发',exact:true})).toHaveValue('2');
  await expect(page.getByRole('button',{name:'登录 ChatGPT',exact:true})).toBeEnabled();
  await page.screenshot({path:path.join(work,'settings.png'),fullPage:true});
  expect(result.errors).toEqual([]);expect(result.failed).toEqual([]);expect(result.modelPosts).toEqual([]);
  result.reload=true;
  fs.writeFileSync(path.join(work,'ui-result.json'),JSON.stringify(result,null,2));
 }catch(error){
  if(page)await page.screenshot({path:path.join(work,'failure.png'),fullPage:true}).catch(()=>{});
  fs.writeFileSync(path.join(work,'ui-failure.json'),JSON.stringify({...result,error:error.message},null,2));
  throw error;
 }finally{await browser.close()}
})().catch(e=>{console.error(e.stack);process.exitCode=1});
