import { BookOpen, LoaderCircle, RotateCcw, Square } from 'lucide-react'
import { useState } from 'react'
import type { Paper, ModelSettings } from '../types'
import { useUi } from '../lib/i18n'
import { isActiveTask, remoteAvailable } from '../lib/intelligence'
import { errorMessage } from '../lib/api'
import { AnalysisBadge } from './AnalysisBadge'
import { CoverageSummary } from './IntelligenceAnswer'
import { ErrorBanner } from './Shared'

export function AnalysisControl({paper,settings,queue,cancel}:{paper:Paper;settings:ModelSettings|null;queue:(force?:boolean)=>Promise<void>;cancel:(id:string)=>Promise<void>}) {
  const {t}=useUi();const [busy,setBusy]=useState(false);const [error,setError]=useState('')
  const status=paper.intelligence_status??'unanalyzed',task=paper.intelligence_task
  const retained=!!task?.report.retained_previous_card
  const hasAttemptReport=!!task&&(['failed','cancelled'].includes(status)||retained)&&Object.keys(task.report??{}).length>0
  const active=isActiveTask(status),enabled=remoteAvailable(settings)&&paper.pdf_available
  const phase=task?.phase??''
  const phaseKey=phase.includes('extract')||phase.includes('window')?'analysisPhaseExtract':phase.includes('synth')||phase.includes('reduce')?'analysisPhaseSynthesize':phase.includes('sav')||phase.includes('persist')?'analysisPhaseFinish':status==='queued'?'analysisPhaseQueued':'analysisPhaseUnknown'
  const action=async(callback:()=>Promise<void>)=>{setBusy(true);setError('');try{await callback()}catch(e){setError(errorMessage(e))}finally{setBusy(false)}}
  return <section className="analysis-control" aria-label={t('analysisControl')}><header><strong>{t('analysisControl')}</strong><AnalysisBadge paper={paper}/></header>
    {error&&<ErrorBanner error={error}/>} {task?.error&&<ErrorBanner error={task.error}/>}
    {active&&task&&<div className="analysis-progress"><div><span>{t(phaseKey)}</span><span>{task.completed_steps} / {task.total_steps}</span></div><progress max={Math.max(1,task.total_steps)} value={task.completed_steps}/></div>}
    <p>{t(active?'analysisReadingHint':enabled?'aiLocalHint':'analysisUnavailable')}</p>
    {retained&&<p className="capability-notice">{t('analysisRetainedCard')}</p>}
    <div className="analysis-control-actions">{active?<button className="btn secondary" disabled={busy||!task} onClick={()=>task&&void action(()=>cancel(task.id))}><Square size={12}/>{t('cancelTask')}</button>:<button className="btn secondary" disabled={busy||!enabled} onClick={()=>void action(()=>queue(false))}>{busy?<LoaderCircle className="spin" size={13}/>:<BookOpen size={13}/>} {t(['failed','cancelled','partial'].includes(status)?'analysisRetry':'analysisStart')}</button>}
      {!active&&['completed','partial'].includes(status)&&<button className="text-btn" disabled={busy||!enabled} onClick={()=>void action(()=>queue(true))}><RotateCcw size={12}/>{t('analysisForce')}</button>}</div>
    {paper.intelligence_report&&<details className="analysis-report analysis-published-report"><summary>{t(retained?'analysisPublishedReport':'analysisReport')}</summary><CoverageSummary report={paper.intelligence_report}/><p className="source-check-note">{t('semanticReview')}</p></details>}
    {hasAttemptReport&&<details className="analysis-report analysis-attempt-report"><summary>{t('analysisAttemptReport')}</summary><CoverageSummary report={task?.report}/></details>}
  </section>
}
