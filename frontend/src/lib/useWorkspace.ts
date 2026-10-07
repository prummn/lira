import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import type { Collection, IntelligenceTask, ModelSettings, Paper } from '../types'
import { isActiveTask } from './intelligence'
const keepsPublishedReport=(task:IntelligenceTask) => isActiveTask(task.status) || task.status==='failed' || task.status==='cancelled' || !!task.report.retained_previous_card
export function useWorkspace() {
  const [papers, setPapers] = useState<Paper[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [settings,setSettings]=useState<ModelSettings|null>(null)
  const [taskError,setTaskError]=useState('')
  const alive=useRef(true)
  useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[])
  const reload = useCallback(async () => {
    setError('')
    try { const [p, c,s] = await Promise.all([api.papers(), api.collections(),api.settings()]); if(alive.current){setPapers(p.items);setCollections(c.items);setSettings(s)} }
    catch (e) { setError(errorMessage(e)) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void reload() }, [reload])
  const mergeTasks=useCallback((tasks:IntelligenceTask[],expected?:ReadonlyMap<string,string|null>)=>{
    const latest=new Map<string,IntelligenceTask>()
    for(const task of tasks) if(!latest.has(task.paper_id))latest.set(task.paper_id,task)
    setPapers(current=>current.map(p=>{
      const task=latest.get(p.id)
      if(!task||(expected&&(!expected.has(p.id)||(p.intelligence_task?.id??null)!==expected.get(p.id))))return p
      return {...p,intelligence_status:task.status,intelligence_task:task,intelligence_report:keepsPublishedReport(task)?p.intelligence_report:task.report}
    }))
  },[])
  const queueAnalysis=useCallback(async(ids:string[],force=false,onSubmitted?:(ids:string[])=>void)=>{
    const unique=[...new Set(ids)]
    // Match IntelligenceTaskCreate's 200-paper request limit without parallel queues.
    for(let offset=0;offset<unique.length;offset+=200){
      const batch=unique.slice(offset,offset+200)
      const result=await api.queueAnalysis(batch,force)
      if(alive.current){mergeTasks(result.tasks);setTaskError('');onSubmitted?.(batch)}
    }
  },[mergeTasks])
  const cancelAnalysis=useCallback(async(id:string)=>{const task=await api.cancelAnalysis(id);if(alive.current)mergeTasks([task],new Map([[task.paper_id,id]]))},[mergeTasks])
  const activeTasks=papers.filter(p=>isActiveTask(p.intelligence_status)).map(p=>[p.id,p.intelligence_task?.id??null] as const).sort(([left],[right])=>left.localeCompare(right))
  const activeSignature=activeTasks.length?JSON.stringify(activeTasks):''
  useEffect(()=>{
    if(!activeSignature)return
    let active=true,timer:ReturnType<typeof setTimeout>
    const tracked=JSON.parse(activeSignature) as [string,string|null][]
    const expected=new Map(tracked)
    const poll=async()=>{
      try{
        const pending=tracked.map(([id])=>id),latest:IntelligenceTask[]=[]
        await Promise.all(Array.from({length:Math.min(6,pending.length)},async()=>{
          while(active&&pending.length){const id=pending.shift()!;const response=await api.intelligenceTasks(id);if(response.tasks[0])latest.push(response.tasks[0])}
        }))
        if(!active)return
        mergeTasks(latest,expected);setTaskError('')
        const terminal=latest.filter(task=>!isActiveTask(task.status))
        if(terminal.length){const refreshed=await Promise.all(terminal.map(task=>api.paper(task.paper_id)));if(alive.current)setPapers(current=>current.map(p=>{const task=terminal.find(item=>item.paper_id===p.id);const next=refreshed.find(item=>item.id===p.id);return next&&task&&p.intelligence_task?.id===task.id?{...next,intelligence_status:task.status,intelligence_task:task,intelligence_report:keepsPublishedReport(task)?next.intelligence_report:task.report}:p}))}
        if(active&&(latest.length<tracked.length||latest.some(task=>isActiveTask(task.status))))timer=setTimeout(()=>void poll(),1800)
      }catch(e){if(active){setTaskError(errorMessage(e));timer=setTimeout(()=>void poll(),5000)}}
    }
    timer=setTimeout(()=>void poll(),1000)
    return()=>{active=false;clearTimeout(timer)}
  },[activeSignature,mergeTasks])
  return {papers, collections, loading, error, reload,settings,taskError,queueAnalysis,cancelAnalysis}
}
export type Workspace = ReturnType<typeof useWorkspace>
