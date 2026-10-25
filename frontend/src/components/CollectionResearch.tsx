import { useEffect, useRef, useState } from 'react'
import { ArrowDownToLine, ArrowLeft, ArrowUpRight, Check, ChevronRight, Circle, Clock3, FileText, History, LoaderCircle, Pause, Play, RefreshCw, Settings2, X } from 'lucide-react'
import type { Collection, CollectionResearchState, EssayRevision, EssaySource, ModelProfile, ResearchSettings, ResearchStatus, ResearchWorkType } from '../types'
import type { PdfLocator } from './PdfViewer'
import { api, errorMessage } from '../lib/api'
import { essayCitations } from '../lib/essayCitations'
import { ErrorBanner, Loading, Modal } from './Shared'
import { ResearchMarkdown } from './ResearchMarkdown'
import { ResearchFindings } from './ResearchFindings'
import './collection-research.css'

const reasons:Record<string,string> = {
  disabled:'后台研究已暂停', profile_required:'选择官方连接后即可开始', reading:'正在让出通道，优先保障阅读',
  foreground_queue:'先完成你安排的论文分析', hourly_budget:'本轮预算已用完，稍后继续', cooldown:'稍后重试，已完成的步骤保留',
  account_unavailable:'等待官方账号恢复连接', quota_unknown:'暂时无法读取额度，后台等待中', quota_stale:'等待刷新官方额度',
  quota_reserve:'为你的阅读保留额度', working:'后台正在研究', up_to_date:'材料没有变化，暂时无需更新',
  maintenance_partial:'维护批次已完成一段，等待下一次空闲额度', maintenance_error:'维护批次暂时失败，已有体检结果已保留',
  task_error:'本次研究需要重试，已有文章仍可阅读', service_error:'后台服务暂时未完成，已有成果已保留', ready:'等待开始研究',
}
const stages = ['synthesis','draft','review']
const stageNames:Record<string,string>={synthesis:'研读与论证',draft:'写成文章',review:'核对与审读',published:'文章已更新'}
const isActive=(s?:string)=>!!s&&['queued','running','paused'].includes(s)
const date=(value:string)=>new Date(value).toLocaleDateString('zh-CN',{month:'long',day:'numeric'})

function Constellation() {
  return <svg className="essay-constellation" viewBox="0 0 360 250" fill="none" aria-hidden="true">
    <path d="M65 174C109 113 128 41 196 62S248 213 295 148M65 174C149 231 200 112 295 148M65 174C138 192 165 79 196 62M196 62C235 95 224 146 295 148"/>
    <circle cx="65" cy="174" r="30"/><circle cx="196" cy="62" r="39"/><circle cx="295" cy="148" r="22"/>
    <circle cx="65" cy="174" r="4"/><circle cx="196" cy="62" r="4"/><circle cx="295" cy="148" r="4"/>
    <path d="M52 174h26M196 49v26M285 148h20"/>
    <text x="34" y="226">EXPERIENCE</text><text x="168" y="16">CONNECTION</text><text x="268" y="194">INSIGHT</text>
  </svg>
}

function useEssayDialog(open:boolean, selector:string, close:()=>void) {
  const closeRef=useRef(close);closeRef.current=close
  useEffect(()=>{
    if(!open)return
    const dialog=document.querySelector<HTMLElement>(selector)
    if(!dialog)return
    const previous=document.activeElement as HTMLElement|null
    const focusable=()=>Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled),textarea,input,select,a[href],summary')).filter(e=>e.offsetParent!==null)
    ;(dialog.querySelector<HTMLElement>('textarea')??focusable()[0])?.focus()
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeRef.current();return}
      if(event.key!=='Tab')return
      const items=focusable();if(!items.length)return
      const current=items.indexOf(document.activeElement as HTMLElement)
      if(event.shiftKey&&current<=0){event.preventDefault();items[items.length-1].focus()}
      else if(!event.shiftKey&&(current===items.length-1||current<0)){event.preventDefault();items[0].focus()}
    }
    window.addEventListener('keydown',key,true)
    return()=>{window.removeEventListener('keydown',key,true);if(previous?.isConnected)previous.focus()}
  },[open,selector])
}

export function ResearchStatusButton({open}:{open:()=>void}) {
  const [status,setStatus]=useState<ResearchStatus|null>(null)
  useEffect(()=>{let active=true;const load=()=>api.researchStatus().then(s=>{if(active)setStatus(s)}).catch(()=>{});void load();const timer=setInterval(load,15000);return()=>{active=false;clearInterval(timer)}},[])
  const working=status?.tasks.some(t=>t.status==='running')
  return <button className="research-sidebar" aria-label="后台研究" onClick={open} title={reasons[status?.reason??'disabled']}><span className={'research-status-dot '+(working?'is-working':'')}/><span>后台研究</span><small>{working?'研读中':status?.settings.enabled?'待命':'暂停'}</small></button>
}

export function CollectionResearch({collection,back,openPaper,openSettings,notify}:{collection:Collection;back:()=>void;openPaper:(id:string,locator?:PdfLocator)=>void;openSettings:()=>void;notify:(message:string)=>void}) {
  const [data,setData]=useState<CollectionResearchState|null>(null)
  const [status,setStatus]=useState<ResearchStatus|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [settingsOpen,setSettingsOpen]=useState(false)
  const [view,setView]=useState<'essay'|'findings'>(()=>sessionStorage.getItem(`lira-research-view-${collection.id}`)==='findings'?'findings':'essay')
  const [versionId,setVersionId]=useState(()=>sessionStorage.getItem(`lira-essay-version-${collection.id}`)??'')
  const [source,setSource]=useState<EssaySource|null>(null)
  const [outlineOpen,setOutlineOpen]=useState(false)
  const articleRef=useRef<HTMLElement>(null)
  const sourceTrigger=useRef('')
  useEffect(()=>{sessionStorage.setItem(`lira-research-view-${collection.id}`,view)},[view,collection.id])
  const load=async()=>{
    const [next,monitor]=await Promise.all([api.collectionResearch(collection.id,versionId||undefined),api.researchStatus()])
    setData(next);setStatus(monitor);setError('')
  }
  useEffect(()=>{let active=true;setData(null);setSource(null);setError('');
    const refresh=()=>Promise.all([api.collectionResearch(collection.id,versionId||undefined),api.researchStatus()]).then(([next,s])=>{if(active){setData(next);setStatus(s);setError('')}}).catch(e=>{if(active)setError(errorMessage(e))})
    void refresh();const timer=setInterval(refresh,10000);return()=>{active=false;clearInterval(timer)}
  },[collection.id,versionId])
  const perform=async(action:()=>Promise<unknown>)=>{if(busy)return;setBusy(true);setError('');try{await action();await load()}catch(e){setError(errorMessage(e))}finally{setBusy(false)}}
  const revision=data?.revision
  useEffect(()=>{sessionStorage.setItem(`lira-essay-version-${collection.id}`,versionId)},[versionId,collection.id])
  useEffect(()=>{
    if(!revision)return
    const scroll=articleRef.current?.closest<HTMLElement>('.page-wrap');if(!scroll)return
    const key=`lira-essay-position-${revision.id}`
    const frame=requestAnimationFrame(()=>{scroll.scrollTop=Number(sessionStorage.getItem(key)??0)})
    const remember=()=>sessionStorage.setItem(key,String(scroll.scrollTop))
    scroll.addEventListener('scroll',remember,{passive:true})
    return()=>{cancelAnimationFrame(frame);scroll.removeEventListener('scroll',remember)}
  },[revision?.id])
  const active=isActive(data?.task?.status)
  const headings=(revision?.markdown??'').split('\n').filter(s=>/^##\s/.test(s)).map(s=>s.replace(/^##\s+/,''))
  const exportArticle=()=>{
    if(!revision)return
    const citations=essayCitations(revision.markdown??'')
    const references=[...citations].map(([id,number])=>({source:revision.sources?.find(s=>s.id===id),number})).filter(item=>item.source)
    const text=`# ${revision.title}\n\n${revision.dek}\n\n${revision.markdown}\n\n---\n\n${references.map(({source:s,number})=>`<a id="source-${s!.id}"></a>\n\n**[${number}] · ${s!.title} · p.${s!.page??'—'}**\n\n> ${s!.quote.replace(/\n/g,'\n> ')}\n`).join('\n')}\n\nLIRA · 第 ${revision.number} 版 · ${revision.created_at}\n`
    const url=URL.createObjectURL(new Blob([text],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=revision.title.replace(/[<>:"/\\|?*]/g,'')+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
  }
  const revealSource=(id:string)=>{
    const found=revision?.sources?.find(s=>s.id===id)
    if(found){sourceTrigger.current=id;setSource(found)}
  }
  const closeSource=()=>{setSource(null);requestAnimationFrame(()=>articleRef.current?.querySelector<HTMLElement>(`[data-source-id="${CSS.escape(sourceTrigger.current)}"]`)?.focus({preventScroll:true}))}
  useEssayDialog(!!source,'.essay-source-dialog',closeSource)
  const jumpHeading=(index:number)=>{articleRef.current?.querySelectorAll('h2')[index]?.scrollIntoView({behavior:'smooth',block:'start'});setOutlineOpen(false)}
  return <div className="collection-research">
    <div className="essay-workspace-nav"><button onClick={back}><ArrowLeft size={15}/><span>{collection.name}</span></button><div className="essay-view-switch" aria-label="专题视图"><button onClick={back}>文献</button><button className={view==='essay'?'is-selected':''} aria-current={view==='essay'?'page':undefined} onClick={()=>setView('essay')}>专题文章</button><button className={view==='findings'?'is-selected':''} aria-current={view==='findings'?'page':undefined} onClick={()=>setView('findings')}>研究线索</button></div><button onClick={()=>setSettingsOpen(true)} aria-label="专题研究设置"><Settings2 size={16}/><span>研究设置</span></button></div>
    {error&&<ErrorBanner error={error} retry={()=>void load().catch(e=>setError(errorMessage(e)))}/>}
    {view==='findings'&&<ResearchFindings collectionId={collection.id} openSource={setSource} setup={()=>setSettingsOpen(true)} notify={notify}/>}
    {view==='essay'&&<>
    {!data&&!error&&<Loading text="打开专题文章…"/>}
    {data&&!revision&&<section className="essay-empty">
      <div className="essay-empty-copy"><div className="essay-kicker">LIRA / FIELDNOTES</div><h1>让读过的论文，<br/>形成自己的认识。</h1><p>从「{collection.name}」出发，把方法之间的联系、分歧与证据边界，写成一篇值得反复阅读的文章。</p>
        {data.scope.focus&&<blockquote>{data.scope.focus}</blockquote>}
        <button className="essay-start" onClick={()=>setSettingsOpen(true)}>安排这个专题<ChevronRight size={17}/></button><small>闲时研读 · 阅读优先 · 每次更新保留旧版</small>
      </div><Constellation/>
      <div className="essay-empty-foot"><span>01 <strong>从原文出发</strong></span><span>02 <strong>沿着问题组织</strong></span><span>03 <strong>让认识持续生长</strong></span></div>
    </section>}
    {data&&revision&&<>
      <div className="essay-tools"><div><FileText size={14}/><span>{collection.name}</span><span className="essay-tool-separator">/</span><span>专题文章</span></div><div><label className="essay-version"><History size={14}/><select aria-label="文章版本" value={versionId||data.revisions[0]?.id||''} onChange={e=>setVersionId(e.target.value===data.revisions[0]?.id?'':e.target.value)}>{data.revisions.map(r=><option key={r.id} value={r.id}>第 {r.number} 版 · {date(r.created_at)}</option>)}</select></label><button aria-label="导出文章" title="导出文章" onClick={exportArticle}><ArrowDownToLine size={16}/><span>导出</span></button></div></div>
      <div className="essay-reading-layout">
        <aside className={'essay-outline '+(outlineOpen?'is-open':'')}><button className="essay-outline-toggle" onClick={()=>setOutlineOpen(!outlineOpen)}>本文脉络<ChevronRight size={13}/></button><nav aria-label="文章目录">{headings.map((h,i)=><button key={i} onClick={()=>jumpHeading(i)}><span>{String(i+1).padStart(2,'0')}</span>{h}</button>)}</nav></aside>
        <article className="essay-paper" ref={articleRef}>
          <header className="essay-title"><div className="essay-kicker">LIRA / FIELDNOTES <span>No. {String(revision.number).padStart(2,'0')}</span></div><h1>{revision.title}</h1><p className="essay-dek">{revision.dek}</p><div className="essay-byline"><span>{date(revision.created_at)} · 第 {revision.number} 版</span><span>{Math.max(1,Math.ceil((revision.markdown?.length??0)/500))} 分钟阅读</span></div></header>
          <ResearchMarkdown className="essay-prose" text={revision.markdown??''} onSource={revealSource}/>
          <footer className="essay-colophon"><div className="essay-colophon-rule"/><p>{revision.changes}</p><details><summary>关于这篇文章与原文覆盖</summary><p>基于专题原文与个人阅读问题，由 {revision.model} 研读、写作与审读。引文已匹配原文；论证仍欢迎你回到论文中检验。</p>{revision.coverage?.map(c=><div key={c.paper_id}><span>{c.title}</span><small>{!c.included_chars?'暂无可读原文':c.included_chars<c.total_chars?`已选读 ${Math.round(c.included_chars/c.total_chars*100)}% 原文`:'原文已纳入研读'}</small></div>)}</details><button onClick={()=>setSettingsOpen(true)}>调整下次研究的方向<ArrowUpRight size={14}/></button></footer>
        </article>
      </div>
    </>}
    {data&&status&&<section className={'essay-progress '+(data.task?.status==='running'?'is-running':'')} aria-label="研究进度">
      <div className="essay-progress-heading"><span className="research-status-dot"/><span>{data.task?.status==='completed'?'文章已就绪':data.task?.status==='failed'?'这次研究未完成':data.task?.status==='cancelled'?'本次任务已取消':!data.scope.enabled?'这个专题尚未开启闲时研究':reasons[status.reason]??'等待研究'}</span><div>{data.task?.status==='failed'||data.task?.status==='cancelled'?<button disabled={busy} onClick={()=>void perform(()=>api.researchTaskAction(data.task!.id,'retry'))}><Play size={13}/>重试</button>:active?<button disabled={busy} onClick={()=>void perform(()=>api.researchTaskAction(data.task!.id,'cancel'))}><X size={13}/>取消本次</button>:data.scope.enabled&&<button disabled={busy} onClick={()=>void perform(async()=>{const next=await api.updateResearch(collection.id);if(next.status==='completed')notify('材料没有变化，现有文章已是最新版');else notify('已加入闲时研究队列')})}><Clock3 size={13}/>检查更新</button>}<button disabled={busy} onClick={()=>setSettingsOpen(true)}><Settings2 size={13}/>设置</button></div></div>
      {active&&<ol className="essay-steps">{stages.map((stage,i)=>{const position=stages.indexOf(data.task!.stage);return <li key={stage} className={i<position?'is-done':i===position?'is-current':''}>{i<position?<Check size={13}/>:i===position&&data.task?.status==='running'?<LoaderCircle size={13} className="spin"/>:<Circle size={12}/>}<span>{stageNames[stage]}</span></li>})}</ol>}
      {data.task?.error&&<p className="essay-task-error">{data.task.error}</p>}
    </section>}
    </>}
    {settingsOpen&&data&&status&&<ResearchSetup collection={collection} data={data} status={status} close={()=>setSettingsOpen(false)} saved={()=>{setSettingsOpen(false);void load().catch(e=>setError(errorMessage(e)))}} openSettings={openSettings}/>}
    {source&&<Modal title="原文出处" className="essay-source-dialog" close={closeSource}><div className="essay-source-meta"><span>{source.section||'原文'}</span><span>第 {source.page??'—'} 页</span></div><h3>{source.title}</h3><blockquote>{source.quote}</blockquote><details><summary>展开附近原文</summary><p>{source.text}</p></details><button className="btn primary" onClick={()=>{const scroll=articleRef.current?.closest<HTMLElement>('.page-wrap');if(scroll&&revision)sessionStorage.setItem(`lira-essay-position-${revision.id}`,String(scroll.scrollTop));closeSource();openPaper(source.paper_id,{page:source.page??1,source_text:source.quote})}}>在论文中查看<ArrowUpRight size={15}/></button></Modal>}
  </div>
}

function ResearchSetup({collection,data,status,close,saved,openSettings}:{collection:Collection;data:CollectionResearchState;status:ResearchStatus;close:()=>void;saved:()=>void;openSettings:()=>void}) {
  const [focus,setFocus]=useState(data.scope.focus)
  const [workTypes,setWorkTypes]=useState<ResearchWorkType[]>(data.scope.work_types??['essay'])
  const [enabled,setEnabled]=useState(data.scope.enabled)
  const [settings,setSettings]=useState<ResearchSettings>({...status.settings})
  const [profiles,setProfiles]=useState<ModelProfile[]>([])
  const [quota,setQuota]=useState(status.quota)
  const [quotaAt,setQuotaAt]=useState(status.quota_checked_at)
  const [quotaBusy,setQuotaBusy]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  useEssayDialog(true,'.essay-setup-dialog',()=>{if(!busy)close()})
  const refreshQuota=async()=>{setQuotaBusy(true);try{const s=await api.researchQuota();setQuota(s.quota);setQuotaAt(s.checked_at)}catch(e){setError(errorMessage(e))}finally{setQuotaBusy(false)}}
  useEffect(()=>{let active=true;void api.modelProfiles().then(s=>{if(!active)return;const official=s.profiles.filter(p=>p.provider_kind==='codex');setProfiles(official);if(!settings.profile_id&&official.length)setSettings(old=>({...old,profile_id:official[0].id}))}).catch(e=>{if(active)setError(errorMessage(e))});return()=>{active=false}},[])
  const save=async(directionOnly=false)=>{
    if(busy)return;setBusy(true);setError('')
    try{
      if(!directionOnly)await api.researchSettings(settings)
      await api.researchScope(collection.id,{enabled:directionOnly?data.scope.enabled:enabled,focus:focus.trim(),work_types:workTypes})
      if(!directionOnly&&enabled){
        if(workTypes.includes('essay'))await api.updateResearch(collection.id)
        if(workTypes.some(t=>t!=='essay'))await api.updateResearch(collection.id,'findings')
      }
      saved()
    }catch(e){setError(errorMessage(e))}finally{setBusy(false)}
  }
  return <Modal title="专题研究设置" className="essay-setup-dialog" close={()=>{if(!busy)close()}}><p className="essay-setup-intro">为「{collection.name}」留一个值得持续思考的问题。</p><label className="essay-field">研究方向<textarea autoFocus aria-label="研究方向" maxLength={3000} value={focus} onChange={e=>setFocus(e.target.value)} placeholder="例如：这些方法分别在什么时刻使用记忆？哪些区别真正影响实验结果？"/></label><label className="essay-toggle"><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/><span>允许这个专题在闲时研究<small>原文、笔记、方向或任务类型变化时才安排新一轮。</small></span></label>
    <fieldset className="research-work-types"><legend>让后台做些什么</legend>{([
      ['essay','整理专题文章','研读 → 写作 → 审读'],['connections','发现论文联系','比较有解释力的机制'],['gaps','检查知识缺口','找到值得补齐的一环'],['review','准备复习题','用回忆恢复理解'],['questions','提出研究问题','留一个能验证的想法'],
    ] as [ResearchWorkType,string,string][]).map(([value,label,hint])=><label key={value}><input type="checkbox" aria-label={label} checked={workTypes.includes(value)} onChange={e=>setWorkTypes(old=>e.target.checked?[...old,value]:old.filter(t=>t!==value))}/><span>{label}</span><small>{hint}</small></label>)}</fieldset>
    <div className="essay-policy"><div className="essay-policy-heading"><span>闲时工作方式 · 全局策略</span><label><input type="checkbox" checked={settings.enabled} onChange={e=>setSettings({...settings,enabled:e.target.checked})}/>后台总开关</label></div><label className="essay-field">使用的官方连接<select aria-label="后台官方连接" value={settings.profile_id??''} onChange={e=>setSettings({...settings,profile_id:e.target.value||null})}><option value="">选择 Codex 订阅连接</option>{profiles.map(p=><option value={p.id} key={p.id}>{p.name} · {p.model}</option>)}</select></label>{!profiles.length&&<p className="essay-profile-hint">还没有官方连接。<button onClick={openSettings}>去设置登录 ChatGPT<ArrowUpRight size={12}/></button></p>}
      <div className="essay-policy-grid"><label>闲置多久开始<select value={settings.idle_seconds} onChange={e=>setSettings({...settings,idle_seconds:Number(e.target.value)})}>{![60,180,300,600].includes(settings.idle_seconds)&&<option value={settings.idle_seconds}>{settings.idle_seconds} 秒</option>}<option value={60}>1 分钟</option><option value={180}>3 分钟</option><option value={300}>5 分钟</option><option value={600}>10 分钟</option></select></label><label>每小时最多调用<input type="number" min={1} max={18} value={settings.calls_per_hour} onChange={e=>setSettings({...settings,calls_per_hour:Number(e.target.value)})}/></label></div>
      <div className="maintenance-policy"><div className="essay-policy-heading"><span>知识网络维护 · 空闲时运行</span><label><input type="checkbox" checked={settings.maintenance_enabled} onChange={e=>setSettings({...settings,maintenance_enabled:e.target.checked})}/>开启维护</label></div><p>程序先检查重复对象、证据定位和悬空关系；模型只审阅可疑邻域。阅读、论文分析、翻译和提问会自动让路。</p><div className="essay-policy-grid"><label>两轮维护间隔<select value={settings.maintenance_interval_minutes} onChange={e=>setSettings({...settings,maintenance_interval_minutes:Number(e.target.value)})}><option value={30}>30 分钟</option><option value={120}>2 小时</option><option value={720}>12 小时</option><option value={1440}>1 天</option></select></label><label>每轮最多模型调用<input type="number" min={1} max={12} value={settings.maintenance_calls_per_run} onChange={e=>setSettings({...settings,maintenance_calls_per_run:Number(e.target.value)})}/></label><label>维护范围<select value={settings.maintenance_scope} onChange={e=>setSettings({...settings,maintenance_scope:e.target.value as ResearchSettings['maintenance_scope']})}><option value="library">整个文献库</option><option value="enabled_collections">已开启专题</option></select></label></div></div>
      <details><summary>额度保留策略</summary><div className="essay-policy-grid"><label>短窗口启动阈值（%）<input type="number" min={10} max={95} value={settings.start_remaining} onChange={e=>setSettings({...settings,start_remaining:Number(e.target.value)})}/></label><label>短窗口停止阈值（%）<input type="number" min={5} max={90} value={settings.stop_remaining} onChange={e=>setSettings({...settings,stop_remaining:Number(e.target.value)})}/></label><label>长窗口至少保留（%）<input type="number" min={10} max={90} value={settings.long_reserve} onChange={e=>setSettings({...settings,long_reserve:Number(e.target.value)})}/></label></div><p>窗口以官方返回为准。无法读取额度时等待；仅使用选中的官方连接。</p></details>
      <div className="essay-quota-heading"><span>{quotaAt?`额度读取于 ${new Date(quotaAt*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}`:'尚未读取额度'}</span><button type="button" disabled={quotaBusy} onClick={()=>void refreshQuota()}><RefreshCw size={12} className={quotaBusy?'spin':''}/>刷新额度</button></div>{quota.length>0&&<div className="essay-quota" aria-label="官方剩余额度">{quota.map((w,i)=><div key={i}><span>{w.window_minutes? w.window_minutes>=1440?`${Math.round(w.window_minutes/1440)} 天窗口`:`${Math.round(w.window_minutes/60*10)/10} 小时窗口`:'额度窗口'}{w.limit_id&&w.limit_id!=='codex'?` · ${w.limit_id}`:''}</span><strong>{w.used_percent===null?'暂未读取':`剩余 ${Math.round(100-w.used_percent)}%`}</strong><meter min="0" max="100" value={w.used_percent===null?0:100-w.used_percent}/></div>)}</div>}
    </div><p className="essay-setup-footnote"><Pause size={13}/>阅读、翻译或提问时自动让出通道。已完成步骤保留，被中断的一步可能需要重做。</p>{error&&<ErrorBanner error={error}/>}<div className="modal-actions"><button className="btn secondary" disabled={busy} onClick={()=>void save(true)}>保存研究方向</button><button className="btn primary" disabled={busy||!settings.profile_id} onClick={()=>void save()}>{busy?<LoaderCircle className="spin" size={14}/>:<Check size={14}/>}保存设置</button></div></Modal>
}
