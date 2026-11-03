import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUpRight, BookOpen, Bookmark, CheckCircle2, FileText, FolderPlus, Info, Link2, LoaderCircle, Plus, Search, Tag, Trash2, Upload, X } from 'lucide-react'
import type { Collection, Paper, ReadingStatus, ResearchActivity, SearchHit } from '../types'
import type { PdfLocator } from '../components/PdfViewer'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import type { Workspace } from '../lib/useWorkspace'
import { Empty, ErrorBanner, Modal } from '../components/Shared'
import { AddToCollectionDialog } from '../components/AddToCollectionDialog'
import { ImportUrlDialog } from '../components/ImportUrlDialog'
import { MetadataDialog } from '../components/MetadataDialog'
import { ImportFilesDialog } from '../components/ImportFilesDialog'
import { AnalysisBadge } from '../components/AnalysisBadge'
import { intelligenceKeys, isActiveTask, remoteAvailable } from '../lib/intelligence'
import { recordResearchActivity } from '../lib/researchActivity'
import { ResearchActivityHeatmap } from '../components/ResearchActivityHeatmap'

export const statuses: ReadingStatus[] = ['unread','skimming','reading','read','important']
export function LibraryPage({ workspace, collectionId, query, setQuery, openPaper, newCollection, collectionDeleted, notify, openResearch }: {workspace:Workspace;collectionId:string;query:string;setQuery:(value:string)=>void;openPaper:(id:string,locator?:PdfLocator)=>void;newCollection:()=>void;collectionDeleted:(id:string)=>void;notify:(message:string)=>void;openResearch?:(view?:'essay'|'findings')=>void}) {
  const {t} = useUi()
  const [status, setStatus] = useState('')
  const [favorite, setFavorite] = useState(false)
  const [sort, setSort] = useState('recent')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState('')
  const [outcomes, setOutcomes] = useState<{name:string;ok:boolean;message:string}[]>([])
  const [assignment, setAssignment] = useState<{paperIds?:string[];collectionId?:string}|null>(null)
  const [editing, setEditing] = useState<Paper|null>(null)
  const [tags, setTags] = useState('')
  const [mutation, setMutation] = useState('')
  const [hits,setHits] = useState<SearchHit[]>([])
  const [searchError,setSearchError] = useState('')
  const [urlImport,setUrlImport] = useState(false)
  const [metadataPaper,setMetadataPaper] = useState<Paper|null>(null)
  const [pendingFiles,setPendingFiles]=useState<File[]>([])
  const [aiFilter,setAiFilter]=useState('')
  const [selected,setSelected]=useState<string[]>([])
  const [focusedPaperId,setFocusedPaperId]=useState('')
  const [deleteCollectionTarget,setDeleteCollectionTarget]=useState<Collection|null>(null)
  const [deletingCollection,setDeletingCollection]=useState(false)
  const [deleteCollectionError,setDeleteCollectionError]=useState('')
  const collectionDeletionBusy=useRef(false)
  const confirmDeleteCollection=async()=>{
    if(collectionDeletionBusy.current||!deleteCollectionTarget)return
    collectionDeletionBusy.current=true;setDeletingCollection(true);setDeleteCollectionError('')
    try {
      await api.deleteCollection(deleteCollectionTarget.id)
      await workspace.reload()
      setSelected([]);setFocusedPaperId('');setAssignment(null)
      collectionDeleted(deleteCollectionTarget.id)
      setDeleteCollectionTarget(null)
    } catch(e) {setDeleteCollectionError(errorMessage(e))}
    finally {collectionDeletionBusy.current=false;setDeletingCollection(false)}
  }
  const [deleteTargets,setDeleteTargets]=useState<Paper[]>([])
  const [deleting,setDeleting]=useState(false)
  const [deleteError,setDeleteError]=useState('')
  const requestDelete=(papers:Paper[])=>{setDeleteError('');setDeleteTargets(papers)}
  const confirmDelete=async()=>{
    if(deleting||!deleteTargets.length)return
    setDeleting(true);setDeleteError('')
    try {
      const ids=deleteTargets.map(p=>p.id)
      const result=ids.length===1?await api.deletePaper(ids[0]):await api.deletePapers(ids)
      const removed=new Set(result.deleted_ids)
      setSelected(current=>current.filter(id=>!removed.has(id)))
      setFocusedPaperId(current=>removed.has(current)?'':current)
      setHits(current=>current.filter(hit=>!removed.has(hit.paper_id)))
      setDeleteTargets([])
      notify(t('papersDeleted')+' '+result.deleted_ids.length)
      await workspace.reload()
      void refreshActivity()
    } catch(e) {setDeleteError(errorMessage(e));setError(errorMessage(e))}
    finally {setDeleting(false)}
  }
  const [analysisBusy,setAnalysisBusy]=useState(false)
  const [activity,setActivity]=useState<ResearchActivity|null>(null)
  const [activityLoading,setActivityLoading]=useState(true)
  const [activityError,setActivityError]=useState('')
  const [selectedActivityDate,setSelectedActivityDate]=useState('')
  const importStopped=useRef(false)
  const enabled=remoteAvailable(workspace.settings)
  useEffect(()=>{
    let active=true;setHits([]);setSearchError('')
    if(query.trim().length<2)return
    const timer=setTimeout(()=>{api.search(query.trim(),collectionId).then(data=>{if(active){setHits(data.items);void recordResearchActivity('search',undefined,query.trim().toLocaleLowerCase())}}).catch(e=>{if(active)setSearchError(errorMessage(e))})},300)
    return()=>{active=false;clearTimeout(timer)}
  },[query,collectionId])
  const refreshActivity=()=>{
    setActivityLoading(true);setActivityError('')
    return api.activity(371).then(next=>setActivity(next)).catch(e=>setActivityError(errorMessage(e))).finally(()=>setActivityLoading(false))
  }
  useEffect(()=>{void refreshActivity()},[])
  const inputRef = useRef<HTMLInputElement>(null)
  const filtered = useMemo(() => {
    const selectedPaperIds = selectedActivityDate ? new Set(activity?.days.find(day=>day.date===selectedActivityDate)?.paper_ids ?? []) : null
    const items = workspace.papers.filter(p => (!selectedPaperIds || selectedPaperIds.has(p.id)) && (!collectionId || p.collection_ids.includes(collectionId)) && (!status || p.reading_status === status) && (!aiFilter||(p.intelligence_status??'unanalyzed')===aiFilter) && (!favorite || p.is_favorite) && (p.title + ' ' + p.authors.join(' ') + ' ' + p.tags.join(' ') + ' ' + (p.venue ?? '')).toLowerCase().includes(query.toLowerCase()))
    return sort === 'year' ? items.sort((a,b)=>(b.year ?? 0)-(a.year ?? 0)) : sort === 'title' ? items.sort((a,b)=>a.title.localeCompare(b.title)) : items
  }, [workspace.papers,collectionId,status,aiFilter,favorite,query,sort,activity,selectedActivityDate])
  const prepareFiles=(files:FileList|File[])=>{if(!busy&&!urlImport){setPendingFiles(Array.from(files));if(inputRef.current)inputRef.current.value=''}}
  const importFiles = async (files: File[],analyze:boolean) => {
    if(busy || urlImport) return
    setPendingFiles([]);setBusy(true); setError(''); setOutcomes([]);importStopped.current=false
    const results: typeof outcomes = []
    const batch = Array.from(files)
    for(let i=0;i<batch.length;i++) {
      if(importStopped.current)break
      const file = batch[i]; setProgress(String(i+1) + ' / ' + batch.length + ' · ' + file.name)
      try { const paper = await api.import(file,analyze); if(collectionId) await api.membership(collectionId,paper.id,true); void recordResearchActivity('imports',paper.id); results.push({name:file.name,ok:true,message:t('importDone')}) }
      catch(e) { results.push({name:file.name,ok:false,message:errorMessage(e)}) }
      setOutcomes([...results])
    }
    await workspace.reload(); void refreshActivity(); setBusy(false); setProgress('')
    if(inputRef.current) inputRef.current.value = ''
  }
  const analyzeSelected=async()=>{
    if(!enabled||analysisBusy||!selected.length)return
    setAnalysisBusy(true);setError('')
    let submitted=0
    try{
      await workspace.queueAnalysis(selected,false,batch=>{
        submitted+=batch.length
        const accepted=new Set(batch)
        setSelected(current=>current.filter(id=>!accepted.has(id)))
      })
    }catch(e){setError((submitted?t('analysisBatchPartialError')+' ':'')+errorMessage(e))}
    finally{setAnalysisBusy(false)}
  }
  const cancelTask=async(id:string)=>{try{await workspace.cancelAnalysis(id)}catch(e){setError(errorMessage(e))}}
  const update = async (paper:Paper, body:Parameters<typeof api.update>[1]) => {
    setMutation(paper.id); setError('')
    try { await api.update(paper.id,body); await workspace.reload(); notify(t('saved')) } catch(e) { setError(errorMessage(e)) } finally {setMutation('')}
  }
  const membership = async (paper:Paper,id:string,add:boolean) => {
    setMutation(paper.id); setError('')
    setEditing({...paper,collection_ids:add?[...paper.collection_ids,id]:paper.collection_ids.filter(x=>x!==id)})
    try {await api.membership(id,paper.id,add); await workspace.reload(); notify(t('saved'))}
    catch(e) {setEditing(paper);setError(errorMessage(e))} finally {setMutation('')}
  }
  const assigned = async (ids:string[], collection:Collection) => {
    await workspace.reload()
    const assignedIds=new Set(ids)
    setSelected(current=>current.filter(id=>!assignedIds.has(id)))
    notify(t('addedToCollection')+' '+collection.name)
  }
  useEffect(()=>{setSelected([]);setFocusedPaperId('')},[collectionId])
  const collection = workspace.collections.find(c => c.id === collectionId)
  const focusedPaper = workspace.papers.find(p => p.id === focusedPaperId)
  const aiCompleted = workspace.papers.filter(p => p.intelligence_status === 'completed').length
  const aiPending = workspace.papers.filter(p => ['queued','running','partial'].includes(p.intelligence_status ?? '')).length
  const aiLocalOnly = workspace.papers.filter(p => !p.intelligence_status || p.intelligence_status === 'unanalyzed').length
  const focusPaper = (paper:Paper) => setFocusedPaperId(paper.id)
  const refreshFocus = () => { if(focusedPaperId) setFocusedPaperId(workspace.papers.find(p=>p.id===focusedPaperId)?.id??'') }
  return <div className={'library-page ' + (dragging?'is-dragging':'')} onDragOver={e => {e.preventDefault(); setDragging(true)}} onDragLeave={e => {if(!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false)}} onDrop={e => {e.preventDefault();setDragging(false);prepareFiles(e.dataTransfer.files)}}>
    <section className="page-heading"><div><div className="eyebrow">RESEARCH LIBRARY</div><h1>{collection?.name ?? t('libraryTitle')}</h1><p>{collection?.description || t('librarySubtitle')}</p></div><div className="heading-actions">{collection&&<button className="btn secondary" onClick={()=>setAssignment({collectionId:collection.id})}><FolderPlus size={16}/>{t('addExistingPapers')}</button>}{!collectionId&&<button className="btn secondary" onClick={newCollection}><Plus size={16}/>{t('newCollection')}</button>}{collection&&<button className="btn secondary danger-action" onClick={()=>{setDeleteCollectionError('');setDeleteCollectionTarget(collection)}}><Trash2 size={16}/>{t('deleteCollection')}</button>}<button className="btn secondary" disabled={busy} onClick={()=>setUrlImport(true)}><Link2 size={16}/>{t('importUrl')}</button><button className="btn primary" disabled={busy || urlImport} onClick={() => inputRef.current?.click()}>{busy?<LoaderCircle className="spin" size={16}/>:<Upload size={16}/>} {t(busy?'importing':'import')}</button><input ref={inputRef} type="file" accept="application/pdf,.pdf" multiple hidden onChange={e=>{if(e.target.files)prepareFiles(e.target.files)}}/></div></section>
    {collection&&openResearch&&<nav className="library-research-tabs" aria-label="专题视图"><button className="is-selected" aria-current="page">文献</button><button onClick={()=>openResearch('essay')}>专题文章<ArrowUpRight size={13}/></button><button onClick={()=>openResearch('findings')}>研究线索<ArrowUpRight size={13}/></button></nav>}
    <div className="library-facts" aria-label={t('libraryFacts')}><span><strong>{workspace.papers.length}</strong> {t('paperCount')}</span><span><strong>{aiCompleted}</strong> {t('aiCount')}</span><span><strong>{aiPending}</strong> {t('analysisPending')}</span><span><strong>{aiLocalOnly}</strong> {t('localOnlyCount')}</span></div>
    <ResearchActivityHeatmap activity={activity} selectedDate={selectedActivityDate} loading={activityLoading} error={activityError} onSelect={date=>setSelectedActivityDate(current=>current===date?'':date)} onClear={()=>setSelectedActivityDate('')}/>
    {workspace.papers.some(p=>p.is_demo) && <p className="sample-notice"><span className="demo-badge">DEMO</span>{t('demoNotice')}</p>}
    {error && <ErrorBanner error={error}/>}
    {(busy || outcomes.length>0) && <div className="import-report" role="status"><strong>{t('batchResult')}</strong>{busy&&<button className="text-btn" onClick={()=>{importStopped.current=true}}>{t('cancelBatch')}</button>}{progress && <p><LoaderCircle className="spin" size={13}/>{progress}</p>}{outcomes.map((item,i)=><div key={i} className={item.ok?'import-ok':'import-failed'}>{item.ok?<CheckCircle2 size={14}/>:<X size={14}/>}<span>{item.name}</span><small>{item.message}</small></div>)}</div>}
    <div className="library-toolbar library-controls"><label className="search-field"><Search size={16}/><input value={query} onChange={e=>{setQuery(e.target.value);setFocusedPaperId('')}} placeholder={t('search')} aria-label={t('search')}/></label><select aria-label={t('aiState')} value={aiFilter} onChange={e=>{setAiFilter(e.target.value);setFocusedPaperId('')}}><option value="">{t('aiAll')}</option>{Object.entries(intelligenceKeys).map(([value,key])=><option key={value} value={value}>{t(key)}</option>)}</select><select aria-label={t('status')} value={status} onChange={e=>{setStatus(e.target.value);setFocusedPaperId('')}}><option value="">{t('allStatus')}</option>{statuses.map(s=><option key={s} value={s}>{t(s)}</option>)}</select><button className={'btn secondary ' + (favorite?'selected':'')} onClick={()=>{setFavorite(!favorite);setFocusedPaperId('')}}><Bookmark size={14}/>{t('favoritesOnly')}</button><select aria-label={t('title')} value={sort} onChange={e=>{setSort(e.target.value);setFocusedPaperId('')}}><option value="recent">{t('recent')}</option><option value="year">{t('year')}</option><option value="title">{t('title')}</option></select></div>
    {workspace.taskError&&<ErrorBanner error={workspace.taskError}/>}<div className="batch-analysis-bar"><label><input type="checkbox" aria-label={t('selectAll')} checked={filtered.filter(p=>!p.is_demo).length>0&&filtered.filter(p=>!p.is_demo).every(p=>selected.includes(p.id))} onChange={e=>setSelected(e.target.checked?filtered.filter(p=>!p.is_demo).map(p=>p.id):[])}/><span>{selected.length?`${selected.length} ${t('selectedCount')}`:t('notSelected')}</span></label><button className="btn secondary collection-add-action" disabled={!selected.length} onClick={()=>setAssignment({paperIds:[...selected]})}><FolderPlus size={15}/>{t('addToCollection')}</button><button className="btn secondary" disabled={!enabled||!selected.length||analysisBusy} onClick={()=>void analyzeSelected()}><BookOpen size={14}/>{t('analyzeSelected')}</button>{selected.length>0&&<button className="text-btn" onClick={()=>setSelected([])}>{t('clearSelection')}</button>}<small>{t(enabled?'aiLocalHint':'analysisUnavailable')}</small></div><div className="paper-table"><div className="paper-table-head"><span>{t('paper')}</span><span>{t('status')}</span><span>{t('year')}</span><span>{t('collections')}</span><button className="btn secondary paper-batch-delete danger-action" disabled={!selected.length||selected.length>100||deleting||analysisBusy} title={t('deleteBatchLimit')} onClick={()=>requestDelete(workspace.papers.filter(p=>selected.includes(p.id)))}><Trash2 size={14}/>{t('batchDelete')}</button></div>{filtered.map(paper=><article className={'paper-row '+(focusedPaperId===paper.id?'focused':'')} key={paper.id} onClick={e=>{if(e.target instanceof HTMLElement && e.target.closest('button,select,input'))return;focusPaper(paper)}}><div className="paper-main">{!paper.is_demo&&<input className="paper-select" type="checkbox" aria-label={paper.title+' '+t('selectPaper')} checked={selected.includes(paper.id)} onChange={e=>setSelected(current=>e.target.checked?[...current,paper.id]:current.filter(id=>id!==paper.id))}/>}<div className="paper-icon"><FileText size={20} strokeWidth={1.5}/></div><div className="paper-name"><button onClick={()=>openPaper(paper.id)}>{paper.title}</button><p>{paper.authors.join(', ') || t('unknown')}<span> · </span>{paper.venue || t('unknown')}{paper.is_demo && <span className="demo-badge">{t('demo')}</span>}</p><div className="paper-intelligence"><AnalysisBadge paper={paper}/>{isActiveTask(paper.intelligence_status)&&paper.intelligence_task&&<><small>{paper.intelligence_task.completed_steps} / {paper.intelligence_task.total_steps}</small><button className="text-btn" onClick={()=>void cancelTask(paper.intelligence_task!.id)}>{t('cancelTask')}</button></>}{!paper.intelligence_status||paper.intelligence_status==='unanalyzed'?<small>{t('localExtractOnly')}</small>:null}</div><div className="paper-tags">{paper.tags.map(tag=><span key={tag}>{tag}</span>)}<button className="paper-edit-tags" aria-label={paper.title+' '+t('editTags')} onClick={()=>{setEditing(paper);setTags(paper.tags.join(', '))}}><Tag size={11}/>{t('editTags')}</button></div></div></div><select className={'status-select status-'+paper.reading_status} value={paper.reading_status} disabled={mutation===paper.id} aria-label={paper.title+' '+t('status')} onChange={e=>void update(paper,{reading_status:e.target.value as ReadingStatus})}>{statuses.map(s=><option value={s} key={s}>{t(s)}</option>)}</select><span className="paper-year">{paper.year ?? '—'}</span><button className={'collection-summary '+(!paper.collection_ids.length?'is-empty':'')} aria-label={paper.title+' '+t(paper.collection_ids.length?'manageCollections':'addToCollection')} onClick={()=>{if(!paper.collection_ids.length)setAssignment({paperIds:[paper.id]});else{setEditing(paper);setTags(paper.tags.join(', '))}}} title={t(paper.collection_ids.length?'manageCollections':'addToCollection')}><FolderPlus size={14}/><span>{paper.collection_ids.map(id=>workspace.collections.find(c=>c.id===id)?.name).filter(Boolean).join(', ') || t('addToCollection')}</span></button><div className="row-actions"><button className="icon-btn" aria-label={paper.title+' '+t('paperMetadata')} title={t('paperMetadata')} onClick={()=>setMetadataPaper(paper)}><Info size={16}/></button><button className={'icon-btn '+(paper.is_favorite?'bookmarked':'')} aria-label={paper.title+' '+t('favorite')} disabled={mutation===paper.id} onClick={()=>void update(paper,{is_favorite:!paper.is_favorite})}><Bookmark size={16} fill={paper.is_favorite?'currentColor':'none'}/></button><button className="icon-btn" aria-label={t('open')} onClick={()=>openPaper(paper.id)}><ArrowUpRight size={17}/></button><button className="icon-btn danger-action" aria-label={paper.title+' '+t('deletePaper')} title={t('deletePaper')} disabled={deleting||mutation===paper.id||analysisBusy} onClick={()=>requestDelete([paper])}><Trash2 size={16}/></button></div></article>)}{filtered.length===0 && <Empty title={t(!workspace.papers.length?'libraryEmpty':collectionId?'collectionEmpty':'searchEmpty')} text={t(selectedActivityDate?'activityNoPaperHint':'emptyHint')}><button className="text-btn" onClick={()=>{setQuery('');setStatus('');setAiFilter('');setFavorite(false);setSelectedActivityDate('')}}>{t('clearFilters')}</button></Empty>}</div>
    {focusedPaper && <section className="library-selection-detail" aria-label={t('paperDetails')}><div className="selection-detail-main"><div className="eyebrow">{t('selectedPaper')}</div><h2>{focusedPaper.title}</h2><p>{focusedPaper.authors.join(', ') || t('unknown')} · {focusedPaper.venue || t('unknown')} · {focusedPaper.year ?? '—'}</p><div className="selection-detail-meta"><span>{t(focusedPaper.intelligence_status==='completed'?'aiCompleted':focusedPaper.intelligence_status==='failed'?'aiFailed':focusedPaper.intelligence_status==='partial'?'aiPartial':'localExtractOnly')}</span><span>{focusedPaper.page_count ? `${focusedPaper.page_count} ${t('page')}` : t('pageCountUnknown')}</span><span>{focusedPaper.metadata_warnings?.length ? t('metadataPartial') : t('metadataVerified')}</span></div></div><div className="selection-detail-actions"><button className="btn secondary" onClick={()=>setAssignment({paperIds:[focusedPaper.id]})}><FolderPlus size={15}/>{t('addToCollection')}</button><button className="btn primary" onClick={()=>openPaper(focusedPaper.id)}>{t('openReader')}</button><button className="btn secondary" onClick={()=>openPaper(focusedPaper.id)}>{t('viewCard')}</button><button className="text-btn" disabled={!enabled||analysisBusy||focusedPaper.is_demo} onClick={()=>void workspace.queueAnalysis([focusedPaper.id],true).then(refreshFocus)}>{t('analysisRetry')}</button></div></section>}
    {searchError&&<ErrorBanner error={searchError}/>}
    {hits.length>0&&<section className="fulltext-results"><h2>{t('fulltextMatches')}</h2>{hits.filter(hit=>workspace.papers.some(p=>p.id===hit.paper_id&&(!collectionId||p.collection_ids.includes(collectionId)))).map(hit=><button key={hit.chunk_id} className="fulltext-hit" onClick={()=>openPaper(hit.paper_id,{page:hit.page,source_text:hit.content})}><strong>{hit.title}</strong><span>{t('page')} {hit.page} · {hit.section}</span><p>{hit.content}</p><small>{t('viewSource')}</small></button>)}</section>}
    <div className="drop-hint"><Upload size={14}/>{t('importHint')} · PDF · 50 MB</div>
    {pendingFiles.length>0&&<ImportFilesDialog files={pendingFiles} settings={workspace.settings} close={()=>setPendingFiles([])} confirm={analyze=>void importFiles(pendingFiles,analyze)}/>}
    {urlImport && <ImportUrlDialog settings={workspace.settings} close={()=>setUrlImport(false)} openPaper={openPaper} retryLabel={t(collectionId?'retryAddCollection':'retry')} imported={async paper=>{try{if(collectionId)await api.membership(collectionId,paper.id,true)}finally{await workspace.reload();void refreshActivity()}void recordResearchActivity('imports',paper.id);notify(t('importDone'))}}/>}
    {assignment && <AddToCollectionDialog papers={workspace.papers} collections={workspace.collections} {...assignment} close={()=>setAssignment(null)} saved={assigned} createCollection={!collectionId?newCollection:undefined}/>}
    {metadataPaper && <MetadataDialog paper={metadataPaper} close={()=>setMetadataPaper(null)} saved={workspace.reload}/>}
    {deleteCollectionTarget&&<Modal title={t('deleteCollection')} close={()=>{if(!collectionDeletionBusy.current)setDeleteCollectionTarget(null)}}><p>{t('deleteCollectionPrompt').replace('{name}',()=>deleteCollectionTarget.name)}</p><div className="delete-scope-hint">{t('deleteCollectionScope')}</div>{deleteCollectionError&&<ErrorBanner error={deleteCollectionError}/>}<div className="modal-actions"><button className="btn secondary" disabled={deletingCollection} onClick={()=>setDeleteCollectionTarget(null)}>{t('cancel')}</button><button className="btn primary danger-confirm" disabled={deletingCollection} onClick={()=>void confirmDeleteCollection()}>{deletingCollection&&<LoaderCircle size={15} className="spin"/>}{t('confirmDeleteCollection')}</button></div></Modal>}
    {deleteTargets.length>0&&<Modal title={t(deleteTargets.length>1?'batchDelete':'deletePaper')} close={()=>{if(!deleting)setDeleteTargets([])}}><p>{deleteTargets.length===1?t('deletePaperPrompt').replace('{title}',()=>deleteTargets[0].title):t('deletePapersPrompt').replace('{count}',String(deleteTargets.length))}</p>{deleteTargets.length>1&&<ul className="delete-paper-list">{deleteTargets.map(paper=><li key={paper.id}>{paper.title}</li>)}</ul>}<div className="delete-scope-hint">{t('deletePaperScope')}</div>{deleteError&&<ErrorBanner error={deleteError}/>}<div className="modal-actions"><button className="btn secondary" disabled={deleting} onClick={()=>setDeleteTargets([])}>{t('cancel')}</button><button className="btn primary danger-confirm" disabled={deleting} onClick={()=>void confirmDelete()}>{deleting?<LoaderCircle size={15} className="spin"/>:<Trash2 size={15}/>} {t(deleting?'deletingPapers':'confirmDeletePapers')}</button></div></Modal>}
    {editing && <Modal title={t('manageCollections')} close={()=>setEditing(null)}><p className="muted">{editing.title}</p><div className="membership-list">{workspace.collections.map(c=><label key={c.id}><input type="checkbox" checked={editing.collection_ids.includes(c.id)} disabled={mutation===editing.id} onChange={e=>void membership(editing,c.id,e.target.checked)}/><span>{c.name}</span></label>)}</div>{!workspace.collections.length && <Empty title={t('noCollections')}/>}<label>{t('editTags')}<input aria-label={t('tags')} value={tags} onChange={e=>setTags(e.target.value)} placeholder={t('tagPlaceholder')}/></label><div className="modal-actions"><button className="btn primary" disabled={!!mutation} onClick={async()=>{await update(editing,{tags:[...new Set(tags.split(/[,，]/).map(s=>s.trim()).filter(Boolean))]});setEditing(null)}}><Tag size={14}/>{t('save')}</button></div></Modal>}
  </div>
}
