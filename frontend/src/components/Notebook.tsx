import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, BookOpen, Link2, LoaderCircle, MessageSquare, Plus } from 'lucide-react'
import type { Answer, Collection, Evidence, HistoryItem, LibraryAnswer, LibraryCitation, Note, Paper, PaperDetail } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { Empty, ErrorBanner } from './Shared'
import type { PdfLocator } from './PdfViewer'
import { PaperCard } from './PaperCard'
import { EvidenceIndex } from './EvidenceSources'
import { NotesPanel } from './NotesPanel'
import type { NoteComposeRequest, NoteFocusRequest } from './NotesPanel'
import { AnalysisControl } from './AnalysisControl'
import { IntelligenceAnswer } from './IntelligenceAnswer'
import { remoteAvailable } from '../lib/intelligence'
import type { Workspace } from '../lib/useWorkspace'

type Tab = 'overview'|'evidence'|'ask'|'notes'
export function Notebook({paper,setPaper,tab,setTab,page,locate,reload,notify,collections,reloadWorkspace,workspace,intelligencePaper,openMetadata,composeRequest,focusRequest,onNoteSaved,onNoteDeleted,onNoteFocus,clearNoteFocus}:{paper:PaperDetail;setPaper:(p:PaperDetail)=>void;tab:Tab;setTab:(t:Tab)=>void;page:number;locate:(l:PdfLocator)=>void;reload:()=>Promise<void>;notify:(m:string)=>void;collections:Collection[];reloadWorkspace:()=>Promise<void>;workspace:Workspace;intelligencePaper:Paper;openMetadata:()=>void;composeRequest:NoteComposeRequest|null;focusRequest:NoteFocusRequest|null;onNoteSaved:(note:Note,focus?:boolean)=>void;onNoteDeleted:(id:string)=>void;onNoteFocus:(id:string)=>void;clearNoteFocus:()=>void}) {
  const {t} = useUi()
  const [busy,setBusy] = useState('')
  const [error,setError] = useState('')
  const [question,setQuestion] = useState('')
  const [answer,setAnswer] = useState<Answer|null>(null)
  const [libraryAnswer,setLibraryAnswer]=useState<LibraryAnswer|null>(null)
  const [askBusy,setAskBusy]=useState(false)
  const history=useRef<HistoryItem[]>([]);const generation=useRef(0);const askController=useRef<AbortController>()
  const remote=remoteAvailable(workspace.settings)
  useEffect(()=>()=>{generation.current++;askController.current?.abort()},[paper.id])
  const [membership,setMembership] = useState(false)
  const [sourceTarget,setSourceTarget]=useState<string|null>(null)
  useEffect(()=>{
    if(tab!=='overview'||!sourceTarget)return
    const frame=requestAnimationFrame(()=>requestAnimationFrame(()=>{
      const target=document.getElementById(`paper-card-${sourceTarget}`)
      target?.scrollIntoView({block:'center'})
      target?.focus({preventScroll:true})
    }))
    const timer=window.setTimeout(()=>setSourceTarget(null),1800)
    return()=>{cancelAnimationFrame(frame);window.clearTimeout(timer)}
  },[tab,sourceTarget])
  const analyze = async()=>{setBusy('analyze');setError('');try{setPaper(await api.analyze(paper.id));await reloadWorkspace()}catch(e){setError(errorMessage(e))}finally{setBusy('')}}
  const ask = async()=>{
    if(!question.trim()||askBusy)return
    const value=question.trim(),token=++generation.current
    setAskBusy(true);setError('');setAnswer(null);setLibraryAnswer(null)
    askController.current=new AbortController()
    try{
      if(remote){
        const result=await api.librarian({question:value,paper_ids:[paper.id],history:history.current.slice(-8)},askController.current.signal)
        if(generation.current===token){
          setLibraryAnswer(result)
          history.current=[...history.current,{role:'user' as const,content:value.slice(0,4000)},{role:'assistant' as const,content:result.answer.slice(0,6000)}].slice(-8)
        }
      }else{
        const result=await api.ask(paper.id,value)
        if(generation.current===token)setAnswer(result)
      }
    }catch(e){if(generation.current===token&&(e as Error).name!=='AbortError')setError(errorMessage(e))}
    finally{if(generation.current===token)setAskBusy(false)}
  }
  const stopAsk=()=>{generation.current++;askController.current?.abort();setAskBusy(false)}
  const jumpLibraryCitation=(item:LibraryCitation)=>{if(item.source_type==='external_metadata'){openMetadata();return}if(item.source_type==='user')setTab('notes');if(item.page!=null)locate({page:item.page,bbox:item.bbox,page_width:item.page_width,page_height:item.page_height,source_text:item.source_text});else if(item.source_type!=='user')setTab('overview')}
  const changeCollection = async(id:string,add:boolean)=>{setBusy('collection');setError('');setPaper({...paper,collection_ids:add?[...paper.collection_ids,id]:paper.collection_ids.filter(c=>c!==id)});try{await api.membership(id,paper.id,add);await reload();await reloadWorkspace();notify(t('saved'))}catch(e){setPaper(paper);setError(errorMessage(e))}finally{setBusy('')}}
  const jumpEvidence = (item:Evidence)=>locate({page:item.page??1,bbox:item.bbox,page_width:item.page_width,page_height:item.page_height,source_text:item.source_text})
  return <aside className="notebook-panel"><div className="notebook-head"><div><span className="eyebrow">READING NOTEBOOK</span><h2>{t('notebook')}</h2></div><button className="icon-btn" aria-label={t('manageCollections')} onClick={()=>setMembership(!membership)}><Plus size={17}/></button></div>
    {membership&&<div className="notebook-memberships">{collections.map(c=><label key={c.id}><input type="checkbox" disabled={!!busy} checked={paper.collection_ids.includes(c.id)} onChange={e=>void changeCollection(c.id,e.target.checked)}/>{c.name}</label>)}{collections.length===0&&<p>{t('noCollections')}</p>}</div>}
    <div className="notebook-tabs">{(['overview','evidence','ask','notes'] as const).map(item=><button key={item} aria-label={t(item)} className={tab===item?'active':''} onClick={()=>setTab(item)}>{t(item)}{item==='notes'&&paper.notes.length>0&&<span>{paper.notes.length}</span>}</button>)}</div>
    <div className="notebook-content">{error&&<ErrorBanner error={error}/>}
      {paper.analysis_status==='no_text'&&<div className="capability-notice"><strong>{t('noText')}</strong><p>{t('noTextHint')}</p></div>}
      {tab==='overview'&&<><AnalysisControl paper={intelligencePaper} settings={workspace.settings} queue={force=>workspace.queueAnalysis([paper.id],force)} cancel={workspace.cancelAnalysis}/>{paper.analysis?<><div className="provider-line"><BookOpen size={13}/>{paper.analysis.provider??'MockProvider'} · {paper.analysis.mode==='extractive'?t('extractive'):paper.analysis.mode}</div><p className="capability-notice">{t(paper.analysis.mode==='extractive'?'extractiveNotice':'remoteNotice')}</p><PaperCard paper={paper} locate={jumpEvidence} sourceTarget={sourceTarget}/><div className="concept-tags">{paper.analysis.concepts.map(c=><span key={c}>{c}</span>)}</div></>:<Empty title={t('analysisEmpty')} text={t('analysisHint')}/>}{!remote&&<button className="btn secondary analyze-btn" disabled={!!busy||paper.chunks.length===0} onClick={()=>void analyze()}>{busy==='analyze'?<LoaderCircle size={14} className="spin"/>:<BookOpen size={14}/>} {t(busy==='analyze'?'analyzing':'analyze')}</button>}<div className="section-excerpts">{[...new Set(paper.chunks.map(c=>c.section).filter(Boolean))].map(section=><details key={section}><summary>{section}</summary>{paper.chunks.filter(c=>c.section===section).slice(0,3).map(c=><button key={c.id} onClick={()=>locate({...c,source_text:c.content})}><small>{t('page')} {c.page}</small><p>{c.content}</p></button>)}</details>)}</div></>}
      {tab==='evidence'&&<>{paper.evidence.length===0?<Empty title={t('evidenceEmpty')} text={t('evidenceHint')}/>:<EvidenceIndex paper={paper} locate={jumpEvidence} onEntry={id=>{setSourceTarget(id);setTab('overview')}}/>}</>}
      {tab==='ask'&&<div className="ask-panel"><div className="ask-intro"><MessageSquare size={23} strokeWidth={1.5}/><h3>{t('ask')}</h3><p>{t('askHint')}</p></div><div className="suggested-questions">{(['questionNovelty','questionLimitation','questionResults'] as const).map(key=><button key={key} onClick={()=>setQuestion(t(key))}>{t(key)}<ArrowUpRight size={13}/></button>)}</div><form className="ask-form" onSubmit={e=>{e.preventDefault();void ask()}}><textarea aria-label={t('ask')} value={question} onChange={e=>setQuestion(e.target.value)} placeholder={t('questionHint')} onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();void ask()}}}/><button className="btn primary" disabled={askBusy||!question.trim()}>{askBusy&&<LoaderCircle size={14} className="spin"/>}{t(askBusy?'asking':'send')}</button></form>{askBusy&&<button className="text-btn" onClick={stopAsk}>{t('cancelRequest')}</button>}{libraryAnswer&&<div className="ask-answer"><IntelligenceAnswer answer={libraryAnswer} onCitation={jumpLibraryCitation}/></div>}{answer&&<div className="ask-answer" role="status"><span className="provider-line">{answer.provider} · {answer.mode}</span>{answer.insufficient_evidence&&<strong>{t('noAnswer')}</strong>}<p>{answer.answer}</p>{answer.citations.map(item=><article className="answer-citation" key={item.id}><blockquote>{item.source_text}</blockquote><button className="text-btn" onClick={()=>jumpEvidence(item)}><Link2 size={12}/>{t('page')} {item.page} · {item.section}</button></article>)}</div>}</div>}
      <NotesPanel paperId={paper.id} notes={paper.notes} page={page} active={tab==='notes'} composeRequest={composeRequest} focusRequest={focusRequest} locate={locate} onSaved={onNoteSaved} onDeleted={onNoteDeleted} onFocus={onNoteFocus} clearFocus={clearNoteFocus} notify={notify}/>
    </div>
  </aside>
}
