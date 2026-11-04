import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, History, LoaderCircle, MessageSquare, AlertCircle } from 'lucide-react'
import type { Evidence, PaperDetail, SavedConversation } from '../types'
import type { PdfSelection } from './PdfViewer'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { ExplainPanel, type ExplanationState } from './ExplainPanel'
import './reading-conversations.css'

export interface ExplanationRequest { key:string; selection?:PdfSelection; visualPage?:number; visualImage?:string }
type Target=ExplanationRequest & { conversationId?:string; savedContext?:Record<string,unknown> }
const marker=(item:SavedConversation)=>[item.latest_turn_id??item.updated_at,item.latest_status??''].join(':')
function stored<T>(key:string,fallback:T):T { try{return JSON.parse(localStorage.getItem(key)??'null')??fallback}catch{return fallback} }

/** A stable reading entry; transient selections never own an in-flight chat. */
export function ReadingConversations({paper,request,locate}:{paper:PaperDetail;request:ExplanationRequest|null;locate:(e:Evidence)=>void}) {
  const {t,language}=useUi()
  const [target,setTarget]=useState<Target|null>(null)
  const [open,setOpen]=useState(false)
  const [{items,hasMore},setArchive]=useState<{items:SavedConversation[];hasMore:boolean}>({items:[],hasMore:false})
  const [error,setError]=useState('')
  const [loading,setLoading]=useState(false)
  const [current,setCurrent]=useState<ExplanationState>({id:null,status:null,question:''})
  const seenKey='riw-reading-chat-seen:'+paper.id
  const [seen,setSeen]=useState<Record<string,string>>(()=>stored(seenKey,{}))
  const activeId=useRef<string|null>(null)
  const restoreVersion=useRef(0)
  const alive=useRef(true)
  const historyRef=useRef<HTMLDetailsElement>(null)
  const menuRef=useRef<HTMLDivElement>(null)
  const menuId=useId()
  const [historyOpen,setHistoryOpen]=useState(false)
  const [menuPosition,setMenuPosition]=useState({left:12,top:12,width:370,maxHeight:500})
  const moreBusy=useRef(false)
  const loadBusy=useRef(false)
  const pollDelay=historyOpen||current.status==='running'||items.some(item=>item.latest_status==='running')?2000:15000
  const load=useCallback(async()=>{
    if(loadBusy.current)return
    loadBusy.current=true
    try {
      const list=await api.conversations('explanation',paper.id,undefined)
      if(alive.current){
        // Refresh the head without throwing away pages the researcher opened.
        const freshIds=new Set(list.items.map(item=>item.id))
        setArchive(previous=>({items:[...list.items,...previous.items.filter(item=>!freshIds.has(item.id))],
          hasMore:previous.items.length>list.items.length?previous.hasMore:list.has_more}))
        setError('')
      }
    } catch(e){if(alive.current)setError(errorMessage(e))}
    finally{loadBusy.current=false}
  },[paper.id])
  useEffect(()=>{
    alive.current=true
    let timer:ReturnType<typeof setTimeout>
    let round=0
    const poll=async()=>{const token=++round;clearTimeout(timer);if(!document.hidden)await load();if(alive.current&&token===round)timer=setTimeout(()=>{void poll()},pollDelay)}
    const resume=()=>{if(document.hidden)return;clearTimeout(timer);void poll()}
    void poll()
    window.addEventListener('focus',resume);document.addEventListener('visibilitychange',resume)
    return()=>{alive.current=false;round++;clearTimeout(timer);window.removeEventListener('focus',resume);document.removeEventListener('visibilitychange',resume)}
  },[load,pollDelay])
  useEffect(()=>{
    if(!request)return
    restoreVersion.current++;setLoading(false)
    setTarget(request);setOpen(true);setCurrent({id:null,status:null,question:''});activeId.current=null
  },[request])
  const report=useCallback((state:ExplanationState)=>{
    activeId.current=state.id
    setCurrent(previous=>previous.id===state.id&&previous.status===state.status&&previous.question===state.question?previous:state)
    void load()
  },[load])
  useEffect(()=>{
    if(!open)return
    const item=items.find(item=>item.id===current.id)
    if(!item||seen[item.id]===marker(item))return
    const next={...seen,[item.id]:marker(item)}
    setSeen(next)
    try{localStorage.setItem(seenKey,JSON.stringify(next))}catch{/* Archive stays available without browser storage. */}
  },[items,current.id,open,seen,seenKey])
  useEffect(()=>{
    const outside=(event:PointerEvent)=>{if(historyRef.current?.open&&!historyRef.current.contains(event.target as Node)&&!menuRef.current?.contains(event.target as Node))historyRef.current.open=false}
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&historyRef.current?.open){historyRef.current.open=false;historyRef.current.querySelector('summary')?.focus()}}
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape)
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape)}
  },[])
  useLayoutEffect(()=>{
    if(!historyOpen)return
    const place=()=>{
      const rect=historyRef.current?.getBoundingClientRect()
      if(!rect)return
      const width=Math.min(370,window.innerWidth-24),maxHeight=Math.min(520,window.innerHeight-24)
      const height=Math.min(menuRef.current?.offsetHeight??maxHeight,maxHeight)
      setMenuPosition({width,maxHeight,left:Math.max(12,Math.min(window.innerWidth-width-12,rect.right-width)),
        top:Math.max(12,Math.min(window.innerHeight-height-12,rect.bottom+9))})
    }
    place()
    window.addEventListener('resize',place);document.addEventListener('scroll',place,true)
    return()=>{window.removeEventListener('resize',place);document.removeEventListener('scroll',place,true)}
  },[historyOpen,items.length,error,hasMore])
  const restore=async(id:string)=>{
    if(historyRef.current)historyRef.current.open=false
    if(id===activeId.current&&target){setOpen(true);return}
    const version=++restoreVersion.current
    setLoading(true);setError('')
    try {
      const saved=await api.conversation(id),context=saved.context
      if(!alive.current||version!==restoreVersion.current)return
      const page=Number(context.page)||1
      const source=typeof context.selected_text==='string'?context.selected_text:''
      const translated=typeof context.translated_text==='string'?context.translated_text:''
      // Re-entering the same saved chat after New chat must also reset local state.
      setTarget({key:`${saved.id}:${version}`,conversationId:saved.id,savedContext:context,
        ...(context.visual?{visualPage:page,selection:{page,bbox:Array.isArray(context.bbox)?context.bbox:[0,0,1,1],text:translated||source,
          ...(context.visual_kind==='figure'||context.visual_kind==='table'||context.visual_kind==='equation'?{visualKind:context.visual_kind}:{ }),
          ...(typeof context.visual_label==='string'?{visualLabel:context.visual_label}:{}),
          ...(translated?{origin:'translation' as const,sourceText:source}:{})}}:{selection:{page,bbox:[0,0,1,1],text:translated||source,
          ...(translated?{origin:'translation' as const,sourceText:source}:{})}})})
      setCurrent({id:saved.id,status:saved.latest_status??null,question:saved.latest_question||saved.title})
      activeId.current=saved.id;setOpen(true)
    }catch(e){if(alive.current&&version===restoreVersion.current)setError(errorMessage(e))}
    finally{if(alive.current&&version===restoreVersion.current)setLoading(false)}
  }
  const more=async()=>{
    if(moreBusy.current)return
    moreBusy.current=true
    try {
      const list=await api.conversations('explanation',paper.id,undefined,items.length)
      if(alive.current)setArchive(previous=>({items:[...new Map([...previous.items,...list.items].map(item=>[item.id,item])).values()],hasMore:list.has_more}))
    }catch(e){if(alive.current)setError(errorMessage(e))}
    finally{moreBusy.current=false}
  }
  const suggested=items.find(item=>item.latest_status==='running')
    ??items.find(item=>item.latest_status==='completed'&&seen[item.id]!==marker(item))??items[0]
  const status=target?current.status:suggested?.latest_status
  const pending=status==='running',ready=status==='completed',failed=status==='failed'||status==='interrupted'
  return <div className="reading-conversations">
    <button type="button" className={'reading-chat-resume'+(pending?' is-running':ready?' is-ready':'')} aria-label={t('readingChats')} disabled={loading||(!target&&!items.length)} title={current.question||suggested?.latest_question||t('readingChatsEmpty')} onClick={()=>{if(target)setOpen(true);else if(suggested)void restore(suggested.id)}}>
      {pending?<LoaderCircle size={14} className="spin"/>:<MessageSquare size={14}/>}<span>{t('readingChats')}</span>
      {(pending||ready||failed)&&<small>{t(pending?'readingChatRunning':ready?'readingChatReady':'readingChatFailed')}</small>}
    </button>
    <details ref={historyRef} className="reading-chat-history" onToggle={event=>{setHistoryOpen(event.currentTarget.open);if(event.currentTarget.open)void load()}}>
      <summary aria-label={t('readingChatHistory')} title={t('readingChatHistory')} aria-controls={menuId}><History size={14}/><ChevronDown size={10}/></summary>
    </details>
    {historyOpen&&createPortal(<div ref={menuRef} id={menuId} className="reading-chat-menu" style={menuPosition} role="region" aria-label={t('readingChatHistory')}>
        <header><strong>{t('readingChatHistory')}</strong><span>{paper.title}</span></header>
        {error&&<div className="reading-chat-error" role="alert">{error}<button type="button" onClick={()=>void load()}>{t('retry')}</button></div>}
        {!items.length&&!error&&<p className="reading-chat-empty">{t('readingChatsEmpty')}</p>}
        <div className="reading-chat-items">{items.map(item=><button type="button" key={item.id} disabled={loading} aria-current={item.id===current.id?'true':undefined} onClick={()=>void restore(item.id)}>
          <span className="reading-chat-item-copy"><strong>{item.title||t('newConversation')}</strong><small>{t('page')} {Number(item.context.page)||1} · {new Date(item.updated_at).toLocaleDateString(language==='zh-CN'?'zh-CN':'en-US',{month:'short',day:'numeric'})}</small></span>
          <span className={'reading-chat-item-status status-'+(item.latest_status??'empty')}>{item.latest_status==='running'?<><LoaderCircle size={12} className="spin"/>{t('readingChatRunning')}</>:item.latest_status==='completed'?<><Check size={12}/>{t('readingChatReady')}</>:item.latest_status?<><AlertCircle size={12}/>{t('readingChatFailed')}</>:null}</span>
        </button>)}</div>
        {hasMore&&<button type="button" className="reading-chat-more" onClick={()=>void more()}>{t('chatMore')}</button>}
      </div>,document.body)}
    {target&&<ExplainPanel key={target.key} paper={paper} selection={target.selection} visualPage={target.visualPage} visualImage={target.visualImage} hidden={!open} conversationId={target.conversationId} savedContext={target.savedContext} onState={report} archive={{items,hasMore,loading,error,select:id=>{void restore(id)},more:()=>{void more()}}} close={()=>setOpen(false)} locate={locate}/>}
  </div>
}
