import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, Highlighter, Info, MessageSquare, Sparkles, X } from 'lucide-react'
import type { Collection, NotebookTab, PaperDetail } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { Empty, ErrorBanner, Loading } from '../components/Shared'
import { PdfViewer } from '../components/PdfViewer'
import type { PdfLocator, PdfSelection } from '../components/PdfViewer'
import { Notebook } from '../components/Notebook'
import { ExplainPanel } from '../components/ExplainPanel'
import { MetadataDialog } from '../components/MetadataDialog'
import type { Workspace } from '../lib/useWorkspace'
import { isActiveTask } from '../lib/intelligence'

const cachedTranslations=(paper:PaperDetail)=>Object.fromEntries((paper.translations??[]).map(item=>[item.chunk_id,item.text]))

export function ReaderPage({paperId,collections,reloadWorkspace,back,notify,initialLocator,initialTab='overview',workspace,backLabel}:{paperId:string;collections:Collection[];reloadWorkspace:()=>Promise<void>;back:()=>void;notify:(message:string)=>void;initialLocator?:PdfLocator|null;initialTab?:NotebookTab;workspace:Workspace;backLabel?:string}) {
  const {t} = useUi()
  const [paper,setPaper] = useState<PaperDetail|null>(null)
  const [error,setError] = useState('')
  const [locator,setLocator] = useState<PdfLocator|null>(initialLocator??null)
  const [selection,setSelection] = useState<PdfSelection|null>(null)
  const [explaining,setExplaining] = useState(false)
  const [page,setPage] = useState(()=>Math.max(1,Number(localStorage.getItem('riw-page-'+paperId))||1))
  const [tab,setTab] = useState<NotebookTab>(initialTab)
  const [saving,setSaving] = useState(false)
  const [mode,setMode] = useState<'original'|'bilingual'|'chinese'>('original')
  const [translations,setTranslations] = useState<Record<string,string>>({})
  const [translating,setTranslating] = useState('')
  const [translationAvailable,setTranslationAvailable] = useState(false)
  const [metadataOpen,setMetadataOpen] = useState(false)
  const reload = useCallback(async()=>{try{const next=await api.paper(paperId);setPaper(next);setTranslations(cachedTranslations(next));setError('')}catch(e){setError(errorMessage(e))}},[paperId])
  const workspacePaper=workspace.papers.find(item=>item.id===paperId)
  const taskStamp=workspacePaper?.intelligence_task?.updated_at??workspacePaper?.intelligence_status
  useEffect(()=>{if(workspacePaper?.intelligence_task&&!isActiveTask(workspacePaper.intelligence_status))void reload()},[taskStamp,reload])
  useEffect(()=>{let active=true;api.paper(paperId).then(p=>{if(active){setPaper(p);setTranslations(cachedTranslations(p))}}).catch(e=>{if(active)setError(errorMessage(e))});api.settings().then(s=>{if(active)setTranslationAvailable(s.translation_available)}).catch(e=>{if(active)setError(errorMessage(e))});return()=>{active=false}},[paperId])
  const locate = (next:PdfLocator) => {setMode('original');setLocator({...next,nonce:Date.now()});setSelection(null)}
  const rememberPage = (next:number)=>{setPage(next);localStorage.setItem('riw-page-'+paperId,String(next))}
  const highlight = async()=>{
    if(!selection||saving)return
    setSaving(true);setError('')
    try{await api.note(paperId,{kind:'highlight',content:selection.text,source_text:selection.text,page:selection.page,bbox:selection.bbox});await reload();setTab('notes');setSelection(null);notify(t('saved'))}catch(e){setError(errorMessage(e))}finally{setSaving(false)}
  }
  const translate = async(id:string)=>{setTranslating(id);setError('');try{const result=await api.translate(paperId,id);setTranslations(current=>({...current,[id]:result.text}))}catch(e){setError(errorMessage(e))}finally{setTranslating('')}}
  const switchMode = (next:typeof mode)=>{if(next!=='original'&&!translationAvailable&&!Object.keys(translations).length){setError(t('translationNeedsModel'));return}setMode(next);setError('')}
  if(!paper)return error?<ErrorBanner error={error} retry={()=>void reload()}/>:<Loading text={t('paperLoading')}/>
  return <div className="reader-page"><div className="reader-toolbar"><button className="back-btn" onClick={back}><ArrowLeft size={16}/>{backLabel??t('back')}</button><div className="reader-title" title={paper.title}>{paper.title}</div>{paper.is_demo&&<span className="demo-badge">{t('demo')}</span>}<button className="btn secondary" onClick={()=>setMetadataOpen(true)}><Info size={14}/>{t('paperMetadata')}</button><span className="reader-pages">{paper.page_count} {t('page')}</span></div>
    {error&&<ErrorBanner error={error}/>}
    <div className="reader-layout"><section className="pdf-panel">
      <div className="reading-modes"><span>{t('readMode')}</span>{(['original','bilingual','chinese'] as const).map(item=><button key={item} className={mode===item?'active':''} onClick={()=>switchMode(item)}>{t(item)}</button>)}</div>
      {selection&&<div className="selection-actions"><strong>{t('selection')}</strong><span>{selection.text.slice(0,70)}</span><button disabled={saving} onClick={()=>void highlight()}><Highlighter size={14}/>{t('addHighlight')}</button><button onClick={()=>setTab('notes')}><MessageSquare size={14}/>{t('addNote')}</button><button onClick={()=>setExplaining(true)}><Sparkles size={14}/>{t('explainSelection')}</button><button className="icon-btn" aria-label={t('close')} onClick={()=>setSelection(null)}><X size={14}/></button></div>}
      {paper.pdf_available ? mode==='original'?<PdfViewer key={paper.id} initialPage={page} url={'/api/papers/'+encodeURIComponent(paper.id)+'/pdf'} locator={locator} onSelection={setSelection} onPageChange={rememberPage}/>:<div className="paragraph-reader">{paper.chunks.map(chunk=><article className="paragraph-block" key={chunk.id}><header>{t('page')} {chunk.page} · {chunk.section}<button className="text-btn" onClick={()=>locate({...chunk,source_text:chunk.content})}>{t('viewSource')}</button></header>{mode==='bilingual'&&<p>{chunk.content}</p>}{translations[chunk.id]?<><p className="translated-text">{translations[chunk.id]}</p><small className="provider-line">{t('modelTranslation')}</small></>:translationAvailable?<button className="btn secondary" disabled={!!translating} onClick={()=>void translate(chunk.id)}>{t(translating===chunk.id?'translating':'translate')}</button>:<p className="muted">{t('translationNeedsModel')}</p>}</article>)}</div>:<Empty title={t('noPdf')} text={t('noPdfHint')}/>}
    </section><Notebook paper={paper} setPaper={setPaper} tab={tab} setTab={setTab} selection={selection} clearSelection={()=>setSelection(null)} page={page} locate={locate} reload={reload} notify={notify} collections={collections} reloadWorkspace={reloadWorkspace} workspace={workspace} intelligencePaper={workspacePaper??paper} openMetadata={()=>setMetadataOpen(true)}/></div>
    {explaining&&selection&&<ExplainPanel paper={paper} selection={selection} close={()=>setExplaining(false)} locate={e=>locate({page:e.page??1,bbox:e.bbox,page_width:e.page_width,page_height:e.page_height,source_text:e.source_text})}/>}
    {metadataOpen && <MetadataDialog paper={paper} close={()=>setMetadataOpen(false)} saved={async()=>{await reload();await reloadWorkspace()}}/>}
  </div>
}
