import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Bookmark, Check, ChevronRight, Clock3, History, LoaderCircle, RotateCcw, X } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import type { EssaySource, FindingAction, FindingKind, FindingRevision, ReadingOrigin, ResearchFinding, ResearchFindingsState } from '../types'
import { ErrorBanner, Loading } from './Shared'
import { ResearchMarkdown } from './ResearchMarkdown'
import { ResearchAgenda } from './ResearchAgenda'
import './research-findings.css'

const kinds:Record<FindingKind,string>={connection:'论文联系',gap:'知识缺口',review:'复习题',question:'研究问题',reading:'阅读疑问'}
const states:Record<ResearchFinding['status'],string>={unread:'未读',kept:'已保留',dismissed:'已忽略',done:'已完成'}
const active=(status?:string)=>!!status&&['queued','running','paused'].includes(status)
const date=(value:string)=>new Date(value).toLocaleDateString('zh-CN',{month:'long',day:'numeric'})
const due=(item:ResearchFinding)=>item.kind==='review'&&item.status!=='dismissed'&&item.status!=='done'&&!!item.due_at&&new Date(item.due_at).getTime()<=Date.now()

export function ResearchFindings({collectionId,openSource,openOrigin,setup,notify}:{collectionId:string;openSource:(source:EssaySource)=>void;openOrigin?:(origin:ReadingOrigin)=>void;setup:()=>void;notify:(message:string)=>void}) {
  const key=`lira-findings-${collectionId}`
  const initial=useRef<{id?:string;kind?:string;status?:string}>((()=>{try{return JSON.parse(sessionStorage.getItem(key)??'{}')}catch{return {}}})())
  const [data,setData]=useState<ResearchFindingsState|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [kind,setKind]=useState(initial.current.kind??'all')
  const [status,setStatus]=useState(initial.current.status??'active')
  const [selectedId,setSelectedId]=useState(initial.current.id??'')
  const [listOnly,setListOnly]=useState(false)
  const [compact,setCompact]=useState(()=>window.matchMedia('(max-width:1000px)').matches)
  const [answer,setAnswer]=useState(false)
  const [history,setHistory]=useState<FindingRevision[]|null>(null)
  const [historyBusy,setHistoryBusy]=useState(false)
  const historyTicket=useRef(0)
  const selectedRef=useRef('')
  const pane=useRef<HTMLElement>(null)
  const load=async()=>{const next=await api.researchFindings(collectionId);setData(next);setError('')}
  useEffect(()=>{const media=window.matchMedia('(max-width:1000px)');const change=()=>setCompact(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change)},[])
  useEffect(()=>{
    let alive=true
    const refresh=()=>api.researchFindings(collectionId).then(next=>{if(alive){setData(next);setError('')}}).catch(e=>{if(alive)setError(errorMessage(e))})
    void refresh();const timer=setInterval(refresh,10000)
    return()=>{alive=false;clearInterval(timer)}
  },[collectionId])
  const visible=(data?.items??[]).filter(i=>(kind==='all'||i.kind===kind)&&(status==='all'||status==='active'&&!['dismissed','done'].includes(i.status)||status==='due'&&due(i)||i.status===status))
  const selected=visible.find(i=>i.id===selectedId)??visible[0]
  selectedRef.current=selected?.id??''
  useEffect(()=>{sessionStorage.setItem(key,JSON.stringify({id:selected?.id??'',kind,status}))},[key,selected?.id,kind,status])
  useEffect(()=>{
    setAnswer(!!selected&&sessionStorage.getItem(`lira-finding-answer-${selected.id}`)==='true');setHistory(null)
    historyTicket.current++;setHistoryBusy(false)
  },[selected?.id])
  useEffect(()=>{
    if(!selected)return
    const position=`lira-finding-position-${selected.id}`
    const element=compact?pane.current?.closest<HTMLElement>('.page-wrap'):pane.current
    if(!element)return
    const frame=requestAnimationFrame(()=>{element.scrollTop=Number(sessionStorage.getItem(position)??0)})
    const remember=()=>sessionStorage.setItem(position,String(element.scrollTop))
    element.addEventListener('scroll',remember,{passive:true})
    return()=>{cancelAnimationFrame(frame);element.removeEventListener('scroll',remember)}
  },[selected?.id,compact])
  const toggleAnswer=()=>{if(selected){sessionStorage.setItem(`lira-finding-answer-${selected.id}`,String(!answer));setAnswer(!answer)}}
  const perform=async(work:()=>Promise<unknown>)=>{if(busy)return;setBusy(true);setError('');try{await work();await load()}catch(e){setError(errorMessage(e))}finally{setBusy(false)}}
  const act=(action:FindingAction)=>{if(selected)void perform(()=>api.findingAction(selected.id,action))}
  const checkUpdates=()=>{
    if(!data?.scope.enabled||!data.scope.work_types?.some(t=>t!=='essay')){setup();return}
    void perform(async()=>{
      if(data.scope.work_types.some(t=>t!=='essay'&&t!=='reading')){
        const job=await api.updateResearch(collectionId,'findings')
        notify(job.status==='completed'?'材料没有变化，线索已是最新':'已安排发现与复核两步研究')
      }else{
        const scan=await api.followReading(collectionId)
        notify(scan.tasks.some(t=>active(t.status))?'已安排跟进阅读疑问':'已检查，等待新的阅读问题')
      }
    })
  }
  const revisions=async()=>{
    if(history){setHistory(null);return}
    if(!selected||historyBusy)return
    const ticket=++historyTicket.current, id=selected.id
    setHistoryBusy(true)
    try{const next=await api.findingHistory(id);if(ticket===historyTicket.current&&selectedRef.current===id)setHistory(next.revisions)}catch(e){if(ticket===historyTicket.current)setError(errorMessage(e))}finally{if(ticket===historyTicket.current)setHistoryBusy(false)}
  }
  const task=data?.task
  const taskLabel=task?.status==='running'?(task.stage==='discover'?'正在寻找值得留下的问题':'正在核对线索与原文'):task?.status==='failed'?'本轮未完成，已有线索已保留':task?.status==='cancelled'?'本轮任务已取消':active(task?.status)?'已排队，闲时继续':task?.status==='completed'?'这一轮已整理好':data?.scope.enabled?'等待下一轮材料变化':'为这个专题选择研究任务'
  return <section className="research-findings" aria-label="研究线索">
    {error&&<ErrorBanner error={error} retry={()=>void load().catch(e=>setError(errorMessage(e)))}/>}
    {!data&&!error&&<Loading text="打开研究线索…"/>}
    {data&&<>
      <header className="findings-heading"><div><p>读过之后，还有什么值得想？</p><h1>研究线索<span>{data.items.filter(i=>i.status!=='dismissed').length.toString().padStart(2,'0')}</span></h1></div><button className="findings-due" onClick={()=>{setStatus('due');setKind('all');setListOnly(false)}}><Clock3 size={14}/>{data.items.filter(due).length} 题待复习<ChevronRight size={13}/></button></header>
      {data.agenda&&(data.items.length>0||data.agenda.planner||data.agenda.tasks.length>0)&&<ResearchAgenda agenda={data.agenda} busy={busy} canPlan={data.scope.work_types.some(t=>t!=='essay'&&t!=='reading')} openOrigin={openOrigin} start={()=>void perform(()=>api.planResearch(collectionId))} action={(id,action)=>void perform(()=>api.researchTaskAction(id,action))} openResult={id=>{setKind('all');setStatus('all');setSelectedId(id);setListOnly(false);requestAnimationFrame(()=>pane.current?.scrollIntoView({behavior:'smooth',block:'nearest'}))}}/>}
      {data.items.length===0?<div className="findings-empty"><div className="findings-orbit" aria-hidden="true"><span/><span/><span/><i/></div><h2>下一次阅读，从一个好问题开始。</h2><p>让后台回到原文，找出论文间值得比较的机制，留下还没想清的地方，也为以后准备几道复习题。</p><button className="btn primary" onClick={setup}>选择研究任务<ArrowRight size={15}/></button><small>沿用官方额度与阅读优先策略。材料不变时，无需重复生成。</small></div>:<>
        <div className="findings-filter"><label>类型<select aria-label="线索类型" value={kind} onChange={e=>{setKind(e.target.value);setListOnly(false)}}><option value="all">全部线索</option>{Object.entries(kinds).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>状态<select aria-label="线索状态" value={status} onChange={e=>{setStatus(e.target.value);setListOnly(false)}}><option value="active">待探索与已保留</option><option value="unread">未读</option><option value="kept">已保留</option><option value="due">到期复习</option><option value="done">已完成</option><option value="dismissed">已忽略</option><option value="all">所有状态</option></select></label><span>{visible.length} 条</span></div>
        <div className={'findings-workspace '+(listOnly?'is-list-only':'')}>
          <nav className="findings-list" aria-label="研究线索列表">{visible.map((item,index)=><button key={item.id} aria-label={item.title} aria-current={selected?.id===item.id?'true':undefined} className={'finding-row '+(selected?.id===item.id?'is-current':'')} onClick={()=>{setSelectedId(item.id);setListOnly(false)}}><span className="finding-row-index">{String(index+1).padStart(2,'0')}</span><span className="finding-row-copy"><small>{kinds[item.kind]}<span>{due(item)?'待复习':states[item.status]}</span></small><strong>{item.title}</strong><span>{[...new Set(item.sources.map(s=>s.title))].join(' / ')}</span></span><ChevronRight size={14}/></button>)}{!visible.length&&<p className="findings-no-results">这个筛选下暂时没有线索。<button onClick={()=>{setKind('all');setStatus('active')}}>查看待探索的线索</button></p>}</nav>
          {selected?<article className="finding-detail" ref={pane} key={selected.id} aria-label="线索详情">
            <button className="finding-mobile-back" onClick={()=>setListOnly(true)}><ArrowLeft size={14}/>返回线索列表</button>
            <div className="finding-meta"><span>{kinds[selected.kind]}</span><span>{states[selected.status]} · {date(selected.updated_at)}</span></div>
            <h2>{selected.title}</h2>
            <div className="finding-actions">{selected.status==='dismissed'||selected.status==='done'?<button disabled={busy} onClick={()=>act('restore')}><RotateCcw size={14}/>恢复线索</button>:<><button disabled={busy||selected.status==='kept'} onClick={()=>act('keep')}><Bookmark size={14}/>{selected.status==='kept'?'已保留':'保留线索'}</button><button disabled={busy} onClick={()=>act('done')}><Check size={14}/>标为完成</button><button disabled={busy} onClick={()=>act('dismiss')}><X size={14}/>忽略线索</button></>}</div>
            {selected.kind==='review'&&<div className="finding-review"><p>先用自己的话回答，再展开对照。</p><button className="btn secondary" onClick={toggleAnswer}>{answer?'收起参考答案':'展开参考答案'}<ChevronRight className={answer?'is-open':''} size={14}/></button>{selected.review_count>0&&selected.due_at&&<small>已记住 {selected.review_count} 次 · 下次复习 {date(selected.due_at)}</small>}{!selected.review_count&&selected.status==='kept'&&selected.due_at&&<small>下次复习 {new Date(selected.due_at).toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'})}</small>}</div>}
            {(selected.kind!=='review'||answer)&&<div className={selected.kind==='review'?'finding-answer':''}>
              <ResearchMarkdown className="finding-prose" text={selected.body} sourceLabels={Object.fromEntries(selected.sources.map((s,i)=>[s.id,String(i+1)]))} onSource={id=>{const source=selected.sources.find(s=>s.id===id);if(source)openSource(source)}}/>
              <section className="finding-next"><h3>{selected.kind==='review'?'试着这样回忆':'可以从这里继续'}</h3><ResearchMarkdown text={selected.next_step} sourceLabels={Object.fromEntries(selected.sources.map((s,i)=>[s.id,String(i+1)]))} onSource={id=>{const source=selected.sources.find(s=>s.id===id);if(source)openSource(source)}}/></section>
              {selected.kind==='review'&&<div className="finding-grade" aria-label="安排下次复习"><button aria-label="再复习" disabled={busy} onClick={()=>act('again')}><RotateCcw size={14}/>再复习<small>10 分钟后</small></button><button aria-label="记住了" disabled={busy} onClick={()=>act('remembered')}><Check size={14}/>记住了<small>{[1,3,7,14,30,60][Math.min(selected.review_count,5)]} 天后</small></button></div>}
              <details className="finding-sources"><summary>原文依据<span>{new Set(selected.sources.map(s=>s.paper_id)).size} 篇论文 · {selected.sources.length} 处</span></summary>{selected.sources.map((s,i)=><button key={s.id} onClick={()=>openSource(s)}><span>{i+1}</span><span>{s.title}<small>{s.section||'原文'} · 第 {s.page??'—'} 页</small></span><ChevronRight size={13}/></button>)}</details>
            </div>}
            <footer className="finding-footer"><span>后台研读 · {selected.model}</span><button onClick={()=>void revisions()} disabled={historyBusy}>{historyBusy?<LoaderCircle className="spin" size={12}/>:<History size={12}/>}修订记录</button></footer>
            {history&&<div className="finding-history">{history.map((r,i)=><details key={r.id}><summary>{i===0?'当前修订':'之前的修订'} · {date(r.created_at)}<small>{r.model}</small></summary><h3>{r.title}</h3><ResearchMarkdown text={r.body} sourceLabels={Object.fromEntries(r.sources.map((s,i)=>[s.id,String(i+1)]))} onSource={id=>{const s=r.sources.find(s=>s.id===id);if(s)openSource(s)}}/></details>)}{!history.length&&<p>还没有修订记录。</p>}</div>}
          </article>:<div className="finding-detail findings-detail-empty"><span>留一点空间，给下一个好问题。</span></div>}
        </div>
      </>}
      <footer className={'findings-run '+(task?.status==='running'?'is-running':'')}><div><span className="research-status-dot"/>{taskLabel}{active(task?.status)&&<small>{task?.stage==='assess'?'02 / 02 · 核对与编辑':'01 / 02 · 研读原文'}</small>}</div><div>{task?.status==='failed'||task?.status==='cancelled'?<button disabled={busy} onClick={()=>void perform(()=>api.researchTaskAction(task!.id,'retry'))}>重试本轮</button>:active(task?.status)?<button disabled={busy} onClick={()=>void perform(()=>api.researchTaskAction(task!.id,'cancel'))}>取消本轮</button>:<button disabled={busy} onClick={checkUpdates}>{data.scope.work_types?.every(t=>t==='essay'||t==='reading')?'检查阅读问题':'检查更新'}</button>}<button onClick={setup}>研究设置</button></div>{task?.error&&<p>{task.error}</p>}</footer>
    </>}
  </section>
}
