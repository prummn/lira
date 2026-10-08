import { LoaderCircle } from 'lucide-react'
import type { Paper } from '../types'
import { useUi } from '../lib/i18n'
import { intelligenceKeys, isActiveTask } from '../lib/intelligence'

export function AnalysisBadge({paper}:{paper:Paper}) {
  const {t}=useUi()
  const status=paper.intelligence_status??'unanalyzed'
  return <span className={'analysis-badge ai-'+status} role="status">
    <span className="analysis-dot" aria-hidden="true">{isActiveTask(status)&&<LoaderCircle size={11} className="spin"/>}</span>{t(intelligenceKeys[status])}
  </span>
}
