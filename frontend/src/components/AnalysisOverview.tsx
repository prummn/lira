import { BookOpen } from 'lucide-react'
import type { Evidence, Paper, PaperDetail } from '../types'
import { useUi } from '../lib/i18n'
import { isActiveTask } from '../lib/intelligence'
import { PaperCard } from './PaperCard'

export function AnalysisOverview({paper,taskPaper,configured,locate,sourceTarget}:{paper:PaperDetail;taskPaper:Paper;configured:boolean;locate:(evidence:Evidence)=>void;sourceTarget:string|null}) {
  const {t}=useUi()
  const analysis=paper.analysis
  if(!analysis)return null
  const card=<><PaperCard paper={paper} locate={locate} sourceTarget={sourceTarget}/><div className="concept-tags">{analysis.concepts.map(c=><span key={c}>{c}</span>)}</div></>
  if(analysis.mode==='extractive') {
    const active=isActiveTask(taskPaper.intelligence_status)
    const preparing=['prepare_reading','awaiting_translation'].includes(taskPaper.intelligence_task?.phase??'')
    return <section className="analysis-source-state" aria-label={t('extractive')}>
      <h3><BookOpen size={15}/>{t(preparing?'analysisReadingPrepared':active?'analysisSourcePending':'extractive')}</h3>
      <p>{t(preparing?'analysisPreparingHint':active?'analysisSourcePendingHint':configured?'analysisSourceReadyHint':'analysisSourceConfigureHint')}</p>
      <details className="analysis-source-preview" open={!active||!!sourceTarget}>
        <summary>{t('analysisSourcePreview')}</summary>
        {card}
      </details>
    </section>
  }
  return <><div className="provider-line"><BookOpen size={13}/>{analysis.provider??t('analysisGenerated')}</div><p className="capability-notice">{t('remoteNotice')}</p>{card}</>
}
