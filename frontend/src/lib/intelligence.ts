import { useState } from 'react'
import type { AnalysisTaskSummary, IntelligenceStatus, ModelSettings, Paper } from '../types'

export const isActiveTask = (status?:string) => status==='queued'||status==='running'
export function analysisPhaseKey(task:{status:string;phase:string}) {
  const phase=task.phase
  if(phase==='prepare_reading')return 'analysisPhasePrepare' as const
  if(phase==='awaiting_translation')return 'analysisPhaseTranslation' as const
  if(phase==='awaiting_connection')return 'analysisPhaseConnection' as const
  if(phase==='awaiting_quota')return 'analysisPhaseQuota' as const
  if(task.status==='queued')return 'analysisPhaseQueued' as const
  if(phase==='structure')return 'analysisPhaseStructure' as const
  if(phase==='knowledge_intake')return 'analysisPhaseKnowledge' as const
  if(/science|review/.test(phase))return 'analysisPhaseReview' as const
  if(/extract|window/.test(phase))return 'analysisPhaseExtract' as const
  if(/synth|reduce/.test(phase))return 'analysisPhaseSynthesize' as const
  if(/sav|persist|complete/.test(phase))return 'analysisPhaseFinish' as const
  return 'analysisPhaseUnknown' as const
}
// Older running services lack the summary field. Reuse the library's existing
// task polling so a UI upgrade never requires interrupting an active analysis.
export function analysisTasksFromPapers(papers:Paper[]):AnalysisTaskSummary[] {
  const tasks=papers.flatMap(p=>{
    const task=p.intelligence_task
    if(!task)return []
    const {id,paper_id,status,phase,completed_steps,total_steps,error,created_at,updated_at}=task
    return [{id,paper_id,paper_title:p.title,status,phase,completed_steps,total_steps,error,created_at,updated_at}]
  })
  const active=tasks.filter(task=>isActiveTask(task.status)).sort((a,b)=>Number(b.status==='running')-Number(a.status==='running'))
  const recent=tasks.filter(task=>!isActiveTask(task.status)).sort((a,b)=>(b.updated_at??'').localeCompare(a.updated_at??'')).slice(0,10)
  return [...active,...recent]
}
export const remoteAvailable = (settings:ModelSettings|null) => !!settings?.configured && settings.mode!=='extractive' && settings.intelligence_available!==false
export const intelligenceKeys = {
  unanalyzed:'aiUnanalyzed',queued:'aiQueued',running:'aiRunning',completed:'aiCompleted',partial:'aiPartial',failed:'aiFailed',cancelled:'aiCancelled',
} as const satisfies Record<IntelligenceStatus,string>
export function useAnalysisPreference() {
  const [analyze,setValue]=useState(()=>localStorage.getItem('riw-analyze-import')==='true')
  return [analyze,(next:boolean)=>{setValue(next);localStorage.setItem('riw-analyze-import',String(next))}] as const
}
