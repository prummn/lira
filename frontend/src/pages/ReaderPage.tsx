import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, Highlighter, Info, MessageSquare, PanelLeftClose, PanelLeftOpen, Sparkles, X } from 'lucide-react'
import type { Collection, Note, NotebookTab, PaperDetail, ReadingDocument, ReadingParagraph, ReadingTranslation } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { Empty, ErrorBanner, Loading } from '../components/Shared'
import { PdfViewer } from '../components/PdfViewer'
import type { PdfLocator, PdfSelection } from '../components/PdfViewer'
import { Notebook } from '../components/Notebook'
import type { NoteComposeRequest, NoteFocusRequest } from '../components/NotesPanel'
import { paperAnnotations } from '../lib/pdfAnnotations'
import type { PdfAnnotation } from '../lib/pdfAnnotations'
import { TranslationPanel } from '../components/TranslationPanel'
import { ExplainPanel } from '../components/ExplainPanel'
import { MetadataDialog } from '../components/MetadataDialog'
import type { Workspace } from '../lib/useWorkspace'
import { isActiveTask } from '../lib/intelligence'
import './reader-translation.css'

export function ReaderPage({paperId,collections,reloadWorkspace,back,notify,initialLocator,initialTab='overview',workspace,backLabel}:{paperId:string;collections:Collection[];reloadWorkspace:()=>Promise<void>;back:()=>void;notify:(message:string)=>void;initialLocator?:PdfLocator|null;initialTab?:NotebookTab;workspace:Workspace;backLabel?:string}) {
  const {t} = useUi()
  const [paper,setPaper] = useState<PaperDetail|null>(null)
  const [error,setError] = useState('')
  const [locator,setLocator] = useState<PdfLocator|null>(initialLocator??null)
  const [selection,setSelection] = useState<PdfSelection|null>(null)
  const selectionRef=useRef(selection)
  selectionRef.current=selection
  const [composeRequest,setComposeRequest]=useState<NoteComposeRequest|null>(null)
  const [noteFocus,setNoteFocus]=useState<NoteFocusRequest|null>(null)
  const [activeNoteId,setActiveNoteId]=useState<string|null>(null)
  const noteSequence=useRef(0)
  const annotations=useMemo(()=>paperAnnotations(paper?.notes??[]),[paper?.notes])
  const [explaining,setExplaining] = useState(false)
  const [page,setPage] = useState(()=>Math.max(1,Number(localStorage.getItem('riw-page-'+paperId))||1))
  const [tab,setTab] = useState<NotebookTab>(initialTab)
  const [saving,setSaving] = useState(false)
  const [mode,setMode] = useState<'original'|'bilingual'>('original')
  const [reading,setReading] = useState<ReadingDocument|null>(null)
  const [readingLoading,setReadingLoading] = useState(false)
  const [readingError,setReadingError] = useState('')
  const [selected,setSelected] = useState<ReadingParagraph|null>(null)
  const [translations,setTranslations] = useState<Record<string,ReadingTranslation>>({})
  const [pending,setPending] = useState<Record<string,boolean>>({})
  const [translationErrors,setTranslationErrors] = useState<Record<string,string>>({})
  const [translationAvailable,setTranslationAvailable] = useState(false)
  const [layout,setLayout] = useState<'side'|'bottom'>(()=>localStorage.getItem('riw-translation-layout')==='bottom'?'bottom':'side')
  const [focus,setFocus] = useState(false)
  const [readerWidth,setReaderWidth] = useState(1200)
  const [metadataOpen,setMetadataOpen] = useState(false)
  const readerRef = useRef<HTMLDivElement>(null)
  const requests = useRef(new Map<string,AbortController>())
  const generation = useRef(0)
  const noteRevision=useRef(0)
  const readingInFlight = useRef(false)
  const reload = useCallback(async()=>{
    const token=generation.current,revision=noteRevision.current
    try {
      const next=await api.paper(paperId)
      if(generation.current!==token)return
      setPaper(current=>current&&noteRevision.current!==revision?{...next,notes:current.notes}:next);setError('')
    } catch(e) { if(generation.current===token)setError(errorMessage(e)) }
  },[paperId])
  const workspacePaper=workspace.papers.find(item=>item.id===paperId)
  const taskStamp=workspacePaper?.intelligence_task?.updated_at??workspacePaper?.intelligence_status
  useEffect(()=>{if(workspacePaper?.intelligence_task&&!isActiveTask(workspacePaper.intelligence_status))void reload()},[taskStamp,reload])
  useEffect(()=>{
    const token = ++generation.current,revision=noteRevision.current
    api.paper(paperId).then(p=>{if(generation.current===token)setPaper(current=>current&&noteRevision.current!==revision?{...p,notes:current.notes}:p)}).catch(e=>{if(generation.current===token)setError(errorMessage(e))})
    api.settings().then(s=>{if(generation.current===token)setTranslationAvailable(s.translation_available)}).catch(e=>{if(generation.current===token)setError(errorMessage(e))})
    return ()=>{generation.current++;requests.current.forEach(controller=>controller.abort());requests.current.clear()}
  },[paperId])
  useEffect(()=>{
    document.querySelector('.app-shell')?.classList.toggle('reading-focus',focus)
    return ()=>document.querySelector('.app-shell')?.classList.remove('reading-focus')
  },[focus])
  useEffect(()=>{
    const reader=readerRef.current
    if(!reader)return
    const observer=new ResizeObserver(([entry])=>setReaderWidth(entry.contentRect.width))
    observer.observe(reader)
    setReaderWidth(reader.clientWidth)
    return ()=>observer.disconnect()
  },[paper?.id])
  const sideAvailable=readerWidth>=1040
  const effectiveLayout=layout==='side'&&!sideAvailable?'bottom':layout
  const loadReading = async()=>{
    if(readingInFlight.current)return
    readingInFlight.current=true;setReadingLoading(true);setReadingError('')
    const token=generation.current
    try {
      const next=await api.readingParagraphs(paperId)
      if(generation.current!==token)return
      setReading(next);setTranslations(current=>({...next.translations,...current}))
    } catch(e) { if(generation.current===token)setReadingError(errorMessage(e)) }
    finally { if(generation.current===token){setReadingLoading(false);readingInFlight.current=false} }
  }
  const switchMode = (next:typeof mode)=>{
    setMode(next);setSelection(null);setError('')
    if(next==='bilingual'&&!reading)void loadReading()
  }
  const locate = (next:PdfLocator)=>{setMode('original');setLocator({...next,nonce:Date.now()});setSelection(null)}
  const choose = (paragraph:ReadingParagraph)=>{
    setSelected(paragraph);setSelection(null)
    const anchor=paragraph.anchors.find(a=>a.page===page)??paragraph.anchors[0]
    setLocator({...anchor,source_text:paragraph.source_text,kind:'translation',nonce:Date.now()})
  }
  const rememberPage = (next:number)=>{
    setPage(next);localStorage.setItem('riw-page-'+paperId,String(next))
    setSelected(current=>current?.anchors.some(anchor=>anchor.page===next)?current:null)
  }
  const translate = async(paragraph:ReadingParagraph)=>{
    choose(paragraph)
    if(translations[paragraph.id]||requests.current.has(paragraph.id)||!translationAvailable)return
    const token=generation.current,controller=new AbortController()
    requests.current.set(paragraph.id,controller)
    setPending(current=>({...current,[paragraph.id]:true}));setTranslationErrors(current=>({...current,[paragraph.id]:''}))
    try {
      const result=await api.translateParagraph(paperId,paragraph.id,controller.signal)
      if(generation.current===token)setTranslations(current=>({...current,[paragraph.id]:{text:result.text,model:result.model_version}}))
    } catch(e) {
      if(generation.current===token&&(e as Error).name!=='AbortError')setTranslationErrors(current=>({...current,[paragraph.id]:errorMessage(e)}))
    } finally {
      requests.current.delete(paragraph.id)
      if(generation.current===token)setPending(current=>({...current,[paragraph.id]:false}))
    }
  }
  const highlight = async()=>{
    if(!selection||saving)return
    const selected=selection,token=generation.current,intent=noteSequence.current
    setSaving(true);setError('')
    try {
      const saved=await api.note(paperId,{kind:'highlight',content:selected.text,source_text:selected.text,page:selected.page,bbox:selected.bbox,anchors:selected.anchors})
      if(generation.current!==token)return
      const focus=selectionRef.current===selected&&noteSequence.current===intent
      saveNote(saved,focus)
      if(focus){setMode('original');setSelection(null);window.getSelection()?.removeAllRanges()}
      notify(t('saved'))
    } catch(e) { if(generation.current===token)setError(errorMessage(e)) }
    finally { if(generation.current===token)setSaving(false) }
  }
  const changeLayout=(value:'side'|'bottom')=>{setLayout(value);localStorage.setItem('riw-translation-layout',value)}
  const saveNote=(note:Note,focus=true)=>{
    noteRevision.current++
    setPaper(current=>current?{...current,notes:current.notes.some(item=>item.id===note.id)?current.notes.map(item=>item.id===note.id?note:item):[...current.notes,note]}:current)
    if(focus){setTab('notes');setActiveNoteId(note.id);setNoteFocus({ids:[note.id],nonce:++noteSequence.current})}
  }
  const deleteNote=(id:string)=>{
    noteRevision.current++
    setPaper(current=>current?{...current,notes:current.notes.filter(note=>note.id!==id)}:current)
    setNoteFocus(current=>current?{...current,ids:current.ids.filter(noteId=>noteId!==id)}:null)
    setActiveNoteId(current=>current===id?null:current)
  }
  const openAnnotation=(annotation:PdfAnnotation)=>{
    setMode('original');setTab('notes');setSelection(null);window.getSelection()?.removeAllRanges()
    setActiveNoteId(annotation.notes[0].id);setNoteFocus({ids:annotation.notes.map(note=>note.id),nonce:++noteSequence.current})
  }
  const takeNote=()=>{
    if(!selection)return
    setComposeRequest({selection:structuredClone(selection),nonce:++noteSequence.current})
    setNoteFocus(null);setActiveNoteId(null);setMode('original');setTab('notes');setSelection(null);window.getSelection()?.removeAllRanges()
  }
  if(!paper)return error?<ErrorBanner error={error} retry={()=>void reload()}/>:<Loading text={t('paperLoading')}/>
  return <div ref={readerRef} className={`reader-page ${mode==='bilingual'?'translation-reading':''}`}>
    <div className="reader-toolbar">
      <button className="back-btn" onClick={back}><ArrowLeft size={16}/>{backLabel??t('back')}</button>
      <div className="reader-title" title={paper.title}>{paper.title}</div>
      {paper.is_demo&&<span className="demo-badge">{t('demo')}</span>}
      <button className="icon-btn reading-focus-button" aria-label={t(focus?'readingRestore':'readingFocus')} title={t(focus?'readingRestore':'readingFocus')} onClick={()=>setFocus(value=>!value)}>{focus?<PanelLeftOpen size={16}/>:<PanelLeftClose size={16}/>}</button>
      <button className="btn secondary" onClick={()=>setMetadataOpen(true)}><Info size={14}/>{t('paperMetadata')}</button>
      <span className="reader-pages">{paper.page_count} {t('page')}</span>
    </div>
    {error&&<ErrorBanner error={error}/>}
    <div className={`reader-layout ${mode==='bilingual'?`translation-layout translation-${effectiveLayout}`:''}`}>
      <section className="pdf-panel">
        <div className="reading-modes">{(['original','bilingual'] as const).map(item=><button key={item} className={mode===item?'active':''} aria-pressed={mode===item} onClick={()=>switchMode(item)}>{t(item)}</button>)}</div>
        {selection&&<div className="selection-actions"><strong>{t('selection')}</strong><span>{selection.text.slice(0,70)}</span><button disabled={saving} onClick={()=>void highlight()}><Highlighter size={14}/>{t('addHighlight')}</button><button onClick={takeNote}><MessageSquare size={14}/>{t('addNote')}</button><button onClick={()=>setExplaining(true)}><Sparkles size={14}/>{t('explainSelection')}</button><button className="icon-btn" aria-label={t('close')} onClick={()=>setSelection(null)}><X size={14}/></button></div>}
        {paper.pdf_available ? <PdfViewer key={paper.id} initialPage={page} url={'/api/papers/'+encodeURIComponent(paper.id)+'/pdf'} locator={locator} onSelection={setSelection} onPageChange={rememberPage}
          paragraphs={mode==='bilingual'?reading?.paragraphs:undefined} activeParagraphId={selected?.id} translatedParagraphIds={Object.keys(translations)} onTranslateParagraph={paragraph=>void translate(paragraph)} annotations={annotations} activeNoteId={activeNoteId} onOpenAnnotation={openAnnotation}/>
          : <Empty title={t('noPdf')} text={t('noPdfHint')}/>}
      </section>
      {mode==='bilingual'&&<TranslationPanel paragraphs={reading?.paragraphs??[]} selected={selected} translation={selected?translations[selected.id]:undefined} pending={!!(selected&&pending[selected.id])} error={selected?translationErrors[selected.id]??'':readingError} available={translationAvailable} page={page} layout={effectiveLayout} sideAvailable={sideAvailable} setLayout={changeLayout} choose={choose} translate={()=>{if(selected)void translate(selected)}} close={()=>{setSelected(null);setLocator(null)}} loading={readingLoading} retry={()=>void loadReading()}/>}
      <section className="reader-research-panel" hidden={mode==='bilingual'} aria-label={t('researchPanel')}>
        <Notebook paper={paper} setPaper={next=>setPaper(current=>current?{...next,notes:current.notes}:next)} tab={tab} setTab={setTab} page={page} locate={locate} reload={reload} notify={notify} collections={collections} reloadWorkspace={reloadWorkspace} workspace={workspace} intelligencePaper={workspacePaper??paper} openMetadata={()=>setMetadataOpen(true)} composeRequest={composeRequest} focusRequest={noteFocus} onNoteSaved={saveNote} onNoteDeleted={deleteNote} onNoteFocus={setActiveNoteId} clearNoteFocus={()=>{setNoteFocus(null);setActiveNoteId(null)}}/>
      </section>
    </div>
    {explaining&&selection&&<ExplainPanel paper={paper} selection={selection} close={()=>setExplaining(false)} locate={e=>locate({page:e.page??1,bbox:e.bbox,page_width:e.page_width,page_height:e.page_height,source_text:e.source_text})}/>}
    {metadataOpen&&<MetadataDialog paper={paper} close={()=>setMetadataOpen(false)} saved={async()=>{await reload();await reloadWorkspace()}}/>}
  </div>
}
