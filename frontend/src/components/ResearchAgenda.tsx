import { ArrowUpRight, Check, Circle, LoaderCircle, RotateCcw, X } from 'lucide-react'
import type { ReadingOrigin, ResearchAgendaState } from '../types'
import './research-agenda.css'

const active=(status:string)=>['queued','running','paused'].includes(status)
const label=(status:string,stage:string)=>status==='running'?(stage==='plan'?'规划问题':stage==='assess'?'核对原文':'正在研读'):({queued:'待研读',paused:'等待继续',completed:'已完成',failed:'待重试',cancelled:'已取消',superseded:'材料已更新'} as Record<string,string>)[status]??status

export function ResearchAgenda({agenda,busy,start,action,openResult,openOrigin,canPlan=true}:{agenda:ResearchAgendaState;busy:boolean;start:()=>void;action:(id:string,action:'retry'|'cancel')=>void;openResult:(id:string)=>void;openOrigin?:(origin:ReadingOrigin)=>void;canPlan?:boolean}) {
  const tasks=agenda.tasks, planner=agenda.planner
  const completed=tasks.filter(t=>t.status==='completed').length
  const working=tasks.some(t=>t.status==='running')||planner?.status==='running'
  return <details className="research-agenda">
    <summary><span className={'agenda-mark '+(working?'is-working':'')}>{working?<LoaderCircle size={14} className="spin"/>:<Circle size={12}/>}</span><strong>继续研究</strong><span>{tasks.length?`${completed} / ${tasks.length} 项完成`:planner?label(planner.status,planner.stage):'把下一步交给后台'}</span></summary>
    <div className="agenda-content">
      <div className="agenda-intro"><p>接着阅读中留下的问题查原文，也沿着专题继续探索。每项先研读、再核对，结果保存在下方。</p>{!planner&&canPlan&&<button disabled={busy} onClick={start}>规划后续问题<ArrowUpRight size={13}/></button>}{planner&&['failed','cancelled'].includes(planner.status)&&<button disabled={busy} onClick={()=>action(planner.id,'retry')}><RotateCcw size={13}/>重试规划</button>}{planner&&active(planner.status)&&<button disabled={busy} onClick={()=>action(planner.id,'cancel')}>取消规划<X size={13}/></button>}</div>
      {planner?.error&&<p className="agenda-error" role="status">{planner.error}</p>}
      {!tasks.length&&planner?.status==='completed'&&<p className="agenda-quiet">本轮没有找到值得继续的问题。加入新论文、笔记或调整方向后，后台会重新规划。</p>}
      <ol className="agenda-tasks">{tasks.map((task,index)=><li key={task.id} className={'agenda-task is-'+task.status}>
        <span className="agenda-index">{task.status==='completed'?<Check size={13}/>:task.status==='running'?<LoaderCircle size={13} className="spin"/>:String(index+1).padStart(2,'0')}</span>
        <div className="agenda-task-copy"><div><strong>{task.title}</strong><small>{label(task.status,task.stage)}</small></div>{task.origin&&<div className="agenda-origin"><span>{task.origin.kind==='note'?'来自问题笔记':'来自未完成的提问'}{task.origin.page?` · 第 ${task.origin.page} 页`:''}</span>{openOrigin&&<button onClick={()=>openOrigin(task.origin!)}>回到阅读位置<ArrowUpRight size={12}/></button>}</div>}<p>{task.rationale}</p><details><summary>研读范围</summary><p>{task.question}</p><span>{task.paper_ids.length} 篇论文{task.section_hints.length?' · '+task.section_hints.join(' / '):''}</span></details>{task.error&&<p className="agenda-error">{task.error}</p>}{task.status==='completed'&&<div className="agenda-outcomes">{task.outcome_ids.map(id=><button disabled={busy} key={id} onClick={()=>openResult(id)}>查看研究结果<ArrowUpRight size={12}/></button>)}{!task.outcome_ids.length&&<span>已查阅，本轮没有新增或修订的结论。</span>}</div>}</div>
        {active(task.status)?<button className="agenda-control" disabled={busy} aria-label={'取消：'+task.title} onClick={()=>action(task.id,'cancel')}><X size={14}/></button>:['failed','cancelled'].includes(task.status)&&<button className="agenda-control" disabled={busy} aria-label={'重试：'+task.title} onClick={()=>action(task.id,'retry')}><RotateCcw size={14}/></button>}
      </li>)}</ol>
    </div>
  </details>
}
