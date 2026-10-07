import { useState } from 'react'
import type { IntelligenceStatus, ModelSettings } from '../types'

export const isActiveTask = (status?:string) => status==='queued'||status==='running'
export const remoteAvailable = (settings:ModelSettings|null) => !!settings?.configured && settings.mode!=='extractive' && settings.intelligence_available!==false
export const intelligenceKeys = {
  unanalyzed:'aiUnanalyzed',queued:'aiQueued',running:'aiRunning',completed:'aiCompleted',partial:'aiPartial',failed:'aiFailed',cancelled:'aiCancelled',
} as const satisfies Record<IntelligenceStatus,string>
export function useAnalysisPreference() {
  const [analyze,setValue]=useState(()=>localStorage.getItem('riw-analyze-import')==='true')
  return [analyze,(next:boolean)=>{setValue(next);localStorage.setItem('riw-analyze-import',String(next))}] as const
}
