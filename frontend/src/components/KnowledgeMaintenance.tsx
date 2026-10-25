import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowUpRight, Check, ChevronRight, CircleDashed, Clock3, LoaderCircle, Pause, Play, RotateCcw, ShieldCheck, Undo2, X } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import type { MaintenanceIssue, MaintenanceRunDetail } from '../types'
import type { PdfLocator } from './PdfViewer'
import './knowledge-maintenance.css'

type ScopeType = 'library' | 'collection' | 'papers'
type Filter = 'all' | 'safe' | 'review' | 'critical'

const statusKeys: Record<MaintenanceRunDetail['status'], 'maintenanceQueued'|'maintenanceRunning'|'maintenancePartial'|'maintenanceComplete'|'maintenanceCancelled'|'maintenanceFailed'> = {
  queued: 'maintenanceQueued', running: 'maintenanceRunning', partial: 'maintenancePartial', complete: 'maintenanceComplete', cancelled: 'maintenanceCancelled', failed: 'maintenanceFailed',
}

export function KnowledgeMaintenance({ scopeType, scopeId, paperIds, openPaper }: {
  scopeType: ScopeType
  scopeId?: string
  paperIds?: string[]
  openPaper: (id: string, locator?: PdfLocator) => void
}) {
  const { t } = useUi()
  const [run, setRun] = useState<MaintenanceRunDetail | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [busy, setBusy] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const list = await api.maintenanceRuns(20, {type: scopeType, id: scopeId})
      const latest = list.items[0]
      const detail = latest ? await api.maintenanceRun(latest.id) : null
      setRun(detail)
      setSelectedId(current => detail?.issues.some(issue => issue.id === current) ? current : detail?.issues[0]?.id ?? '')
      setError('')
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [scopeType, scopeId, paperIds?.join(',')])

  const issues = useMemo(() => {
    const all = run?.issues ?? []
    return all.filter(issue => filter === 'all' || filter === 'safe' && issue.auto_eligible && issue.status === 'proposed' || filter === 'review' && !issue.auto_eligible && ['proposed', 'needs_review'].includes(issue.status) || filter === 'critical' && issue.severity === 'critical')
      .sort((a, b) => Number(b.severity === 'critical') - Number(a.severity === 'critical') || Number(b.auto_eligible) - Number(a.auto_eligible) || b.confidence - a.confidence)
  }, [run, filter])
  const selected = issues.find(issue => issue.id === selectedId) ?? issues[0] ?? null
  const pendingSafe = run?.issues.filter(issue => issue.auto_eligible && issue.status === 'proposed').length ?? 0
  const pendingReview = run?.issues.filter(issue => !issue.auto_eligible && ['proposed', 'needs_review'].includes(issue.status)).length ?? 0
  const critical = run?.issues.filter(issue => issue.severity === 'critical' && !['rejected', 'undone'].includes(issue.status)).length ?? 0

  const refresh = async () => { await load() }
  const start = async () => {
    setBusy('start'); setError('')
    try {
      const detail = await api.createMaintenanceRun({scope_type: scopeType, ...(scopeId ? {scope_id: scopeId} : {}), ...(paperIds?.length ? {paper_ids: paperIds} : {}), allow_external: false})
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
    {run && <>
      <div className="maintenance-status-strip">
        <span className={`maintenance-status-dot status-${run.status}`} />
        <strong>{t(statusKeys[run.status])}</strong>
        <span className="maintenance-status-copy">{run.error_message && run.status === 'partial' ? t('maintenancePartialHint') : t('maintenanceModelHint')}</span>
        <time>{run.finished_at ? new Date(run.finished_at).toLocaleString() : t('maintenanceRunning')}</time>
      </div>
      <div className="maintenance-metrics">
        <button className={filter === 'safe' ? 'active' : ''} onClick={() => setFilter(filter === 'safe' ? 'all' : 'safe')}><ShieldCheck size={15}/><span><strong>{pendingSafe}</strong>{t('maintenanceSafe')}</span></button>
        <button className={filter === 'review' ? 'active' : ''} onClick={() => setFilter(filter === 'review' ? 'all' : 'review')}><CircleDashed size={15}/><span><strong>{pendingReview}</strong>{t('maintenanceReview')}</span></button>
        <button className={filter === 'critical' ? 'active' : ''} onClick={() => setFilter(filter === 'critical' ? 'all' : 'critical')}><AlertTriangle size={15}/><span><strong>{critical}</strong>{t('maintenanceConflicts')}</span></button>
        <div className="maintenance-metric-last"><Check size={15}/><span><strong>{run.applied_count}</strong>{t('maintenanceApplied')}</span></div>
      </div>
      <div className="maintenance-workbench">
        <aside className="maintenance-queue"><div className="maintenance-queue-head"><h3>{t('maintenanceIssues')}</h3><span>{issues.length}</span></div>{issues.length === 0 ? <p className="maintenance-empty-line">{t('maintenanceNoRunHint')}</p> : issues.map(issue => <button key={issue.id} className={`maintenance-issue-row ${selected?.id === issue.id ? 'selected' : ''}`} onClick={() => setSelectedId(issue.id)}><span className={`issue-severity severity-${issue.severity}`}/><span className="issue-row-copy"><strong>{issue.summary}</strong><small>{issue.auto_eligible ? t('maintenanceSafe') : t('maintenanceReview')} · {Math.round(issue.confidence * 100)}%</small></span><ChevronRight size={15}/></button>)}</aside>
        <MaintenanceDetail issue={selected} busy={busy} onEvidence={openEvidence} onApply={issue => void issueAction(issue, 'apply')} onReject={issue => void issueAction(issue, 'reject')} onUndo={issue => void issueAction(issue, 'undo')} />
      </div>
    </>}
    {!run && !loading && <div className="maintenance-empty"><ShieldCheck size={30}/><h3>{t('maintenanceNoRun')}</h3><p>{t('maintenanceNoRunHint')}</p><button className="btn primary" disabled={!!busy} onClick={() => void start()}><Play size={14}/>{t('maintenanceStart')}</button></div>}
    {loading && <div className="maintenance-loading"><LoaderCircle className="spin" size={17}/>{t('chatLoading')}</div>}
  </section>
}

function MaintenanceDetail({issue, busy, onEvidence, onApply, onReject, onUndo}: {issue:MaintenanceIssue|null; busy:string; onEvidence:(e:MaintenanceIssue['evidence'][number])=>void; onApply:(issue:MaintenanceIssue)=>void; onReject:(issue:MaintenanceIssue)=>void; onUndo:(issue:MaintenanceIssue)=>void}) {
  const {t} = useUi()
  if (!issue) return <main className="maintenance-detail maintenance-detail-empty"><ShieldCheck size={23}/><p>{t('maintenanceNoEvidence')}</p></main>
  const done = ['auto_applied', 'accepted', 'rejected', 'stale', 'undone'].includes(issue.status)
  return <main className="maintenance-detail"><header className="maintenance-detail-head"><div><span className={`issue-pill ${issue.auto_eligible ? 'safe' : 'review'}`}>{issue.auto_eligible ? t('maintenanceSafe') : t('maintenanceReview')}</span><h3>{issue.summary}</h3></div><span className={`detail-severity severity-${issue.severity}`}>{issue.severity}</span></header><section className="maintenance-explanation"><h4>{t('maintenanceReason')}</h4><p>{issue.reasoning}</p></section><section className="maintenance-explanation"><h4>{t('maintenanceAction')}</h4><code>{String(issue.proposed_action.type ?? 'review_structure').replace(/_/g, ' ')}</code></section><section className="maintenance-evidence"><div className="maintenance-section-title"><h4>{t('maintenanceEvidence')}</h4><span>{issue.evidence.length}</span></div>{issue.evidence.length ? issue.evidence.map((e, index) => <button className="maintenance-evidence-row" key={`${e.chunk_id}-${index}`} onClick={() => onEvidence(e)}><blockquote>{e.quote}</blockquote><span><small>{e.paper_title ?? e.paper_id} · {t('page')} {e.page ?? '—'}</small><ArrowUpRight size={13}/></span></button>) : <p className="maintenance-no-evidence">{t('maintenanceNoEvidence')}</p>}</section><footer className="maintenance-detail-actions">{issue.status === 'undone' && <span className="maintenance-done-label"><Undo2 size={14}/>{t('maintenanceUndo')}</span>}{!done && <>{issue.auto_eligible && <button className="btn primary" disabled={!!busy} onClick={() => onApply(issue)}>{busy === `apply-${issue.id}` ? <LoaderCircle className="spin" size={13}/> : <ShieldCheck size={13}/>} {t('maintenanceApply')}</button>}<button className="btn secondary" disabled={!!busy} onClick={() => onReject(issue)}>{t('maintenanceReject')}</button></>}{['auto_applied', 'accepted'].includes(issue.status) && <button className="btn secondary" disabled={!!busy} onClick={() => onUndo(issue)}><Undo2 size={13}/>{t('maintenanceUndo')}</button>}</footer></main>
}
