import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, CheckCircle2, Clock3, FileText, Languages, LoaderCircle, RefreshCw, RotateCcw, Sparkles, X } from 'lucide-react'
import type { AnalysisTaskSummary, Collection, MaintenanceTaskSummary, ResearchStatus, TranslationJobAction } from '../types'
import { api, errorMessage } from '../lib/api'
import { analysisPhaseKey, intelligenceKeys, isActiveTask } from '../lib/intelligence'
import { useUi } from '../lib/i18n'
import { ErrorBanner, Loading } from '../components/Shared'
import { queueJobLabel, TranslationJobScope, TranslationJobActions } from '../components/TranslationQueueProgress'
import { QuotaPolicyControl } from '../components/QuotaPolicyControl'
import './background-tasks.css'
import {activeMaintenance,maintenanceStatus} from '../lib/maintenanceStatus'

export function BackgroundTasksPage({status,error,refresh,openPaper,openResearch,openKnowledge,collections,cancelAnalysis,queueAnalysis,reloadWorkspace}:{status:ResearchStatus|null;error:string;refresh:()=>Promise<void>;openPaper:(id:string)=>void;openResearch:(id:string)=>void;openKnowledge:(task:MaintenanceTaskSummary)=>void;collections:Collection[];cancelAnalysis:(id:string)=>Promise<void>;queueAnalysis:(ids:string[],force?:boolean)=>Promise<void>;reloadWorkspace:()=>Promise<void>}) {
  const {t}=useUi()
  const [busy,setBusy]=useState(''),[actionError,setActionError]=useState('')
  const [quotaBusy,setQuotaBusy]=useState(false)
  const lock=useRef(false)
  const jobs=status?.translation_jobs??[]
  const active=jobs.filter(job=>['queued','running','paused'].includes(job.status))
  const recent=jobs.filter(job=>!['queued','running','paused'].includes(job.status))
  const analyses=status?.analysis_tasks??[]
  const activeAnalyses=analyses.filter(task=>isActiveTask(task.status))
  const recentAnalyses=analyses.filter(task=>!isActiveTask(task.status))
  const maintenance=status?.maintenance_tasks??[]
  const activeCuration=maintenance.filter(activeMaintenance)
  const recentCuration=maintenance.filter(task=>!activeMaintenance(task))
  const activeCount=active.length+activeAnalyses.length+activeCuration.length
  useEffect(()=>{void refresh()},[refresh])
  const retryQuota=async()=>{
    if(quotaBusy)return
    setQuotaBusy(true);setActionError('')
    try{await api.researchQuota();await refresh()}
    catch(e){setActionError(errorMessage(e))}
    finally{setQuotaBusy(false)}
  }
  const perform=async(id:string,action:TranslationJobAction)=>{
    if(lock.current)return
    lock.current=true;setBusy(id);setActionError('')
    try{await api.translationJobAction(id,action);await refresh()}
    catch(e){setActionError(errorMessage(e))}
    finally{lock.current=false;setBusy('')}
  }
  const performAnalysis=async(task:AnalysisTaskSummary,action:'cancel'|'retry')=>{
    if(lock.current)return
    lock.current=true;setBusy(task.id);setActionError('')
    try{
      if(action==='cancel')await cancelAnalysis(task.id);else await queueAnalysis([task.paper_id],true)
      // The monitor may have discovered a newer attempt than the library snapshot.
      await Promise.all([reloadWorkspace(),refresh()])
    }
    catch(e){setActionError(errorMessage(e))}
    finally{lock.current=false;setBusy('')}
  }
  const performMaintenance=async(task:MaintenanceTaskSummary,action:'cancel'|'retry')=>{
    if(lock.current)return
    lock.current=true;setBusy(task.id);setActionError('')
    try{await api.maintenanceAction(task.id,action);await refresh()}
    catch(e){setActionError(errorMessage(e))}
    finally{lock.current=false;setBusy('')}
  }
  const renderMaintenance=(task:MaintenanceTaskSummary)=>{
    const title=task.scope_title??t(task.scope_type==='library'?'allPapers':'curationSelectedPapers')
    return <article className={'background-job '+(task.status==='running'?'is-running':'')} key={task.id} data-task-id={task.id} aria-label={title}>
      <div className="background-job-main">
        <div className="background-job-kind"><Sparkles size={14}/><span>{t('maintenance')}</span>{task.model_name&&<span className="background-job-model">{task.model_name}</span>}</div>
        <h3>{title}</h3>
        <p className="background-job-reason" role="status">{maintenanceStatus(task,t)}</p>
        {(task.active_papers?.length??0)>1&&<ul className="background-curation-papers" aria-label={t('curationActivePapers')}>{task.active_papers!.map(paper=><li key={paper.id}><button onClick={()=>openPaper(paper.id)}>{paper.title??paper.id}<ArrowUpRight size={12}/></button></li>)}</ul>}
        <p className="background-job-scope">{t('curationScope')} {task.paper_count} {t('paperCount')}{task.failed>0&&` · ${task.failed} ${t('curationNeedsRetry')}`}</p>
        {task.error&&<p className="background-job-error">{task.error}</p>}
        <progress aria-label={`${title} ${t('backgroundProgress')}`} max={Math.max(1,task.total)} value={task.completed}/>
      </div>
      <div className="background-job-controls"><span className="background-job-count">{task.completed} / {task.total}<small>{t('curationPaperUnit')}</small></span><div className="translation-queue-actions">{activeMaintenance(task)?<button disabled={!!busy} onClick={()=>void performMaintenance(task,'cancel')}><X size={12}/>{t('cancelTask')}</button>:['failed','partial','cancelled'].includes(task.status)&&<button disabled={!!busy} onClick={()=>void performMaintenance(task,'retry')}><RotateCcw size={12}/>{t('maintenanceRetry')}</button>}</div><button className="background-open-paper" onClick={()=>openKnowledge(task)}>{t('curationOpen')}<ArrowUpRight size={14}/></button></div>
    </article>
  }
  const renderAnalysis=(task:AnalysisTaskSummary)=>{
    const active=isActiveTask(task.status)
    const phase=analysisPhaseKey(task)
    return <article className={'background-job '+(task.status==='running'?'is-running':'')} key={task.id} aria-label={task.paper_title}>
      <div className="background-job-main"><div className="background-job-kind">{task.status==='running'?<LoaderCircle size={14} className="spin"/>:task.status==='completed'?<CheckCircle2 size={14}/>:<FileText size={14}/>}<span>{t('backgroundAnalysis')}</span></div><h3>{task.paper_title}</h3><p className="background-job-reason" role="status">{t(intelligenceKeys[task.status])}{active&&` · ${t(phase)}`}</p>{task.error&&<p className="background-job-error">{task.error}</p>}{task.total_steps>0&&<progress aria-label={`${task.paper_title} ${t('backgroundProgress')}`} max={task.total_steps} value={task.completed_steps}/>}</div>
      <div className="background-job-controls">{task.total_steps>0&&<span className="background-job-count">{task.completed_steps} / {task.total_steps}<small>{t('backgroundStepUnit')}</small></span>}<div className="translation-queue-actions">{active?<button disabled={!!busy} onClick={()=>void performAnalysis(task,'cancel')}><X size={12}/>{t('cancelTask')}</button>:task.status!=='completed'&&<button disabled={!!busy} onClick={()=>void performAnalysis(task,'retry')}><RotateCcw size={12}/>{t('analysisRetry')}</button>}</div><button className="background-open-paper" aria-label={t('backgroundOpenPaper')} onClick={()=>openPaper(task.paper_id)}>{t('backgroundOpenPaper')}<ArrowUpRight size={14}/></button></div>
    </article>
  }
  const renderJob=(job:typeof jobs[number])=><article className={'background-job '+(job.status==='running'?'is-running':'')} key={job.id} aria-label={job.paper_title}>
    <div className="background-job-main"><div className="background-job-kind">{job.status==='running'?<LoaderCircle size={14} className="spin"/>:job.status==='completed'?<CheckCircle2 size={14}/>:<Languages size={14}/>}<span>{t(job.mode==='full'?'queueFull':'batchTranslate')}</span><span className="background-job-model">{job.model_name}</span></div><h3>{job.paper_title}</h3><p className="background-job-reason" role="status">{queueJobLabel(job,t)}{job.failed>0&&` · ${job.failed} ${t('batchFailed')}`}</p><TranslationJobScope job={job}/>{job.error&&<p className="background-job-error">{job.error}</p>}<progress aria-label={`${job.paper_title} ${t('backgroundProgress')}`} max={Math.max(1,job.total)} value={job.completed}/></div>
    <div className="background-job-controls"><span className="background-job-count">{job.completed} / {job.total}<small>{t('batchParagraphUnit')}</small></span><TranslationJobActions job={job} busy={!!busy} action={(id,action)=>void perform(id,action)}/><button className="background-open-paper" aria-label={t('backgroundOpenPaper')} onClick={()=>openPaper(job.paper_id)}>{t('backgroundOpenPaper')}<ArrowUpRight size={14}/></button></div>
  </article>
  return <section className="background-tasks" aria-label={t('background')}>
    <header className="background-heading"><div><span className="background-kicker">LIRA / BACKGROUND</span><h1>{t('background')}</h1><p>{t('backgroundHint')}</p></div><button className="btn secondary" onClick={()=>void refresh()}><RefreshCw size={14}/>{t('backgroundRefresh')}</button></header>
    {(error||actionError)&&<ErrorBanner error={actionError||error} retry={()=>void refresh()}/>}
    {!status&&!error&&<Loading text={t('loading')}/>}
    {status&&<>
      <div className="background-quota" aria-label={t('backgroundQuota')}><Clock3 size={15}/><span>{t('backgroundQuota')}</span>{status.quota.filter(q=>q.used_percent!==null).map((q,i)=><span key={q.name+i}><strong>{Math.max(0,Math.round(100-q.used_percent!))}%</strong> {t(q.window_minutes&&q.window_minutes<=1440?'backgroundShort':'backgroundLong')}</span>)}{!status.quota.some(q=>q.used_percent!==null)&&<span>{t(status.quota_error_code==='transport_timeout'?'quotaQueryTimeout':status.quota_error_code?'quotaQueryFailed':'queueUnknownQuota')}</span>}<small>{status.quota_checked_at?`${t('backgroundChecked')} ${new Date(status.quota_checked_at*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}`:t('backgroundAutoRefresh')}</small></div>
      {status.quota_error_code&&<div className="background-quota-notice" role="status"><p>{t(status.quota_using_recent?'quotaRecentHint':'quotaQueryHint')}</p><button disabled={quotaBusy} onClick={()=>void retryQuota()}><RefreshCw size={13} className={quotaBusy?'spin':''}/>{t('quotaQueryRetry')}</button></div>}
      {status.scheduler&&<div className="background-scheduler" aria-label={t('schedulerConcurrency')}><span>{t('schedulerConcurrency')} <strong>{status.scheduler.official.active} / {status.scheduler.official.effective}</strong></span><span>{status.scheduler.waiting} {t('schedulerWaiting')}</span>{status.scheduler.official.effective<status.scheduler.official.configured&&<span role="status">{t('schedulerReduced')} · {status.scheduler.official.configured}</span>}</div>}
      {status.scheduler&&<p className="background-scheduler-hint">{t('schedulerReadingHint')}</p>}
      <QuotaPolicyControl status={status} onSaved={refresh}/>
      <div className="background-section-heading"><h2>{t('backgroundActive')}</h2><span>{activeCount} {t('backgroundTaskUnit')}</span></div>
      {activeCount?<div className="background-job-list">{activeAnalyses.map(renderAnalysis)}{active.map(renderJob)}{activeCuration.map(renderMaintenance)}</div>:<div className="background-empty"><CheckCircle2 size={18}/><div><strong>{t('backgroundNoActive')}</strong><p>{t('backgroundNoActiveHint')}</p></div></div>}
      {recent.length+recentAnalyses.length+recentCuration.length>0&&<><div className="background-section-heading"><h2>{t('backgroundRecent')}</h2><span>{t('backgroundSaved')}</span></div><div className="background-job-list background-job-history">{recentAnalyses.map(renderAnalysis)}{recent.map(renderJob)}{recentCuration.map(renderMaintenance)}</div></>}
      {collections.length>0&&<div className="background-research-links"><div><h2>{t('research')}</h2><p>{t('backgroundResearchHint')}</p></div><div>{collections.filter(c=>status.scope_ids.includes(c.id)||status.tasks.some(task=>task.collection_id===c.id)).map(c=><button key={c.id} onClick={()=>openResearch(c.id)}>{c.name}<ArrowUpRight size={14}/></button>)}</div></div>}
      <p className="background-footnote">{t('backgroundServiceHint')}</p>
    </>}
  </section>
}
