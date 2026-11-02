import { useEffect, useRef, useState } from 'react'
import type { ChatKind, SavedConversation, SavedTurn } from '../types'
import { api, ApiError, errorMessage } from './api'

// The archive must still work when browser storage is disabled or full.
function remember(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* SQLite remains the source of truth. */ }
}
function recalled(key: string) {
  try { return localStorage.getItem(key) } catch { return null }
}

/** SQLite owns the transcript; browser storage remembers only the selected ID. */
export function useConversation<R>(kind:ChatKind,paperId:string|undefined,context:Record<string,unknown>,initialId?:string) {
  const contextJson=JSON.stringify(context)
  const storageKey=`riw-chat:${kind}:${paperId??''}:${contextJson}`
  const [id,setId]=useState<string|null>(null)
  const [turns,setTurns]=useState<SavedTurn<R>[]>([])
  const [savedContext,setSavedContext]=useState(context)
  const [items,setItems]=useState<SavedConversation[]>([])
  const [hasMore,setHasMore]=useState(false)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const generation=useRef(0)
  const selected=useRef<string|null>(null)
  const creating=useRef<{generation:number;promise:Promise<SavedConversation>}|null>(null)
  const select=async(nextId:string)=>{
    const token=++generation.current
    setLoading(true);setError('')
    try {
      const saved=await api.conversation<R>(nextId)
      if(token!==generation.current)return
      selected.current=saved.id;setId(saved.id);setTurns(saved.turns);setSavedContext(saved.context)
      remember(storageKey,saved.id)
    } catch(e){if(token===generation.current)setError(errorMessage(e))}
    finally {if(token===generation.current)setLoading(false)}
  }
  useEffect(()=>{
    const token=++generation.current
    selected.current=null;setId(null);setTurns([]);setSavedContext(JSON.parse(contextJson));setItems([]);setLoading(true);setError('')
    void (async()=>{
      try {
        const list=await api.conversations(kind,paperId,JSON.parse(contextJson))
        if(token!==generation.current)return
        setItems(list.items);setHasMore(list.has_more)
        const pointer=recalled(storageKey)
        const nextId=initialId??(pointer==='new'?null:pointer??list.items[0]?.id)
        if(nextId){
          let saved
          try {saved=await api.conversation<R>(nextId)}
          catch(e) {
            if(!(e instanceof ApiError)||e.status!==404)throw e
            if(list.items[0]&&list.items[0].id!==nextId)saved=await api.conversation<R>(list.items[0].id)
          }
          if(token!==generation.current)return
          if(saved){selected.current=saved.id;setId(saved.id);setTurns(saved.turns);setSavedContext(saved.context);remember(storageKey,saved.id)}
        }
      }catch(e){if(token===generation.current)setError(errorMessage(e))}
      finally {if(token===generation.current)setLoading(false)}
    })()
    return()=>{generation.current++}
  },[kind,paperId,contextJson,storageKey,initialId])
  const refreshList=async()=>{
    const token=generation.current
    try {const list=await api.conversations(kind,paperId,JSON.parse(contextJson));if(token===generation.current){setItems(list.items);setHasMore(list.has_more)}}
    catch(e){if(token===generation.current)setError(errorMessage(e))}
  }
  const more=async()=>{
    const token=generation.current
    try {const list=await api.conversations(kind,paperId,JSON.parse(contextJson),items.length);if(token===generation.current){setItems(previous=>[...previous,...list.items]);setHasMore(list.has_more)}}
    catch(e){if(token===generation.current)setError(errorMessage(e))}
  }
  const refresh=async()=>{
    const token=generation.current,nextId=selected.current
    if(!nextId)return
    try {
      const saved=await api.conversation<R>(nextId)
      if(token===generation.current&&selected.current===nextId)setTurns(saved.turns)
    }catch(e){if(token===generation.current)setError(errorMessage(e))}
    if(token===generation.current&&selected.current===nextId)await refreshList()
  }
  const ensure=async()=>{
    if(selected.current)return selected.current
    const token=generation.current
    const request=creating.current?.generation===token?creating.current:{generation:token,promise:api.createConversation(kind,paperId,JSON.parse(contextJson))}
    creating.current=request
    try {
      const saved=await request.promise
      if(token===generation.current){selected.current=saved.id;setId(saved.id);setSavedContext(saved.context);remember(storageKey,saved.id)}
      return saved.id
    } finally {if(creating.current===request)creating.current=null}
  }
  const append=(question:string,response:R,turnId?:string)=>{
    setTurns(previous=>[...previous,{id:turnId??crypto.randomUUID(),question,response,status:'completed',error:null,created_at:new Date().toISOString()}])
    void refreshList()
  }
  const newChat=()=>{
    generation.current++;selected.current=null;setId(null);setTurns([]);setSavedContext(JSON.parse(contextJson));setLoading(false);setError('')
    remember(storageKey,'new');void refreshList()
  }
  const pending=turns.some(turn=>turn.status==='running')
  useEffect(()=>{
    if(!pending||!id)return
    let alive=true
    const timer=window.setInterval(()=>{
      if(document.hidden)return
      void api.conversation<R>(id).then(saved=>{if(alive)setTurns(saved.turns)}).catch(e=>{if(alive)setError(errorMessage(e))})
    },1500)
    return()=>{alive=false;window.clearInterval(timer)}
  },[id,pending])
  return {id,turns,context:savedContext,items,hasMore,loading,error,pending,ensure,append,newChat,select,more,refresh,refreshList}
}
