import { LoaderCircle } from 'lucide-react'
import type { Paper } from '../types'
import { useUi } from '../lib/i18n'
import { intelligenceKeys, isActiveTask } from '../lib/intelligence'

export function AnalysisBadge({paper}:{paper:Paper}) {
  const {t}=useUi()
  const status=paper.intelligence_status??'unanalyzed'
  return <span className={'analysis-badge ai-'+status}>
    {isActiveTask(status)&&<LoaderCircle size={11} className="spin"/>}{t(intelligenceKeys[status])}
  </span>
}
