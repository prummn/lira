import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import type { ResearchStatus } from '../types'

export function useBackgroundStatus() {
  const [status,setStatus]=useState<ResearchStatus|null>(null)
  const [error,setError]=useState('')
  const alive=useRef(false),version=useRef(0)
  const refresh=useCallback(async()=>{
    const current=++version.current
    try {
      const next=await api.researchStatus()
      if(alive.current&&current===version.current){setStatus(next);setError('')}
    } catch(e){if(alive.current&&current===version.current)setError(errorMessage(e))}
  },[])
  useEffect(()=>{
    alive.current=true
    let timer:ReturnType<typeof setTimeout>,stopped=false
    const poll=async()=>{await refresh();if(!stopped)timer=setTimeout(poll,5000)}
    void poll()
    return()=>{stopped=true;alive.current=false;version.current++;clearTimeout(timer)}
  },[refresh])
  return {status,error,refresh}
}
