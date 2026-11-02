import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, FolderPlus, Highlighter, Info, Languages, MessageSquare, PanelLeftClose, PanelLeftOpen, Sparkles, X } from 'lucide-react'
import { createPortal } from 'react-dom'
import type { Collection, Note, NotebookTab, PaperDetail, PdfVisualRegion, ReadingDocument, ReadingParagraph, ReadingTranslation } from '../types'
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
import { ReadingConversations, type ExplanationRequest } from '../components/ReadingConversations'
import { isShortTranslationSelection, QuickTranslationPopover } from '../components/QuickTranslationPopover'
import { recordResearchActivity } from '../lib/researchActivity'
import { AddToCollectionDialog } from '../components/AddToCollectionDialog'
import { MetadataDialog } from '../components/MetadataDialog'
import type { Workspace } from '../lib/useWorkspace'
import { isActiveTask } from '../lib/intelligence'
import { isActiveTranslationQueueItem, useTranslationQueue } from '../lib/useTranslationQueue'
import { TranslationQueueProgress } from '../components/TranslationQueueProgress'
import './reader-translation.css'

function SelectionActions({selection, quickTranslationOpen, setQuickTranslationOpen, saving, highlight, takeNote, explain, close, t}:{
  selection: PdfSelection
  quickTranslationOpen: boolean
  setQuickTranslationOpen: (open:boolean)=>void
  saving: boolean
  highlight: ()=>void
  takeNote: ()=>void
  explain: ()=>void
  close: ()=>void
  t: ReturnType<typeof useUi>['t']
}) {
  const actionsRef = useRef<HTMLDivElement>(null)
  const repositionFrame = useRef(0)
  const [position, setPosition] = useState<{left:number;top:number}|null>(null)
  const place = useCallback(() => {
    const element = actionsRef.current
    let anchor = selection.selectionRect
    const liveSelection = window.getSelection()
    if (liveSelection && !liveSelection.isCollapsed && liveSelection.rangeCount) {
      const rects = Array.from(liveSelection.getRangeAt(0).getClientRects()).filter(rect => rect.width > 1 && rect.height > 1
        && rect.bottom >= 0 && rect.top <= window.innerHeight)
      if (rects.length) {
        const left = Math.min(...rects.map(rect => rect.left)), top = Math.min(...rects.map(rect => rect.top))
        const right = Math.max(...rects.map(rect => rect.right)), bottom = Math.max(...rects.map(rect => rect.bottom))
        anchor = {left, top, width:right-left, height:bottom-top}
      }
    }
    if (!anchor || !element) return
    const margin = 12, gap = 10
    const width = element.offsetWidth, height = element.offsetHeight
    const viewportWidth = window.innerWidth, viewportHeight = window.innerHeight
    let top = anchor.top - height - gap
    if (top < margin) top = Math.min(viewportHeight - margin - height, anchor.top + anchor.height + gap)
    top = Math.max(margin, Math.min(viewportHeight - margin - height, top))
    const left = Math.max(margin, Math.min(viewportWidth - margin - width, anchor.left + anchor.width / 2 - width / 2))
    setPosition({left, top})
  }, [selection.selectionRect, quickTranslationOpen])
  useLayoutEffect(() => { place() }, [place])
  useEffect(() => {
    const schedule = () => {
      cancelAnimationFrame(repositionFrame.current)
      repositionFrame.current = requestAnimationFrame(place)
    }
    window.addEventListener('resize', schedule)
    document.addEventListener('scroll', schedule, true)
    return () => {
      cancelAnimationFrame(repositionFrame.current)
      window.removeEventListener('resize', schedule)
      document.removeEventListener('scroll', schedule, true)
    }
  }, [place])
  const fixedStyle = selection.selectionRect ? {
    position:'fixed' as const,
    left: position?.left ?? 12,
    top: position?.top ?? 12,
    visibility: position ? 'visible' as const : 'hidden' as const,
  } : { position:'fixed' as const, left:12, top:12 }
  return createPortal(<div ref={actionsRef} className="selection-actions" style={fixedStyle}>
    <strong>{t('selection')}</strong>
    <span>{selection.text.slice(0,70)}</span>
    {selection.origin==='translation'&&<span className="selection-origin">{t('selectedTranslation')}</span>}
    {selection.origin!=='translation'&&isShortTranslationSelection(selection.text)&&<button onClick={()=>setQuickTranslationOpen(true)} aria-pressed={quickTranslationOpen}><Languages size={14}/>{t('quickTranslate')}</button>}
    {selection.origin!=='translation'&&<button disabled={saving} onClick={highlight}><Highlighter size={14}/>{t('addHighlight')}</button>}
    {selection.origin!=='translation'&&<button onClick={takeNote}><MessageSquare size={14}/>{t('addNote')}</button>}
    <button onClick={explain}><Sparkles size={14}/>{t('explainSelection')}</button>
    <button className="icon-btn" aria-label={t('close')} onClick={close}><X size={14}/></button>
    {quickTranslationOpen&&isShortTranslationSelection(selection.text)&&<QuickTranslationPopover text={selection.text} close={()=>setQuickTranslationOpen(false)}/>}
  </div>, document.body)
}

export function ReaderPage({paperId,collections,reloadWorkspace,back,notify,initialLocator,initialTab='overview',workspace,backLabel,openPaper}:{paperId:string;collections:Collection[];reloadWorkspace:()=>Promise<void>;back:()=>void;notify:(message:string)=>void;initialLocator?:PdfLocator|null;initialTab?:NotebookTab;workspace:Workspace;backLabel?:string;openPaper:(id:string,locator?:PdfLocator)=>void}) {
  const {t} = useUi()
  const [assigningCollection,setAssigningCollection] = useState(false)
  const [paper,setPaper] = useState<PaperDetail|null>(null)
  const [visualRegions,setVisualRegions] = useState<PdfVisualRegion[]>([])
  const [error,setError] = useState('')
  const [locator,setLocator] = useState<PdfLocator|null>(initialLocator??null)
  const [selection,setSelection] = useState<PdfSelection|null>(null)
  const [explanationRequest,setExplanationRequest] = useState<ExplanationRequest|null>(null)
  const [quickTranslationOpen,setQuickTranslationOpen] = useState(false)
  useEffect(()=>{setQuickTranslationOpen(false)},[selection?.text])
  const selectionRef=useRef(selection)
  selectionRef.current=selection
  const [composeRequest,setComposeRequest]=useState<NoteComposeRequest|null>(null)
  const [noteFocus,setNoteFocus]=useState<NoteFocusRequest|null>(null)
  const [activeNoteId,setActiveNoteId]=useState<string|null>(null)
  const noteSequence=useRef(0)
  const annotations=useMemo(()=>paperAnnotations(paper?.notes??[]),[paper?.notes])
  const [page,setPage] = useState(()=>Math.max(1,Number(localStorage.getItem('riw-page-'+paperId))||1))
  const [tab,setTab] = useState<NotebookTab>(initialTab)
  const [saving,setSaving] = useState(false)
  const [mode,setMode] = useState<'original'|'bilingual'>('original')
  const [reading,setReading] = useState<ReadingDocument|null>(null)
  const [readingLoading,setReadingLoading] = useState(false)
  const [readingError,setReadingError] = useState('')
  const [selected,setSelected] = useState<ReadingParagraph|null>(null)
  const [translations,setTranslations] = useState<Record<string,ReadingTranslation>>({})
  const translationsRef = useRef<Record<string,ReadingTranslation>>({})
  const regeneratedTranslations = useRef(new Set<string>())
  translationsRef.current = translations
  const [pending,setPending] = useState<Record<string,boolean>>({})
  const [checking,setChecking] = useState<Record<string,boolean>>({})
  const [reviewOnlyErrors,setReviewOnlyErrors] = useState<Record<string,boolean>>({})
  const [translationErrors,setTranslationErrors] = useState<Record<string,string>>({})
  const [translationAvailable,setTranslationAvailable] = useState(false)
  const [batchMode,setBatchMode] = useState(false)
  const [batchScope,setBatchScope] = useState<'page'|'paper'>('page')
  const [batchSelectedIds,setBatchSelectedIds] = useState<string[]>([])
  const [layout,setLayout] = useState<'side'|'bottom'>(()=>localStorage.getItem('riw-translation-layout')==='bottom'?'bottom':'side')
  const [focus,setFocus] = useState(false)
  const [readerWidth,setReaderWidth] = useState(1200)
  const [metadataOpen,setMetadataOpen] = useState(false)
  const readerRef = useRef<HTMLDivElement>(null)
  const requests = useRef(new Map<string,AbortController>())
  const queue = useTranslationQueue(paperId)
  const queueReadingRefresh = useRef(false)
  const queueReadingSignature = useRef('')
  const queueReadingAttempts = useRef(new Map<string,number>())
  const queueReadingTimer = useRef<ReturnType<typeof setTimeout>>()
  const [queueReadingRetry,setQueueReadingRetry] = useState(0)
  const readingRef = useRef<ReadingDocument|null>(null)
  readingRef.current = reading
  const generation = useRef(0)
  const noteRevision=useRef(0)
  const readingInFlight = useRef(false)
  const boundaryReviewInFlight = useRef(false)
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
    setVisualRegions([])
    api.paper(paperId).then(p=>{if(generation.current===token)setPaper(current=>current&&noteRevision.current!==revision?{...p,notes:current.notes}:p)}).catch(e=>{if(generation.current===token)setError(errorMessage(e))})
    api.settings().then(s=>{if(generation.current===token)setTranslationAvailable(s.translation_available)}).catch(e=>{if(generation.current===token)setError(errorMessage(e))})
    api.visualRegions(paperId).then(result=>{if(generation.current===token)setVisualRegions(result.items)}).catch(()=>{if(generation.current===token)setVisualRegions([])})
    return ()=>{generation.current++;clearTimeout(queueReadingTimer.current);requests.current.forEach(controller=>controller.abort());requests.current.clear()}
  },[paperId])
  useEffect(()=>{ void recordResearchActivity('reading', paperId) },[paperId])
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
      readingRef.current=next;setReading(next);setTranslationErrors(current=>({...next.translation_errors,...current}));setTranslations(current=>{const merged={...next.translations,...current};translationsRef.current=merged;return merged})
    } catch(e) { if(generation.current===token)setReadingError(errorMessage(e)) }
    finally { if(generation.current===token){setReadingLoading(false);readingInFlight.current=false} }
  }
  useEffect(()=>{
    const completed:Record<string,ReadingTranslation>={}
    for(const job of [...queue.jobs].reverse())for(const item of job.items)if(item.translation){
      for(const id of new Set([item.paragraph_id,item.original_paragraph_id,...item.aliases]))if(!regeneratedTranslations.current.has(id))completed[id]=item.translation
    }
    if(Object.keys(completed).length)setTranslations(current=>{const next={...current,...completed};translationsRef.current=next;return next})
  },[queue.jobs])
  useEffect(()=>{
    if(!reading||queueReadingRefresh.current)return
    const items=Object.values(queue.items)
    const unknown=[...new Set(items.filter(item=>!reading.paragraphs.some(paragraph=>paragraph.id===item.paragraph_id)).map(item=>item.paragraph_id))].sort().join('|')
    if(!unknown||queueReadingSignature.current===unknown||(queueReadingAttempts.current.get(unknown)??0)>=3)return
    clearTimeout(queueReadingTimer.current)
    queueReadingRefresh.current=true
    const token=generation.current
    void api.readingParagraphs(paperId).then(next=>{
      if(generation.current!==token)return
      queueReadingSignature.current=unknown;queueReadingAttempts.current.delete(unknown)
      readingRef.current=next;setReading(next);setReadingError('')
      setTranslations(current=>{const merged={...next.translations,...current};translationsRef.current=merged;return merged})
      setSelected(current=>{
        if(!current)return null
        const mapped=queue.items[current.id]?.paragraph_id??current.id
        return next.paragraphs.find(paragraph=>paragraph.id===mapped)??current
      })
      setBatchSelectedIds(current=>[...new Set(current.map(id=>queue.items[id]?.paragraph_id??id))])
    }).catch(e=>{
      if(generation.current!==token)return
      setReadingError(errorMessage(e))
      const attempts=(queueReadingAttempts.current.get(unknown)??0)+1
      queueReadingAttempts.current.set(unknown,attempts)
      if(attempts<3)queueReadingTimer.current=setTimeout(()=>setQueueReadingRetry(current=>current+1),1500)
    }).finally(()=>{queueReadingRefresh.current=false})
  },[queue.items,reading,paperId,queueReadingRetry])
  const switchMode = (next:typeof mode)=>{
    setMode(next);setSelection(null);setError('')
    if(next==='original'){setLocator(null);setSelected(null)}
    if(next==='bilingual'&&!reading)void loadReading()
  }
  const locate = (next:PdfLocator)=>{setMode('original');setLocator({...next,nonce:Date.now()});setSelection(null)}
  const choose = (paragraph:ReadingParagraph)=>{
    setSelected(paragraph);setSelection(null)
    const item=queue.items[paragraph.id]
    if(isActiveTranslationQueueItem(item)&&!translationsRef.current[paragraph.id])void queue.prioritize(paragraph.id)
    const anchor=paragraph.anchors.find(a=>a.page===page)??paragraph.anchors[0]
    setLocator({...anchor,source_text:paragraph.source_text,kind:'translation',nonce:Date.now()})
  }
  const rememberPage = (next:number)=>{
    setPage(next);localStorage.setItem('riw-page-'+paperId,String(next))
    if(mode!=='bilingual')setSelected(current=>current?.anchors.some(anchor=>anchor.page===next)?current:null)
    else if(selected&&!selected.anchors.some(anchor=>anchor.page===next)&&!translations[selected.id]&&!pending[selected.id]){setSelected(null);setLocator(null)}
  }
  type ParagraphRunResult = {ok:boolean;paragraphId:string;finalId?:string;error?:string;skipped?:boolean;aborted?:boolean}
  const runParagraph = async(paragraph:ReadingParagraph,translateAfter:boolean,options:{interactive?:boolean;signal?:AbortSignal;force?:boolean}={}):Promise<ParagraphRunResult>=>{
    const interactive=options.interactive!==false
    if(!translationAvailable)return {ok:false,paragraphId:paragraph.id,error:t('translationNeedsModel')}
    if(requests.current.has(paragraph.id))return {ok:false,paragraphId:paragraph.id,error:t('translationBusy')}
    const shouldReview=!translateAfter||paragraph.review_needed
    if(shouldReview&&boundaryReviewInFlight.current){if(interactive){choose(paragraph);notify(t('paragraphReviewBusy'))}return {ok:false,paragraphId:paragraph.id,error:t('paragraphReviewBusy')}}
    if(translateAfter&&interactive)choose(paragraph)
    if(translateAfter&&!options.force&&translationsRef.current[paragraph.id]&&!paragraph.review_needed)return {ok:true,paragraphId:paragraph.id,finalId:paragraph.id,skipped:true}
    const token=generation.current,controller=new AbortController()
    const relayAbort=()=>controller.abort()
    options.signal?.addEventListener('abort',relayAbort,{once:true})
    let target=paragraph
    let reviewing=false
    let reviewedTranslation:ReadingTranslation|undefined
    const requestIds=new Set([paragraph.id])
    requests.current.set(paragraph.id,controller)
    setPending(current=>({...current,[paragraph.id]:true}));setTranslationErrors(current=>({...current,[paragraph.id]:''}))
    try {
      if(shouldReview){
        reviewing=true;boundaryReviewInFlight.current=true
        setChecking(current=>({...current,[paragraph.id]:true}))
        for(let pass=0;pass<2;pass++){
          const reviewed=await api.reviewParagraph(paperId,target.id,controller.signal)
          if(generation.current!==token)return {ok:false,paragraphId:paragraph.id,aborted:true}
          const priorId=target.id
          target=reviewed.paragraphs.find(item=>item.id===reviewed.selected_paragraph_id)??target
          requestIds.add(target.id)
          requests.current.set(target.id,controller)
          setChecking(current=>({...current,[priorId]:false,[target.id]:true}))
          reviewedTranslation=reviewed.translations[target.id]
          readingRef.current=reviewed;setReading(reviewed);setTranslations(current=>{const merged={...reviewed.translations,...current};translationsRef.current=merged;return merged})
          setPending(current=>({...current,[priorId]:false,[target.id]:true}))
          // Any currently selected fragment may now belong to a merged unit.
          // Remap its identity in place, without choosing or scrolling.
          setSelected(current=>{
            if(!current)return null
            const id=reviewed.paragraph_redirects?.[current.id]??(current.id===priorId?target.id:current.id)
            return reviewed.paragraphs.find(item=>item.id===id)??current
          })
          if(!translateAfter){if(interactive)notify(t(reviewed.review.uncertain?'paragraphReviewUncertain':reviewed.review.merged?'paragraphReviewMerged':'paragraphReviewChecked'));return {ok:true,paragraphId:paragraph.id,finalId:target.id,skipped:true}}
          if(!target.review_needed)break
        }
        setChecking(current=>({...current,[paragraph.id]:false}))
        reviewing=false;boundaryReviewInFlight.current=false
        if(target.review_needed)throw new Error(t('paragraphReviewIncomplete'))
        if(reviewedTranslation&&!options.force){translationsRef.current={...translationsRef.current,[target.id]:reviewedTranslation};return {ok:true,paragraphId:paragraph.id,finalId:target.id,skipped:true}}
      }
      const result=await api.translateParagraph(paperId,target.id,controller.signal,options.force)
      if(generation.current===token){
        const nextTranslation={text:result.text,model:result.model_version}
        if(options.force)regeneratedTranslations.current.add(target.id)
        translationsRef.current={...translationsRef.current,[target.id]:nextTranslation}
        setTranslations(current=>({...current,[target.id]:nextTranslation}))
        void recordResearchActivity('language', paperId, target.id)
      }
      return {ok:true,paragraphId:paragraph.id,finalId:target.id}
    } catch(e) {
      const aborted=(e as Error).name==='AbortError'||controller.signal.aborted||options.signal?.aborted
      if(generation.current===token&&!aborted){
        const message=errorMessage(e)
        setTranslationErrors(current=>({...current,[target.id]:message}))
        setReviewOnlyErrors(current=>({...current,[target.id]:!translateAfter}))
        return {ok:false,paragraphId:paragraph.id,finalId:target.id,error:message}
      }
      return {ok:false,paragraphId:paragraph.id,finalId:target.id,aborted:true}
    } finally {
      options.signal?.removeEventListener('abort',relayAbort)
      requestIds.forEach(id=>requests.current.delete(id))
      if(reviewing)boundaryReviewInFlight.current=false
      if(generation.current===token){
        const cleared=Object.fromEntries([...requestIds].map(id=>[id,false]))
        setPending(current=>({...current,...cleared}));setChecking(current=>({...current,...cleared}))
      }
    }
  }
  const translate=(paragraph:ReadingParagraph)=>{
    const item=queue.items[paragraph.id]
    if(translationsRef.current[paragraph.id]&&!paragraph.review_needed){choose(paragraph);return}
    if(isActiveTranslationQueueItem(item)){choose(paragraph);return}
    if(item?.job_status==='paused'){
      choose(paragraph)
      if(!queue.busy)void queue.start('selected',[paragraph.id])
      return
    }
    if(item?.status==='failed'){
      choose(paragraph)
      void queue.action(item.job_id,'retry')
      return
    }
    void runParagraph(paragraph,true)
  }
  const toggleBatchMode=()=>setBatchMode(current=>!current)
  const changeBatchScope=(scope:'page'|'paper')=>{setBatchScope(scope);setBatchSelectedIds([])}
  const toggleBatchParagraph=(id:string,checked:boolean)=>setBatchSelectedIds(current=>checked?(current.includes(id)?current:[...current,id]):current.filter(item=>item!==id))
  const translateBatch=async()=>{
    if(queue.busy||!batchSelectedIds.length)return
    await queue.start('selected',[...batchSelectedIds])
  }
  const highlight = async()=>{
    if(!selection||saving)return
    const selected=selection,token=generation.current,intent=noteSequence.current
    setSaving(true);setError('')
    try {
      const saved=await api.note(paperId,{kind:'highlight',content:selected.text,source_text:selected.text,page:selected.page,bbox:selected.bbox,anchors:selected.anchors})
      if(generation.current!==token)return
      const focus=selectionRef.current===selected&&noteSequence.current===intent
      // A highlight is a reading mark, not a request to open the notebook.
      // Keep the current original/bilingual mode and any selected translation
      // in place; only clear the transient browser selection after saving.
      saveNote(saved,false)
      if(focus){setSelection(null);window.getSelection()?.removeAllRanges()}
      notify(t('saved'))
    } catch(e) { if(generation.current===token)setError(errorMessage(e)) }
    finally { if(generation.current===token)setSaving(false) }
  }
  const changeLayout=(value:'side'|'bottom')=>{setLayout(value);localStorage.setItem('riw-translation-layout',value)}
  const saveNote=(note:Note,focus=true)=>{
    noteRevision.current++
    setPaper(current=>current?{...current,notes:current.notes.some(item=>item.id===note.id)?current.notes.map(item=>item.id===note.id?note:item):[...current.notes,note]}:current)
    if(focus){setTab('notes');setActiveNoteId(note.id);setNoteFocus({ids:[note.id],nonce:++noteSequence.current})}
    void recordResearchActivity('notes', paperId, note.id)
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
      <ReadingConversations paper={paper} request={explanationRequest} locate={e=>locate({page:e.page??1,bbox:e.bbox,page_width:e.page_width,page_height:e.page_height,source_text:e.source_text})}/>
      <button className="icon-btn reading-focus-button" aria-label={t(focus?'readingRestore':'readingFocus')} title={t(focus?'readingRestore':'readingFocus')} onClick={()=>setFocus(value=>!value)}>{focus?<PanelLeftOpen size={16}/>:<PanelLeftClose size={16}/>}</button>
      <button className="btn secondary reader-collection-action" aria-label={t('addToCollection')} title={t('addToCollection')} onClick={()=>setAssigningCollection(true)}><FolderPlus size={15}/><span>{t('addToCollection')}</span></button>
      <button className="btn secondary" onClick={()=>setMetadataOpen(true)}><Info size={14}/>{t('paperMetadata')}</button>
      <span className="reader-pages">{paper.page_count} {t('page')}</span>
    </div>
    {error&&<ErrorBanner error={error}/>}
    <TranslationQueueProgress jobs={queue.jobs} busy={queue.busy} error={queue.error} action={queue.action}/>
    <div className={`reader-layout ${mode==='bilingual'?`translation-layout translation-${effectiveLayout}`:''}`}>
      <section className="pdf-panel">
        <div className="reading-modes">{(['original','bilingual'] as const).map(item=><button key={item} className={mode===item?'active':''} aria-pressed={mode===item} onClick={()=>switchMode(item)}>{t(item)}</button>)}</div>
        {selection&&<SelectionActions selection={selection} quickTranslationOpen={quickTranslationOpen} setQuickTranslationOpen={setQuickTranslationOpen} saving={saving} highlight={()=>void highlight()} takeNote={takeNote} explain={()=>{setExplanationRequest({key:crypto.randomUUID(),selection:structuredClone(selection)});setSelection(null);window.getSelection()?.removeAllRanges()}} close={()=>setSelection(null)} t={t}/>}
        {paper.pdf_available ? <PdfViewer key={paper.id} initialPage={page} url={'/api/papers/'+encodeURIComponent(paper.id)+'/pdf'} locator={locator} visualRegions={visualRegions} onSelection={next=>{setSelection(next);setQuickTranslationOpen(false)}} onAskVisualRegion={region=>{setSelection(null);setQuickTranslationOpen(false);setExplanationRequest({key:crypto.randomUUID(),visualPage:region.page,visualImage:region.imageDataUrl,selection:{page:region.page,text:region.selectedText,bbox:region.bbox,origin:'pdf',visualKind:region.kind,visualLabel:region.label}})}} onPageChange={rememberPage}
          paragraphs={mode==='bilingual'?reading?.paragraphs:undefined} activeParagraphId={selected?.id} translatedParagraphIds={Object.keys(translations)} paragraphQueueItems={queue.items} onTranslateParagraph={paragraph=>void translate(paragraph)} annotations={annotations} activeNoteId={activeNoteId} onOpenAnnotation={openAnnotation}/>
          : <Empty title={t('noPdf')} text={t('noPdfHint')}/>}
      </section>
      {mode==='bilingual'&&<TranslationPanel paragraphs={reading?.paragraphs??[]} selected={selected} translation={selected?translations[selected.id]:undefined} pending={!!(selected&&pending[selected.id])} checking={!!(selected&&checking[selected.id])} queueItem={selected?queue.items[selected.id]:undefined} queueItems={queue.items} regenerate={()=>{if(selected)void runParagraph(selected,true,{force:true})}} review={()=>{if(selected)void runParagraph(selected,false)}} retrySelected={()=>{if(selected){const item=queue.items[selected.id];if(item?.job_status==='paused')translate(selected);else if(item?.status==='failed')void queue.action(item.job_id,'retry');else void runParagraph(selected,!reviewOnlyErrors[selected.id],{force:!!translationsRef.current[selected.id]})}}} error={selected?translationErrors[selected.id]??queue.items[selected.id]?.error??'':readingError} available={translationAvailable} page={page} layout={effectiveLayout} sideAvailable={sideAvailable} setLayout={changeLayout} choose={choose} translate={()=>{if(selected)void translate(selected)}} close={()=>{setSelected(null);setLocator(null)}} loading={readingLoading} retry={()=>void loadReading()} batchMode={batchMode} batchScope={batchScope} batchSelectedIds={batchSelectedIds} translatedParagraphIds={Object.keys(translations)} batchRunning={queue.busy} onToggleBatchMode={toggleBatchMode} onBatchScopeChange={changeBatchScope} onToggleBatchParagraph={toggleBatchParagraph} onStartBatch={()=>void translateBatch()} onStartFull={()=>void queue.start('full')} onSelection={next=>{setSelection(next);setQuickTranslationOpen(false)}}/>}
      <section className="reader-research-panel" hidden={mode==='bilingual'} aria-label={t('researchPanel')}>
        <Notebook openPaper={openPaper} paper={paper} setPaper={next=>setPaper(current=>current?{...next,notes:current.notes}:next)} tab={tab} setTab={setTab} page={page} locate={locate} reload={reload} notify={notify} collections={collections} reloadWorkspace={reloadWorkspace} workspace={workspace} intelligencePaper={workspacePaper??paper} openMetadata={()=>setMetadataOpen(true)} composeRequest={composeRequest} focusRequest={noteFocus} onNoteSaved={saveNote} onNoteDeleted={deleteNote} onNoteFocus={setActiveNoteId} clearNoteFocus={()=>{setNoteFocus(null);setActiveNoteId(null)}} paragraphId={selected?.id}/>
      </section>
    </div>
    {assigningCollection&&<AddToCollectionDialog papers={[paper]} collections={collections} paperIds={[paper.id]} close={()=>setAssigningCollection(false)} saved={async(_ids,collection)=>{setPaper(current=>current?{...current,collection_ids:[...new Set([...current.collection_ids,collection.id])]}:current);await reloadWorkspace();notify(t('addedToCollection')+' '+collection.name)}}/>}
    {metadataOpen&&<MetadataDialog paper={paper} close={()=>setMetadataOpen(false)} saved={async()=>{await reload();await reloadWorkspace()}}/>}
  </div>
}
