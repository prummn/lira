import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import type { TranslationJob, TranslationJobAction, TranslationQueueEntry } from '../types'

export function isActiveTranslationQueueItem(item:TranslationQueueEntry|undefined) {
  return !!item&&['queued','running'].includes(item.job_status)&&['queued','running'].includes(item.status)
}

// Jobs live on the server. Leaving a reader stops observation, never its work.
export function useTranslationQueue(paperId:string) {
  const [jobs,setJobs]=useState<TranslationJob[]>([])
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const generation=useRef(0)
  const revision=useRef(0)
  const jobsRef=useRef<TranslationJob[]>([])
  const publish=useCallback((next:TranslationJob[])=>{
    if(JSON.stringify(next)===JSON.stringify(jobsRef.current))return
    jobsRef.current=next;setJobs(next)
  },[])
  useEffect(()=>{
    const token=++generation.current
    jobsRef.current=[];setJobs([]);setError('');setBusy(false)
    let stopped=false,timer:ReturnType<typeof setTimeout>
    const poll=async()=>{
      const version=revision.current
      try {
        const next=await api.translationJobs(paperId)
        if(stopped||generation.current!==token)return
        if(revision.current===version){publish(next.jobs);setError('')}
      } catch(e){if(!stopped&&generation.current===token)setError(errorMessage(e))}
      if(!stopped)timer=setTimeout(poll,jobsRef.current.some(job=>job.status==='queued'||job.status==='running')?1200:5000)
    }
    void poll()
    return()=>{stopped=true;generation.current++;clearTimeout(timer)}
  },[paperId,publish])
  const mutate=useCallback(async(request:()=>Promise<TranslationJob>)=>{
    const token=generation.current
    revision.current++;setBusy(true);setError('')
    try {
      const next=await request()
      if(generation.current!==token)return null
      revision.current++
      publish([next,...jobsRef.current.filter(job=>job.id!==next.id)])
      return next
    } catch(e){if(generation.current===token)setError(errorMessage(e));return null}
    finally{if(generation.current===token)setBusy(false)}
  },[publish])
  const items=useMemo(()=>{
    const byId:Record<string,TranslationQueueEntry>={}
    const priority=(entry:TranslationQueueEntry)=>{
      if(entry.status==='running'||entry.status==='queued'){
        if(entry.job_status==='running'||entry.job_status==='queued')return entry.status==='running'?60:50
        if(entry.job_status==='paused')return 40
      }
      return entry.status==='completed'?30:entry.status==='failed'?20:10
    }
    for(const job of [...jobs].reverse())for(const item of job.items){
      const entry:TranslationQueueEntry={...item,job_id:job.id,job_status:job.status,
        status:job.status==='cancelled'&&item.status!=='completed'?'cancelled':item.status}
      for(const id of new Set([item.paragraph_id,item.original_paragraph_id,...item.aliases])){
        if(!byId[id]||priority(entry)>=priority(byId[id]))byId[id]=entry
      }
    }
    return byId
  },[jobs])
  return {jobs,items,error,busy,
    start:(mode:'selected'|'full',paragraphIds?:string[])=>mutate(()=>api.queueTranslations(paperId,mode,paragraphIds)),
    action:(id:string,action:TranslationJobAction)=>mutate(()=>api.translationJobAction(id,action)),
    prioritize:(id:string)=>mutate(()=>api.prioritizeTranslation(paperId,id)),
  }
}
