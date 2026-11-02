import { History, Plus } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { SavedConversation } from '../types'
import { useUi } from '../lib/i18n'
import './conversation-history.css'

export function ConversationHistory({items,current,loading,disabled=false,hasMore,onSelect,onNew,onMore}:{
  items:SavedConversation[];current:string|null;loading:boolean;disabled?:boolean;hasMore:boolean;
  onSelect:(id:string)=>void;onNew:()=>void;onMore:()=>void
}) {
  const {t,language}=useUi()
  const history=useRef<HTMLDetailsElement>(null)
  useEffect(()=>{
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&history.current?.open){history.current.open=false;history.current.querySelector('summary')?.focus()}}
    const outside=(event:PointerEvent)=>{if(history.current?.open&&!history.current.contains(event.target as Node))history.current.open=false}
    document.addEventListener('keydown',escape);document.addEventListener('pointerdown',outside)
    return()=>{document.removeEventListener('keydown',escape);document.removeEventListener('pointerdown',outside)}
  },[])
  return <div className="conversation-tools">
    <details ref={history} className="conversation-history">
      <summary><History size={14}/>{t(loading?'chatLoading':'chatHistory')}</summary>
      <div className="conversation-history-menu">
        {!items.length&&<p>{t('chatEmptyHistory')}</p>}
        {items.map(item=><button type="button" key={item.id} disabled={disabled||loading} aria-current={current===item.id} onClick={event=>{
          event.currentTarget.closest('details')?.removeAttribute('open');onSelect(item.id)
        }}><strong>{item.title||t('newConversation')}</strong><span>{new Date(item.updated_at).toLocaleString(language,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})} · {item.turn_count}</span></button>)}
        {hasMore&&<button type="button" disabled={disabled||loading} onClick={onMore}>{t('chatMore')}</button>}
      </div>
    </details>
    <button type="button" className="conversation-new" disabled={disabled||loading} onClick={onNew}><Plus size={14}/>{t('newConversation')}</button>
  </div>
}
