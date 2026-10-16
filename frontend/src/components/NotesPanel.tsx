import { useEffect, useRef, useState } from 'react'
import { ArrowUpLeft, Check, CircleHelp, CheckCircle2, Highlighter, Lightbulb, LoaderCircle, Pencil, Plus, StickyNote, Trash2, X } from 'lucide-react'
import type { Note, NoteKind } from '../types'
import type { PdfLocator, PdfSelection } from './PdfViewer'
import { noteAnchors } from '../lib/pdfAnnotations'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { ErrorBanner } from './Shared'
import { ScientificText } from './ScientificText'
import './reading-notes.css'

export interface NoteComposeRequest {selection:PdfSelection;nonce:number}
export interface NoteFocusRequest {ids:string[];nonce:number}
type Action={type:'new'}|{type:'quote';selection:PdfSelection}|{type:'edit';note:Note}
interface Draft {content:string;kind:NoteKind;source:PdfSelection|null;editingId:string|null;originalContent:string;originalKind:NoteKind}
const blank=():Draft=>({content:'',kind:'note',source:null,editingId:null,originalContent:'',originalKind:'note'})
type NoteFilter = 'all' | NoteKind
type NoteSort = 'position' | 'updated'

const noteKinds:NoteKind[]=['highlight','note','idea','question','todo']
const noteIcons:Record<NoteKind, typeof Highlighter>={
  highlight:Highlighter,
  note:StickyNote,
  idea:Lightbulb,
  question:CircleHelp,
  todo:CheckCircle2,
}
const parsedDate=(value?:string|null, fallback=0)=>{
  const result=value?Date.parse(value):NaN
  return Number.isFinite(result)?result:fallback
}

/** Return a stable document position for explicit anchors. Legacy page/bbox
 * notes have no reliable line geometry and stay after anchored notes. */
function notePosition(note:Note):[number,number,number,number,string] {
  const anchor=note.anchors?.[0]
  if(!anchor) return [Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER,parsedDate(note.created_at,Number.MAX_SAFE_INTEGER),note.id]
  return [anchor.page,anchor.bbox?.[1]??Number.MAX_SAFE_INTEGER,anchor.bbox?.[0]??Number.MAX_SAFE_INTEGER,parsedDate(note.created_at,Number.MAX_SAFE_INTEGER),note.id]
}

function compareNotes(a:Note,b:Note,sort:NoteSort) {
  if(sort==='updated') {
    const aTime=parsedDate(a.updated_at??a.created_at),bTime=parsedDate(b.updated_at??b.created_at)
    return bTime-aTime || b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id)
  }
  const ap=notePosition(a),bp=notePosition(b)
  return ap[0]-bp[0] || ap[1]-bp[1] || ap[2]-bp[2] || ap[3]-bp[3] || ap[4].localeCompare(bp[4])
}

export function NotesPanel({paperId,notes,page,active,composeRequest,focusRequest,locate,onSaved,onDeleted,onFocus,clearFocus,notify}:{
  paperId:string;notes:Note[];page:number;active:boolean;composeRequest:NoteComposeRequest|null;focusRequest:NoteFocusRequest|null
  locate:(locator:PdfLocator)=>void;onSaved:(note:Note,focus?:boolean)=>void;onDeleted:(id:string)=>void
  onFocus:(id:string)=>void;clearFocus:()=>void;notify:(message:string)=>void
}) {
  const {t,language}=useUi()
  const [draft,setDraft]=useState<Draft>(blank)
  const [busy,setBusy]=useState('')
  const [error,setError]=useState('')
  const [pending,setPending]=useState<Action|null>(null)
  const [deleting,setDeleting]=useState<string|null>(null)
  const [kindFilter,setKindFilter]=useState<NoteFilter>('all')
  const [sortMode,setSortMode]=useState<NoteSort>('position')
  const textarea=useRef<HTMLTextAreaElement>(null)
  const form=useRef<HTMLFormElement>(null)
  const lastCompose=useRef<number>()
  const mounted=useRef(true)
  const interaction=useRef({composeRequest,pending,active})
  interaction.current={composeRequest,pending,active}
  const dirty=draft.content.trim()!==draft.originalContent.trim()||draft.kind!==draft.originalKind
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
  useEffect(()=>{setKindFilter('all');setSortMode('position')},[paperId])

  const focusEditor=()=>requestAnimationFrame(()=>{
    form.current?.scrollIntoView({block:'nearest'})
    textarea.current?.focus({preventScroll:true})
  })
  const apply=(action:Action)=>{
    setPending(null);setError('');setDeleting(null)
    if(action.type==='edit') {
      const note=action.note,anchors=noteAnchors(note),kind=note.kind==='highlight'?'note':note.kind
      const content=note.kind==='highlight'?'':note.content
      setDraft({content,kind,source:note.source_text||anchors.length?{text:note.source_text??'',page:note.page??1,bbox:note.bbox??anchors[0]?.bbox??[],anchors}:null,editingId:note.id,originalContent:content,originalKind:kind})
    } else setDraft({...blank(),source:action.type==='quote'?action.selection:null})
    focusEditor()
  }
  const request=(action:Action)=>{if(busy)return;if(dirty){setPending(action);focusEditor()}else apply(action)}
  useEffect(()=>{
    if(!active||busy||!composeRequest||lastCompose.current===composeRequest.nonce)return
    lastCompose.current=composeRequest.nonce
    request({type:'quote',selection:composeRequest.selection})
  },[active,composeRequest?.nonce,busy])
  useEffect(()=>{
    if(!active||!focusRequest?.ids.length)return
    const frame=requestAnimationFrame(()=>{
      const target=document.getElementById(`reading-note-${focusRequest.ids[0]}`)
      target?.scrollIntoView({block:'nearest'});target?.focus({preventScroll:true})
    })
    return()=>cancelAnimationFrame(frame)
  },[active,focusRequest?.nonce])

  const save=async()=>{
    if(!draft.content.trim()||busy)return
    const captured=draft,composeNonce=interaction.current.composeRequest?.nonce
    setBusy('save');setError('')
    try{
      const content=captured.content.trim(),kind=captured.kind
      const saved=captured.editingId?await api.updateNote(paperId,captured.editingId,{content,kind}):await api.note(paperId,{
        content,kind,page:captured.source?.page??page,source_text:captured.source?.text??null,bbox:captured.source?.bbox??null,anchors:captured.source?.anchors??[]})
      if(!mounted.current)return
      const next=interaction.current.pending,newerQuote=interaction.current.composeRequest?.nonce!==composeNonce
      onSaved(saved,!next&&!newerQuote&&interaction.current.active)
      setDraft(blank());setPending(null)
      if(next&&!newerQuote)apply(next)
      notify(t('saved'))
    }catch(e){if(mounted.current)setError(errorMessage(e))}
    finally{if(mounted.current)setBusy('')}
  }
  const remove=async(note:Note)=>{
    if(busy)return
    setBusy(note.id);setError('')
    try{
      await api.deleteNote(paperId,note.id)
      if(!mounted.current)return
      onDeleted(note.id);setDeleting(null)
      if(draft.editingId===note.id)setDraft(blank())
      notify(t('noteDeleted'))
    }catch(e){if(mounted.current)setError(errorMessage(e))}
    finally{if(mounted.current)setBusy('')}
  }
  const sourcePages=draft.source?.anchors?.length?draft.source.anchors.map(anchor=>anchor.page):draft.source?[draft.source.page]:[]
  const visibleNotes=[...notes]
    .filter(note=>kindFilter==='all'||note.kind===kindFilter)
    .sort((a,b)=>compareNotes(a,b,sortMode))
  return <div className="notes-panel" hidden={!active}>
    <div className="notes-heading"><div><h3>{t('notesTitle')}</h3><p>{t('notesLinkedHint')}</p></div><button type="button" className="text-btn" disabled={!!busy} onClick={()=>request({type:'new'})}><Plus size={14}/>{t('newNote')}</button></div>
    {error&&<ErrorBanner error={error}/>}
    <form ref={form} className="note-form" onSubmit={event=>{event.preventDefault();void save()}}>
      <div className="note-form-head"><strong>{t(draft.editingId?'editingNote':draft.source?'noteOnSelection':'newNote')}</strong><select aria-label={t('noteKind')} value={draft.kind} disabled={!!busy} onChange={event=>setDraft(d=>({...d,kind:event.target.value as NoteKind}))}>{(['note','idea','question','todo'] as const).map(kind=><option value={kind} key={kind}>{t(kind)}</option>)}</select></div>
      {draft.source&&<div className="note-source-preview"><div><span>{t('quotedSource')} · {t('page')} {sourcePages.join(', ')}</span><button type="button" className="text-btn" onClick={()=>locate({...draft.source!,...draft.source!.anchors?.[0],source_text:draft.source!.text})}><ArrowUpLeft size={12}/>{t('noteViewSource')}</button></div><blockquote><ScientificText text={draft.source.text}/></blockquote></div>}
      {pending&&<div className="note-draft-prompt" role="alert"><p>{t('noteUnsavedHint')}</p><button type="button" className="text-btn" disabled={!!busy} onClick={()=>{setPending(null);focusEditor()}}>{t('noteKeepEditing')}</button><button type="button" className="text-btn" disabled={!!busy} onClick={()=>apply(pending)}>{t('noteDiscardDraft')}</button></div>}
      <textarea ref={textarea} aria-label={t('note')} value={draft.content} disabled={!!busy} placeholder={t(draft.source?'noteQuotePlaceholder':'notePlaceholder')} onChange={event=>setDraft(d=>({...d,content:event.target.value}))} onKeyDown={event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();void save()}}}/>
      <div className="note-editor-actions"><span>{t('noteSaveShortcut')}</span>{(draft.editingId||draft.source)&&<button type="button" className="text-btn" disabled={!!busy} onClick={()=>request({type:'new'})}>{t('cancel')}</button>}<button className="btn primary" disabled={!!busy||!draft.content.trim()}>{busy==='save'?<LoaderCircle size={14} className="spin"/>:<Check size={14}/>} {t(pending?'saveNoteAndSwitch':draft.editingId?'saveNoteChanges':'save')}</button></div>
    </form>
    {focusRequest?.ids.length?<div className="notes-source-context"><span>{t('linkedNotesLocated')} · {focusRequest.ids.length}</span><button className="text-btn" onClick={clearFocus}><X size={12}/>{t('clearNoteFocus')}</button></div>:null}
    {notes.length>0&&<div className="notes-toolbar" aria-label={t('notesViewControls')}>
      <label><span>{t('notesFilter')}</span><select aria-label={t('notesFilter')} value={kindFilter} onChange={event=>setKindFilter(event.target.value as NoteFilter)}>
        <option value="all">{t('notesFilterAll')} · {notes.length}</option>
        {noteKinds.map(kind=><option value={kind} key={kind}>{t(kind)} · {notes.filter(note=>note.kind===kind).length}</option>)}
      </select></label>
      <label><span>{t('notesSort')}</span><select aria-label={t('notesSort')} value={sortMode} onChange={event=>setSortMode(event.target.value as NoteSort)}>
        <option value="position">{t('notesSortPosition')}</option><option value="updated">{t('notesSortUpdated')}</option>
      </select></label>
    </div>}
    {notes.length===0?<div className="notes-empty"><Highlighter size={19}/><p>{t('notesEmptyHint')}</p></div>:visibleNotes.length===0?<div className="notes-filter-empty"><p>{t('notesFilterEmpty')}</p><button type="button" className="text-btn" onClick={()=>setKindFilter('all')}>{t('notesFilterAll')}</button></div>:<div className="saved-notes">{visibleNotes.map(note=>{
      const focused=focusRequest?.ids.includes(note.id),anchors=noteAnchors(note)
      const KindIcon=noteIcons[note.kind]
      return <article className={`saved-note note-type-${note.kind} ${focused?'is-focused':''}`} id={`reading-note-${note.id}`} data-note-id={note.id} tabIndex={-1} key={note.id} onFocus={()=>onFocus(note.id)}>
        <div className="saved-note-head"><span className={'note-kind note-kind-'+note.kind}><KindIcon size={12} strokeWidth={2} aria-hidden="true"/><span>{t(note.kind)}</span></span><span className="note-date">{new Date(note.updated_at??note.created_at).toLocaleDateString(language)}</span><button type="button" className="icon-btn" aria-label={t('editNote')} title={t(note.kind==='highlight'?'annotationAddThought':'editNote')} disabled={!!busy} onClick={()=>request({type:'edit',note})}><Pencil size={14}/></button><button type="button" className="icon-btn" aria-label={t('deleteNote')} title={t('deleteNote')} disabled={!!busy} onClick={()=>setDeleting(note.id)}><Trash2 size={14}/></button></div>
        {note.kind==='highlight'?<blockquote className="saved-highlight-text"><ScientificText text={note.source_text??note.content}/></blockquote>:<><ScientificText text={note.content}/>{note.source_text&&<blockquote><ScientificText text={note.source_text}/></blockquote>}</>}
        <footer>{note.page?<button className="text-btn" onClick={()=>{onFocus(note.id);locate({...anchors[0]??{page:note.page!,bbox:note.bbox},source_text:note.source_text??''})}}><ArrowUpLeft size={12}/>{t('page')} {anchors.length>1?`${anchors[0].page}–${anchors[anchors.length-1].page}`:note.page}</button>:<span>{t('paperNote')}</span>}{note.kind==='highlight'&&<button className="text-btn" disabled={!!busy} onClick={()=>request({type:'edit',note})}><Pencil size={12}/>{t('annotationAddThought')}</button>}</footer>
        {deleting===note.id&&<div className="note-delete-confirm" role="alert"><p>{t('deleteNoteHint')}</p><button className="text-btn" disabled={!!busy} onClick={()=>setDeleting(null)}>{t('cancel')}</button><button className="text-btn danger" disabled={!!busy} onClick={()=>void remove(note)}>{busy===note.id?<LoaderCircle size={13} className="spin"/>:null}{t('confirmDeleteNote')}</button></div>}
      </article>
    })}</div>}
  </div>
}
