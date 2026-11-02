import { useEffect, useState } from 'react'
import { BookOpen, LoaderCircle, Plus } from 'lucide-react'
import type { Collection, Evidence, LibraryCitation, Note, Paper, PaperDetail } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { Empty, ErrorBanner } from './Shared'
import type { PdfLocator } from './PdfViewer'
import { EvidenceIndex } from './EvidenceSources'
import { NotesPanel } from './NotesPanel'
import type { NoteComposeRequest, NoteFocusRequest } from './NotesPanel'
import { AnalysisControl } from './AnalysisControl'
import { AnalysisOverview } from './AnalysisOverview'
import { PaperQuestion } from './PaperQuestion'
import { KnowledgePanel } from './KnowledgePanel'
import { remoteAvailable } from '../lib/intelligence'
import type { Workspace } from '../lib/useWorkspace'
type Tab = 'overview'|'evidence'|'ask'|'notes'|'knowledge'
export function Notebook({paper,setPaper,tab,setTab,page,locate,reload,notify,collections,reloadWorkspace,workspace,intelligencePaper,openMetadata,composeRequest,focusRequest,onNoteSaved,onNoteDeleted,onNoteFocus,clearNoteFocus,paragraphId,openPaper}:{paper:PaperDetail;setPaper:(p:PaperDetail)=>void;tab:Tab;setTab:(t:Tab)=>void;page:number;locate:(l:PdfLocator)=>void;reload:()=>Promise<void>;notify:(m:string)=>void;collections:Collection[];reloadWorkspace:()=>Promise<void>;workspace:Workspace;intelligencePaper:Paper;openMetadata:()=>void;composeRequest:NoteComposeRequest|null;focusRequest:NoteFocusRequest|null;onNoteSaved:(note:Note,focus?:boolean)=>void;onNoteDeleted:(id:string)=>void;onNoteFocus:(id:string)=>void;clearNoteFocus:()=>void;paragraphId?:string|null;openPaper:(id:string,locator?:PdfLocator)=>void}) {
  const {t} = useUi()
  const [busy,setBusy] = useState('')
  const [error,setError] = useState('')
  const remote=remoteAvailable(workspace.settings)
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
  const jumpLibraryCitation=(item:LibraryCitation)=>{if(item.source_type==='external_metadata'){openMetadata();return}if(item.source_type==='user')setTab('notes');if(item.page!=null)locate({page:item.page,bbox:item.bbox,page_width:item.page_width,page_height:item.page_height,source_text:item.source_text});else if(item.source_type!=='user')setTab('overview')}
  const changeCollection = async(id:string,add:boolean)=>{setBusy('collection');setError('');setPaper({...paper,collection_ids:add?[...paper.collection_ids,id]:paper.collection_ids.filter(c=>c!==id)});try{await api.membership(id,paper.id,add);await reload();await reloadWorkspace();notify(t('saved'))}catch(e){setPaper(paper);setError(errorMessage(e))}finally{setBusy('')}}
  const jumpEvidence = (item:Evidence)=>locate({page:item.page??1,bbox:item.bbox,page_width:item.page_width,page_height:item.page_height,source_text:item.source_text})
  return <aside className="notebook-panel"><div className="notebook-head"><div><span className="eyebrow">READING NOTEBOOK</span><h2>{t('notebook')}</h2></div><button className="icon-btn" aria-label={t('manageCollections')} onClick={()=>setMembership(!membership)}><Plus size={17}/></button></div>
    {membership&&<div className="notebook-memberships">{collections.map(c=><label key={c.id}><input type="checkbox" disabled={!!busy} checked={paper.collection_ids.includes(c.id)} onChange={e=>void changeCollection(c.id,e.target.checked)}/>{c.name}</label>)}{collections.length===0&&<p>{t('noCollections')}</p>}</div>}
    <div className="notebook-tabs">{(['overview','evidence','ask','notes','knowledge'] as const).map(item=><button key={item} aria-label={t(item)} className={tab===item?'active':''} onClick={()=>setTab(item)}>{t(item)}{item==='notes'&&paper.notes.length>0&&<span>{paper.notes.length}</span>}{item==='knowledge'&&paper.knowledge_candidates?.length? <span>{paper.knowledge_candidates.length}</span>:null}</button>)}</div>
    <div className={`notebook-content${tab==='ask'?' has-paper-question':tab==='knowledge'?' has-knowledge-intake':''}`}>{error&&<ErrorBanner error={error}/>}
      {paper.analysis_status==='no_text'&&<div className="capability-notice"><strong>{t('noText')}</strong><p>{t('noTextHint')}</p></div>}
      {tab==='overview'&&<><AnalysisControl paper={intelligencePaper} settings={workspace.settings} hasPublishedAnalysis={paper.analysis?.mode==='remote'} queue={force=>workspace.queueAnalysis([paper.id],force)} cancel={workspace.cancelAnalysis}/>{paper.analysis?<AnalysisOverview paper={paper} taskPaper={intelligencePaper} configured={remote} locate={jumpEvidence} sourceTarget={sourceTarget}/>:<Empty title={t('analysisEmpty')} text={t('analysisHint')}/>}{!remote&&<button className="btn secondary analyze-btn" disabled={!!busy||paper.chunks.length===0} onClick={()=>void analyze()}>{busy==='analyze'?<LoaderCircle size={14} className="spin"/>:<BookOpen size={14}/>} {t(busy==='analyze'?'analyzing':'analyze')}</button>}<div className="section-excerpts">{[...new Set(paper.chunks.map(c=>c.section).filter(Boolean))].map(section=><details key={section}><summary>{section}</summary>{paper.chunks.filter(c=>c.section===section).slice(0,3).map(c=><button key={c.id} onClick={()=>locate({...c,source_text:c.content})}><small>{t('page')} {c.page}</small><p>{c.content}</p></button>)}</details>)}</div></>}
      {tab==='evidence'&&<>{paper.evidence.length===0?<Empty title={t('evidenceEmpty')} text={t('evidenceHint')}/>:<EvidenceIndex paper={paper} locate={jumpEvidence} onEntry={id=>{setSourceTarget(id);setTab('overview')}}/>}</>}
      <PaperQuestion key={paper.id} paper={paper} page={page} remote={remote} active={tab==='ask'} onCitation={jumpLibraryCitation}/>
      {tab==='knowledge'&&<KnowledgePanel openPaper={openPaper} paperId={paper.id} active={tab==='knowledge'} locate={locate} paragraphId={paragraphId}/>}
      <NotesPanel paperId={paper.id} notes={paper.notes} page={page} active={tab==='notes'} composeRequest={composeRequest} focusRequest={focusRequest} locate={locate} onSaved={onNoteSaved} onDeleted={onNoteDeleted} onFocus={onNoteFocus} clearFocus={clearNoteFocus} notify={notify}/>
    </div>
  </aside>
}
