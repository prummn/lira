import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUpRight, BookOpen, LoaderCircle, MessageSquare, Plus, Square } from 'lucide-react'
import type { HistoryItem, LibrarianThread, LibraryCitation, NotebookTab, Paper } from '../types'
import type { PdfLocator } from '../components/PdfViewer'
import type { Workspace } from '../lib/useWorkspace'
import { useUi } from '../lib/i18n'
import { api, errorMessage } from '../lib/api'
import { remoteAvailable } from '../lib/intelligence'
import { Empty, ErrorBanner } from '../components/Shared'
import { IntelligenceAnswer } from '../components/IntelligenceAnswer'
import { MetadataDialog } from '../components/MetadataDialog'

export function LibrarianPage({workspace,collectionId,thread,setThread,openPaper}:{workspace:Workspace;collectionId:string;thread:LibrarianThread;setThread:(thread:LibrarianThread)=>void;openPaper:(id:string,locator?:PdfLocator,tab?:NotebookTab)=>void}) {
  const {t}=useUi();const [question,setQuestion]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [notice,setNotice]=useState('');const [metadata,setMetadata]=useState<Paper|null>(null)
  const generation=useRef(0);const controller=useRef<AbortController>();const bottom=useRef<HTMLDivElement>(null)
  const available=remoteAvailable(workspace.settings)
  const scoped=useMemo(()=>workspace.papers.filter(p=>!p.is_demo&&(thread.scope==='selected'?thread.selectedIds.includes(p.id):!thread.scope||p.collection_ids.includes(thread.scope))),[workspace.papers,thread.scope,thread.selectedIds])
  const scopeKey=thread.scope+'|'+scoped.map(p=>p.id).sort().join(',')
  useEffect(()=>{generation.current++;controller.current?.abort();setBusy(false);return()=>{generation.current++;controller.current?.abort()}},[scopeKey])
  useEffect(()=>{bottom.current?.scrollIntoView({behavior:'smooth',block:'nearest'})},[busy,thread.turns.length])
  const changeScope=(scope:string,selectedIds=thread.selectedIds)=>{controller.current?.abort();generation.current++;setError('');setNotice(t('scopeChanged'));setThread({scope,selectedIds,turns:[]})}
  const stop=()=>{generation.current++;controller.current?.abort();setBusy(false);setNotice(t('requestStopped'))}
  const ask=async()=>{
    if(!question.trim()||busy||!available||!scoped.length)return
    if(thread.scope==='selected'&&scoped.length>50){setError(t('librarianSelectionLimit'));return}
    const value=question.trim(),token=++generation.current
    const previous=thread.turns.slice(-4)
    const history:HistoryItem[]=previous.flatMap(turn=>[{role:'user' as const,content:turn.question.slice(0,4000)},{role:'assistant' as const,content:turn.response.answer.slice(0,6000)}])
    controller.current=new AbortController();setBusy(true);setError('');setNotice('')
    try{
      const scope=thread.scope==='selected'?{paper_ids:scoped.map(p=>p.id)}:thread.scope?{collection_id:thread.scope}:{}
      const response=await api.librarian({question:value,...scope,history},controller.current.signal)
      if(generation.current!==token)return
      setThread({...thread,turns:[...thread.turns,{id:crypto.randomUUID(),question:value,response}].slice(-12)});setQuestion('')
    }catch(e){if(generation.current===token&&(e as Error).name!=='AbortError')setError(errorMessage(e))}finally{if(generation.current===token)setBusy(false)}
  }
  const citation=(item:LibraryCitation)=>{
    if(item.source_type==='external_metadata'){setMetadata(workspace.papers.find(p=>p.id===item.paper_id)??null);return}
    const locator=item.page==null?undefined:{page:item.page,source_text:item.source_text,bbox:item.bbox,page_width:item.page_width,page_height:item.page_height}
    openPaper(item.paper_id,locator,item.source_type==='user'?'notes':'overview')
  }
  return <div className="librarian-page"><section className="page-heading"><div><div className="eyebrow">{t('librarianEyebrow')}</div><h1>{t('librarianTitle')}</h1><p>{t('librarianSubtitle')}</p></div><button className="btn secondary" onClick={()=>{stop();setThread({...thread,turns:[]});setNotice('')}}><Plus size={15}/>{t('newConversation')}</button></section>
    <div className="librarian-layout"><aside className="librarian-scope-panel"><h2>{t('librarianScope')}</h2><select aria-label={t('librarianScope')} value={thread.scope} onChange={e=>changeScope(e.target.value)}><option value="">{t('librarianAll')}</option>{collectionId&&<option value={collectionId}>{t('librarianCurrent')} · {workspace.collections.find(c=>c.id===collectionId)?.name}</option>}{workspace.collections.filter(c=>c.id!==collectionId).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}<option value="selected">{t('librarianSelected')}</option></select>
      {thread.scope==='selected'&&<div className="librarian-paper-selection"><strong>{t('librarianChoose')}</strong><small>{scoped.length} / 50 · {t('librarianSelectionLimit')}</small>{workspace.papers.filter(p=>!p.is_demo).map(p=><label key={p.id}><input type="checkbox" checked={thread.selectedIds.includes(p.id)} disabled={!thread.selectedIds.includes(p.id)&&scoped.length>=50} onChange={e=>changeScope('selected',e.target.checked?[...thread.selectedIds,p.id]:thread.selectedIds.filter(id=>id!==p.id))}/><span>{p.title}</span></label>)}</div>}
      <div className="librarian-inventory"><BookOpen size={17}/><strong>{t('librarianInventory')}</strong><p>{scoped.length} {t('paperCount')} · {scoped.filter(p=>p.intelligence_status==='completed').length} {t('aiCount')}</p><small>{t('librarianCoverageHint')}</small></div><p className="librarian-local-note">{t('librarianThreadHint')}</p>
    </aside><section className="librarian-dialogue">
      {!available&&<p className="capability-notice">{t('analysisUnavailable')}</p>}
      <div className="librarian-conversation">{!thread.turns.length&&(scoped.length?<div className="librarian-welcome"><MessageSquare size={26} strokeWidth={1.4}/><h2>{t('librarianEmpty')}</h2><p>{t('librarianHint')}</p><div className="librarian-suggestions">{(['librarianQCompare','librarianQEvidence','librarianQNotes'] as const).map(key=><button key={key} onClick={()=>setQuestion(t(key))}>{t(key)}<ArrowUpRight size={14}/></button>)}</div></div>:<Empty title={t('librarianNoPapers')} text={t('librarianNoPapersHint')}/>)}
        {thread.turns.map(turn=><div className="librarian-turn" key={turn.id}><div className="librarian-user-question">{turn.question}</div><div className="librarian-answer"><IntelligenceAnswer answer={turn.response} onCitation={citation}/></div></div>)}
        {busy&&<div className="librarian-pending" role="status"><LoaderCircle className="spin" size={16}/>{t('asking')}</div>}<div ref={bottom}/></div>
      {error&&<ErrorBanner error={error} retry={()=>void ask()}/>} {notice&&<p className="librarian-notice" role="status">{notice}</p>}
      <form className="librarian-composer" onSubmit={e=>{e.preventDefault();void ask()}}><textarea aria-label={t('librarianQuestion')} value={question} onChange={e=>setQuestion(e.target.value)} placeholder={t('librarianPlaceholder')} onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();void ask()}}}/><footer><small>{t('librarianHint')}</small>{busy?<button type="button" className="btn secondary" onClick={stop}><Square size={12}/>{t('cancelRequest')}</button>:<button className="btn primary" disabled={!available||!scoped.length||!question.trim()}>{t('send')}<ArrowUpRight size={14}/></button>}</footer></form>
    </section></div>{metadata&&<MetadataDialog paper={metadata} close={()=>setMetadata(null)} saved={workspace.reload}/>}</div>
}
