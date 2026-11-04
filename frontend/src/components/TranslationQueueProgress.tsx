import { AlertCircle, CheckCircle2, Clock3, LoaderCircle, Pause, Play, RotateCcw, X } from 'lucide-react'
import { useUi } from '../lib/i18n'
import type { LocaleKey } from '../lib/i18n'
import type { TranslationJob, TranslationJobAction, TranslationQueueItem } from '../types'
import { QuotaPolicyControl } from './QuotaPolicyControl'

export function queueItemLabel(item:(TranslationQueueItem&{job_status?:TranslationJob['status']})|undefined,t:ReturnType<typeof useUi>['t']) {
  if(!item)return ''
  if(item.job_status==='paused'&&(item.status==='queued'||item.status==='running'))return t('queuePaused')
  return t(item.status==='running'?item.phase==='checking'?'queueChecking':'queueTranslating':item.status==='completed'?'queueDone':item.status==='failed'?'batchFailed':item.status==='cancelled'?'queueCancelled':'queueQueued')
}
export function queueJobLabel(job:Pick<TranslationJob,'status'|'failed'|'reason'>,t:ReturnType<typeof useUi>['t']) {
    if(job.status==='paused')return t('queuePaused')
    if(job.status==='cancelled')return t('queueCancelled')
    if(job.status==='completed')return t(job.failed?'batchCompletedWithErrors':'batchCompleted')
    if(job.status==='failed')return t('queueFailed')
    const reasons:Record<string,LocaleKey>={reading:'queueReading',quota_reserve:'queueQuota',long_reserve:'queueQuota',daily_budget:'queueQuotaRecheck',hourly_limit:'queueQuotaRecheck',hourly_budget:'queueQuotaRecheck',disabled:'queueDisabled',profile_required:'queueProfile',profile_changed:'queueProfileChanged',account_unavailable:'queueAccount',quota_unknown:'queueUnknownQuota',quota_stale:'queueUnknownQuota',quota_timeout:'queueQuotaTimeout',quota_unavailable:'queueQuotaUnavailable',foreground:'queueForeground',foreground_queue:'queueForeground',busy:'queueForeground',cooldown:'queueCooldown',idle_wait:'queueIdle'}
    return t(reasons[job.reason??'']??(job.status==='running'?'queueTranslating':'queueQueued'))
}
export function TranslationJobScope({job}:{job:Pick<TranslationJob,'mode'|'scope_total'|'scope_skipped'|'scope_reason'>}) {
  const {t}=useUi()
  if(job.mode!=='full'||!job.scope_total)return null
  if(job.scope_reason!=='appendix_or_references')return <span className="translation-queue-scope">{t('queueScopeUncertain')}</span>
  const skipped=job.scope_skipped??0
  return <span className="translation-queue-scope">{t('queueBodyScope')}{skipped>0&&<> · {t('queueScopeSkipped').replace('{count}',String(skipped))}</>}</span>
}
export function TranslationJobActions({job,busy,action}:{job:Pick<TranslationJob,'id'|'status'|'failed'>;busy:boolean;action:(id:string,action:TranslationJobAction)=>unknown}) {
  const {t}=useUi()
  return <div className="translation-queue-actions">
    {['queued','running'].includes(job.status)&&<button disabled={busy} aria-label={t('queuePause')} onClick={()=>action(job.id,'pause')}><Pause size={13}/><span>{t('queuePause')}</span></button>}
    {job.status==='paused'&&<button disabled={busy} aria-label={t('queueResume')} onClick={()=>action(job.id,'resume')}><Play size={13}/><span>{t('queueResume')}</span></button>}
    {job.failed>0&&<button disabled={busy} aria-label={t('queueRetry')} onClick={()=>action(job.id,'retry')}><RotateCcw size={13}/><span>{t('queueRetry')}</span></button>}
    {['queued','running','paused'].includes(job.status)&&<button disabled={busy} aria-label={t('queueCancel')} title={t('queuePreservesCache')} onClick={()=>action(job.id,'cancel')}><X size={13}/><span>{t('queueCancel')}</span></button>}
  </div>
}
export function TranslationQueueProgress({jobs,busy,error,action}:{jobs:TranslationJob[];busy:boolean;error:string;action:(id:string,action:TranslationJobAction)=>unknown}) {
  const {t}=useUi()
  if(!jobs.length&&!error)return null
  const active=jobs.filter(job=>['queued','running','paused'].includes(job.status))
  const visible=active.length?active:jobs.slice(0,1)
  const statusIcon=(job:TranslationJob)=>job.status==='running'?<LoaderCircle size={13} className="spin"/>:job.status==='completed'?<CheckCircle2 size={13}/>:job.status==='queued'?<Clock3 size={13}/>:job.status==='paused'?<Pause size={13}/>:job.status==='failed'?<AlertCircle size={13}/>:<X size={13}/>
  const renderJob=(job:TranslationJob)=><div className="translation-queue-row" key={job.id}>
      <div className="translation-queue-copy"><span className="translation-queue-heading">{statusIcon(job)}<strong>{t(job.mode==='full'?'queueFull':'batchTranslate')}</strong><span className="translation-queue-count">{job.completed} / {job.total}</span>{job.failed>0&&<span>{job.failed} {t('batchFailed')}</span>}</span><span className="translation-queue-reason" role="status">{queueJobLabel(job,t)}{job.error&&` · ${job.error}`}</span><TranslationJobScope job={job}/></div>
      <TranslationJobActions job={job} busy={busy} action={action}/>
    </div>
  return <section className="translation-queue" aria-label={t('queueTitle')} data-testid="translation-queue-progress">
    {visible.slice(0,2).map(renderJob)}
    {active.some(job=>job.mode==='full')&&<QuotaPolicyControl/>}
    {visible.length>2&&<details className="translation-queue-more"><summary>{t('queueMore')} · {visible.length-2}</summary><div>{visible.slice(2).map(renderJob)}</div></details>}
    {error&&<p className="translation-queue-error" role="alert">{error}</p>}
  </section>
}
