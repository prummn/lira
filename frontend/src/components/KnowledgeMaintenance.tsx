import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ArrowUpRight, Check, ChevronRight, CircleDashed, LoaderCircle, Pause, Play, RotateCcw, Sparkles, Undo2, X } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import type { MaintenanceBacklog, MaintenanceIssue, MaintenanceRunDetail, MaintenanceScope, MaintenanceTaskSummary } from '../types'
import {maintenanceStatus} from '../lib/maintenanceStatus'
import type { PdfLocator } from './PdfViewer'
import './knowledge-maintenance.css'

type ScopeType = 'library' | 'collection' | 'papers'
type Filter = 'all' | 'safe' | 'review' | 'critical' | 'applied'
const completed = (issue:MaintenanceIssue) => ['auto_applied','accepted','rejected','stale','undone'].includes(issue.status)
const queuedPaper = (issue:MaintenanceIssue) => issue.proposed_action.type==='curate_paper'&&issue.status==='proposed'
type PaperAudit = {paper_id:string;title:string;source_chars:number;source_chunks:number;coverage:string;objects_added:number;objects_confirmed:number;objects_contextualized:number;relations_added:number;relations_confirmed:number;aliases_linked:number;summary:string}
const number = (value:unknown) => typeof value==='number'&&Number.isFinite(value)?value:0
function paperAudits(run:MaintenanceRunDetail|null):PaperAudit[] {
  if (!Array.isArray(run?.usage.paper_audits)) return []
  return run.usage.paper_audits.filter((item):item is Record<string,unknown> => !!item&&typeof item==='object'&&typeof item.paper_id==='string').map(item=>({paper_id:String(item.paper_id),title:String(item.title??item.paper_id),source_chars:number(item.source_chars),source_chunks:number(item.source_chunks),coverage:String(item.coverage??'bounded'),objects_added:number(item.objects_added),objects_confirmed:number(item.objects_confirmed),objects_contextualized:number(item.objects_contextualized),relations_added:number(item.relations_added),relations_confirmed:number(item.relations_confirmed),aliases_linked:number(item.aliases_linked),summary:typeof item.summary==='string'?item.summary:''}))
}

const statusKeys: Record<MaintenanceRunDetail['status'], 'maintenanceQueued'|'maintenanceRunning'|'maintenancePartial'|'maintenanceComplete'|'maintenanceCancelled'|'maintenanceFailed'> = {
  queued: 'maintenanceQueued', running: 'maintenanceRunning', partial: 'maintenancePartial', complete: 'maintenanceComplete', cancelled: 'maintenanceCancelled', failed: 'maintenanceFailed',
}

export function KnowledgeMaintenance({ scopeType, scopeId, paperIds, openPaper, initialRunId, tasks }: {
  scopeType: ScopeType
  scopeId?: string
  paperIds?: string[]
  initialRunId?: string
  tasks?: MaintenanceTaskSummary[]
  openPaper: (id: string, locator?: PdfLocator) => void
}) {
  const { t } = useUi()
  const [run, setRun] = useState<MaintenanceRunDetail | null>(null)
  const [backlog, setBacklog] = useState<MaintenanceBacklog | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [busy, setBusy] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const generation=useRef(0)
  const chosenRun=useRef(initialRunId)

  const load = async () => {
    const current=++generation.current
    setLoading(true)
    try {
      const id=chosenRun.current??(await api.maintenanceRuns(1, {type: scopeType, id: scopeId})).items[0]?.id
      const detail = id ? await api.maintenanceRun(id) : null
      if(current!==generation.current)return
      setRun(detail)
      setSelectedId(current => detail?.issues.some(issue => issue.id === current) ? current : detail?.issues[0]?.id ?? '')
      setError('')
    } catch (cause) {
      if(current===generation.current)setError(errorMessage(cause))
    } finally {
      if(current===generation.current)setLoading(false)
    }
  }

  useEffect(() => { setBacklog(null); void load();return()=>{generation.current++} }, [scopeType, scopeId, paperIds?.join(',')])
  useEffect(()=>{
    let active=true
    let timer:ReturnType<typeof setTimeout>
    const refresh=async()=>{
      try {
        const current=await api.maintenanceBacklog({type:scopeType,id:scopeId,paperIds})
        if(active)setBacklog(current)
      } catch { /* Retain last known counts through a transient failure. */ }
      if(active)timer=setTimeout(()=>void refresh(),5000)
    }
    void refresh()
    return()=>{active=false;clearTimeout(timer)}
  },[scopeType,scopeId,paperIds?.join(',')])
  useEffect(() => {
    if (!run || !['queued','running','partial'].includes(run.status)) return
    let active=true
    let timer:ReturnType<typeof setTimeout>
    const refreshActive=async()=>{
      try {
        const detail=await api.maintenanceRun(run.id)
        if (!active) return
        setRun(detail)
        if (['queued','running','partial'].includes(detail.status)) timer=setTimeout(()=>void refreshActive(),2000)
      } catch { if(active) timer=setTimeout(()=>void refreshActive(),5000) }
    }
    timer=setTimeout(()=>void refreshActive(),2000)
    return()=>{active=false;clearTimeout(timer)}
  },[run?.id,run?.status,scopeType,scopeId,paperIds?.join(',')])

  const issues = useMemo(() => {
    const all = (run?.issues ?? []).filter(issue=>issue.status==='needs_review')
    return all.filter(issue => filter === 'all' || filter === 'applied' || filter === 'safe' && issue.auto_eligible && issue.status === 'proposed' || filter === 'review' && !issue.auto_eligible && ['proposed', 'needs_review'].includes(issue.status) || filter === 'critical' && issue.severity === 'critical')
      .sort((a, b) => Number(b.severity === 'critical') - Number(a.severity === 'critical') || Number(b.auto_eligible) - Number(a.auto_eligible) || b.confidence - a.confidence)
  }, [run, filter])
  const audits=paperAudits(run)
  const history=run?.issues.filter(completed)??[]
  const safeSuggestions=run?.issues.filter(issue=>issue.status==='proposed'&&issue.auto_eligible&&!queuedPaper(issue))??[]
  const pendingReview = run?.issues.filter(issue => issue.status==='needs_review').length ?? 0
  const critical = run?.issues.filter(issue => issue.severity === 'critical' && issue.status==='needs_review').length ?? 0
  const applied=run?(typeof run.usage.auto_actions==='number'?number(run.usage.auto_actions):run.applied_count):0

  const task=tasks?.find(item=>item.id===run?.id)
  const refresh = async () => { await load() }
  const start = async () => {
    setBusy('start'); setError('')
    try {
      const scope: MaintenanceScope = scopeType === 'collection'
        ? {scope_type: 'collection', scope_id: scopeId ?? ''}
        : scopeType === 'papers'
          ? {scope_type: 'papers', paper_ids: paperIds ?? []}
          : {scope_type: 'library'}
      const detail = await api.createMaintenanceRun({...scope, allow_external: true})
      chosenRun.current=detail.id
      setRun(detail); setSelectedId(detail.issues[0]?.id ?? '')
    } catch (cause) { setError(errorMessage(cause)) } finally { setBusy('') }
  }
  const action = async (key: string, task: () => Promise<unknown>) => {
    setBusy(key); setError('')
    try { await task(); await refresh() } catch (cause) { setError(errorMessage(cause)) } finally { setBusy('') }
  }
  const runAction = (next: 'cancel'|'retry') => action(next, () => api.maintenanceAction(run!.id, next))
  const issueAction = (issue: MaintenanceIssue, next: 'apply'|'reject'|'undo') => action(`${next}-${issue.id}`, () => next === 'apply' ? api.applyMaintenanceIssue(issue.id) : next === 'reject' ? api.rejectMaintenanceIssue(issue.id) : api.undoMaintenanceIssue(issue.id))
  const openEvidence = (e: MaintenanceIssue['evidence'][number]) => {
    if (!e.paper_id) return
    const locator: PdfLocator = {page: e.page ?? 1, bbox: e.bbox ?? undefined, page_width: e.page_width ?? undefined, page_height: e.page_height ?? undefined, source_text: e.quote}
    openPaper(e.paper_id, locator)
  }
  const workbench=(items:MaintenanceIssue[])=>{
    const selected=items.find(issue=>issue.id===selectedId)??items[0]??null
    return <div className="maintenance-workbench"><aside className="maintenance-queue"><div className="maintenance-queue-head"><h3>{t('maintenanceIssues')}</h3><span>{items.length}</span></div>{items.map(issue=><button key={issue.id} className={`maintenance-issue-row ${selected?.id===issue.id?'selected':''}`} onClick={()=>setSelectedId(issue.id)}><CircleDashed size={14}/><span className="issue-row-copy"><strong>{issue.summary}</strong><small>{completed(issue)?t('maintenanceApplied'):issue.auto_eligible?t('maintenanceSafe'):t('maintenanceReview')}</small></span><ChevronRight size={15}/></button>)}</aside><MaintenanceDetail issue={selected} busy={busy} onEvidence={openEvidence} onApply={issue=>void issueAction(issue,'apply')} onReject={issue=>void issueAction(issue,'reject')} onUndo={issue=>void issueAction(issue,'undo')}/></div>
  }

  return <section className="knowledge-maintenance" aria-label={t('maintenance')} data-testid="knowledge-maintenance">
    <header className="maintenance-hero">
      <div><span className="eyebrow">{t('maintenanceEyebrow')}</span><h2>{t('maintenance')}</h2><p>{t('maintenanceIntro')}</p></div>
      <div className="maintenance-hero-actions">
        {run?.status === 'partial' && <button className="btn secondary" disabled={!!busy} onClick={() => runAction('retry')}><RotateCcw size={14}/>{t('maintenanceRetry')}</button>}
        {run && ['queued', 'running', 'partial'].includes(run.status) && <button className="icon-btn" aria-label={t('maintenanceCancel')} disabled={!!busy} onClick={() => runAction('cancel')}><Pause size={16}/></button>}
        <button className="btn primary" disabled={!!busy || loading} onClick={() => void start()}>{busy === 'start' ? <LoaderCircle className="spin" size={14}/> : <Play size={14}/>} {busy === 'start' ? t('maintenanceStarting') : t('maintenanceStart')}</button>
      </div>
    </header>

    {error && <div className="maintenance-error" role="alert"><AlertTriangle size={15}/><span>{error}</span><button className="icon-btn" aria-label={t('close')} onClick={() => setError('')}><X size={14}/></button></div>}
    <div className="maintenance-scope-summary" aria-live="polite">
      <span><strong>{backlog?.pending_papers??'—'}</strong>{t('maintenanceQueuedPapers')}</span>
      <span>{t('maintenanceBacklogObjects')} <strong>{backlog?.pending_objects??'—'}</strong></span>
      <span>{t('maintenanceBacklogRelations')} <strong>{backlog?.pending_relations??'—'}</strong></span>
      <p>{t('maintenanceBacklogHint')}</p>
    </div>
    {!!backlog?.items.length&&<section className="maintenance-auto-queue">
      <header><h3>{t('maintenanceScopeQueue')}</h3><p>{t('maintenanceAutoQueueHint')}</p></header>
      {backlog.items.map(item=><article key={item.paper_id}>
        <div className="maintenance-paper-work"><button className="text-btn" onClick={()=>openPaper(item.paper_id)}>{item.title}<ArrowUpRight size={13}/></button>
          <small>{t('maintenanceBacklogObjects')} {item.pending_objects} · {t('maintenanceBacklogRelations')} {item.pending_relations}</small>
          {item.error&&<small className="maintenance-paper-error">{item.error}</small>}
        </div>
        <span>{t(`maintenancePaper_${item.status}`)}</span>
      </article>)}
    </section>}
    {run && <>
      <div className="maintenance-status-strip">
        <span className={`maintenance-status-dot status-${run.status}`} />
        <strong>{task?maintenanceStatus(task,t):t(statusKeys[run.status])}</strong>{task&&<span>{task.completed} / {task.total} {t('curationPaperUnit')}</span>}
        <span className="maintenance-status-copy">{run.error_message&&['failed','partial'].includes(run.status)?run.error_message:t('maintenanceModelHint')}</span>
        {run.finished_at&&['complete','failed','cancelled'].includes(run.status)&&<time>{new Date(run.finished_at).toLocaleString()}</time>}
      </div>
      <div className="maintenance-metrics">
        <button className={filter === 'applied' ? 'active' : ''} onClick={() => setFilter(filter === 'applied' ? 'all' : 'applied')}><Check size={15}/><span><strong>{applied}</strong>{t('maintenanceApplied')}</span></button>
        <div className="maintenance-metric-last"><Sparkles size={15}/><span><strong>{backlog?.checked_papers??'—'}</strong>{t('maintenanceCheckedPapers')}</span></div>
        <button className={filter === 'review' ? 'active' : ''} onClick={() => setFilter(filter === 'review' ? 'all' : 'review')}><CircleDashed size={15}/><span><strong>{pendingReview}</strong>{t('maintenanceReview')}</span></button>
        <button className={filter === 'critical' ? 'active' : ''} onClick={() => setFilter(filter === 'critical' ? 'all' : 'critical')}><CircleDashed size={15}/><span><strong>{critical}</strong>{t('maintenanceConflicts')}</span></button>
      </div>
      {audits.length>0&&<section className="maintenance-completed"><header><h3>{t('maintenanceCompletedPapers')} <span>{audits.length}</span></h3><p>{t('maintenanceCompletedIntro')}</p></header>{audits.map(audit=><article key={audit.paper_id}><div className="maintenance-audit-heading"><strong>{audit.title}</strong><button className="text-btn" onClick={()=>openPaper(audit.paper_id)}>{t('knowledgeOpenPaper')}<ArrowUpRight size={13}/></button></div>{audit.summary&&<p>{audit.summary}</p>}<dl><div><dt>{t('maintenanceObjects')}</dt><dd>{audit.objects_confirmed}</dd></div><div><dt>{t('maintenanceRelations')}</dt><dd>{audit.relations_confirmed}</dd></div><div><dt>{t('maintenanceAliases')}</dt><dd>{audit.aliases_linked}</dd></div>{audit.objects_contextualized>0&&<div><dt>{t('maintenanceContextualized')}</dt><dd>{audit.objects_contextualized}</dd></div>}<div><dt>{t('maintenanceSourceCoverage')}</dt><dd>{t(audit.coverage==='main_text'?'maintenanceMainText':'maintenanceBounded')} · {audit.source_chunks}</dd></div></dl></article>)}</section>}
      {safeSuggestions.length>0&&<details className="maintenance-suggestions" open={!audits.length}><summary>{t('maintenanceSafe')}<span>{safeSuggestions.length}</span></summary>{workbench(safeSuggestions)}</details>}
      {issues.length>0?<details className="maintenance-pending" open={!audits.length||['safe','review','critical'].includes(filter)}><summary>{t('maintenancePendingDetails')}<span>{issues.length}</span></summary>{workbench(issues)}</details>:<p className="maintenance-clear"><Check size={15}/>{t('maintenanceNoReview')}</p>}
      {history.length>0&&<details className="maintenance-history" open={filter==='applied'}><summary>{t('maintenanceHistory')}<span>{history.length}</span></summary>{workbench(history)}</details>}
    </>}
    {!run && !loading && <div className="maintenance-empty"><Sparkles size={30}/><h3>{t('maintenanceNoRun')}</h3><p>{t('maintenanceNoRunHint')}</p><button className="btn primary" disabled={!!busy} onClick={() => void start()}><Play size={14}/>{t('maintenanceStart')}</button></div>}
    {loading && <div className="maintenance-loading"><LoaderCircle className="spin" size={17}/>{t('chatLoading')}</div>}
  </section>
}

function MaintenanceDetail({issue, busy, onEvidence, onApply, onReject, onUndo}: {issue:MaintenanceIssue|null; busy:string; onEvidence:(e:MaintenanceIssue['evidence'][number])=>void; onApply:(issue:MaintenanceIssue)=>void; onReject:(issue:MaintenanceIssue)=>void; onUndo:(issue:MaintenanceIssue)=>void}) {
  const {t} = useUi()
  if (!issue) return <main className="maintenance-detail maintenance-detail-empty"><Sparkles size={23}/><p>{t('maintenanceNoEvidence')}</p></main>
  const done = ['auto_applied', 'accepted', 'rejected', 'stale', 'undone'].includes(issue.status)
  return <main className="maintenance-detail"><header className="maintenance-detail-head"><div><span className={`issue-pill ${issue.auto_eligible ? 'safe' : 'review'}`}>{issue.auto_eligible ? t('maintenanceSafe') : t('maintenanceReview')}</span><h3>{issue.summary}</h3></div></header><section className="maintenance-explanation"><h4>{t('maintenanceReason')}</h4><p>{issue.reasoning}</p></section><section className="maintenance-explanation"><h4>{t('maintenanceAction')}</h4><p>{t('maintenanceActionHint')}</p></section><section className="maintenance-evidence"><div className="maintenance-section-title"><h4>{t('maintenanceEvidence')}</h4><span>{issue.evidence.length}</span></div>{issue.evidence.length ? issue.evidence.map((e, index) => <button className="maintenance-evidence-row" key={`${e.chunk_id}-${index}`} onClick={() => onEvidence(e)}><blockquote>{e.quote}</blockquote><span><small>{e.paper_title ?? e.paper_id} · {t('page')} {e.page ?? '—'}</small><ArrowUpRight size={13}/></span></button>) : <p className="maintenance-no-evidence">{t('maintenanceNoEvidence')}</p>}</section><footer className="maintenance-detail-actions">{issue.status === 'undone' && <span className="maintenance-done-label"><Undo2 size={14}/>{t('maintenanceUndo')}</span>}{!done && <>{issue.auto_eligible && <button className="btn primary" disabled={!!busy} onClick={() => onApply(issue)}>{busy === `apply-${issue.id}` ? <LoaderCircle className="spin" size={13}/> : <Sparkles size={13}/>} {t('maintenanceApply')}</button>}<button className="btn secondary" disabled={!!busy} onClick={() => onReject(issue)}>{t('maintenanceReject')}</button></>}{['auto_applied', 'accepted'].includes(issue.status)&&issue.applied_change_ids.length>0 && <button className="btn secondary" disabled={!!busy} onClick={() => onUndo(issue)}><Undo2 size={13}/>{t('maintenanceUndo')}</button>}</footer></main>
}
