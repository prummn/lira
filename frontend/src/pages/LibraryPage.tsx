import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUpRight, Bookmark, CheckCircle2, FileText, FolderPlus, Info, Link2, LoaderCircle, Plus, Search, Tag, Upload, X } from 'lucide-react'
import type { Paper, ReadingStatus, SearchHit } from '../types'
import type { PdfLocator } from '../components/PdfViewer'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import type { Workspace } from '../lib/useWorkspace'
import { Empty, ErrorBanner, Modal } from '../components/Shared'
import { ImportUrlDialog } from '../components/ImportUrlDialog'
import { MetadataDialog } from '../components/MetadataDialog'

export const statuses: ReadingStatus[] = ['unread','skimming','reading','read','important']
export function LibraryPage({ workspace, collectionId, query, setQuery, openPaper, newCollection, notify }: {workspace:Workspace;collectionId:string;query:string;setQuery:(value:string)=>void;openPaper:(id:string,locator?:PdfLocator)=>void;newCollection:()=>void;notify:(message:string)=>void}) {
  const {t} = useUi()
  const [status, setStatus] = useState('')
  const [favorite, setFavorite] = useState(false)
  const [sort, setSort] = useState('recent')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState('')
  const [outcomes, setOutcomes] = useState<{name:string;ok:boolean;message:string}[]>([])
  const [editing, setEditing] = useState<Paper|null>(null)
  const [tags, setTags] = useState('')
  const [mutation, setMutation] = useState('')
  const [hits,setHits] = useState<SearchHit[]>([])
  const [searchError,setSearchError] = useState('')
  const [urlImport,setUrlImport] = useState(false)
  const [metadataPaper,setMetadataPaper] = useState<Paper|null>(null)
  useEffect(()=>{
    let active=true;setHits([]);setSearchError('')
    if(query.trim().length<2)return
    const timer=setTimeout(()=>{api.search(query.trim(),collectionId).then(data=>{if(active)setHits(data.items)}).catch(e=>{if(active)setSearchError(errorMessage(e))})},300)
    return()=>{active=false;clearTimeout(timer)}
  },[query,collectionId])
  const inputRef = useRef<HTMLInputElement>(null)
  const filtered = useMemo(() => {
    const items = workspace.papers.filter(p => (!collectionId || p.collection_ids.includes(collectionId)) && (!status || p.reading_status === status) && (!favorite || p.is_favorite) && (p.title + ' ' + p.authors.join(' ') + ' ' + p.tags.join(' ') + ' ' + (p.venue ?? '')).toLowerCase().includes(query.toLowerCase()))
    return sort === 'year' ? items.sort((a,b)=>(b.year ?? 0)-(a.year ?? 0)) : sort === 'title' ? items.sort((a,b)=>a.title.localeCompare(b.title)) : items
  }, [workspace.papers,collectionId,status,favorite,query,sort])
  const importFiles = async (files: FileList | File[]) => {
    if(busy || urlImport) return
    setBusy(true); setError(''); setOutcomes([])
    const results: typeof outcomes = []
    const batch = Array.from(files)
    for(let i=0;i<batch.length;i++) {
      const file = batch[i]; setProgress(String(i+1) + ' / ' + batch.length + ' · ' + file.name)
      try { const paper = await api.import(file); if(collectionId) await api.membership(collectionId,paper.id,true); results.push({name:file.name,ok:true,message:t('importDone')}) }
      catch(e) { results.push({name:file.name,ok:false,message:errorMessage(e)}) }
      setOutcomes([...results])
    }
    await workspace.reload(); setBusy(false); setProgress('')
    if(inputRef.current) inputRef.current.value = ''
  }
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
  const collection = workspace.collections.find(c => c.id === collectionId)
  return <div className={'library-page ' + (dragging?'is-dragging':'')} onDragOver={e => {e.preventDefault(); setDragging(true)}} onDragLeave={e => {if(!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false)}} onDrop={e => {e.preventDefault();setDragging(false);void importFiles(e.dataTransfer.files)}}>
    <section className="page-heading"><div><div className="eyebrow">RESEARCH LIBRARY</div><h1>{collection?.name ?? t('libraryTitle')}</h1><p>{collection?.description || t('librarySubtitle')}</p></div><div className="heading-actions"><button className="btn secondary" onClick={newCollection}><Plus size={16}/>{t('newCollection')}</button><button className="btn secondary" disabled={busy} onClick={()=>setUrlImport(true)}><Link2 size={16}/>{t('importUrl')}</button><button className="btn primary" disabled={busy || urlImport} onClick={() => inputRef.current?.click()}>{busy?<LoaderCircle className="spin" size={16}/>:<Upload size={16}/>} {t(busy?'importing':'import')}</button><input ref={inputRef} type="file" accept="application/pdf,.pdf" multiple hidden onChange={e=>{if(e.target.files)void importFiles(e.target.files)}}/></div></section>
    <div className="library-stats">{[[workspace.papers.length,'paperCount'],[workspace.papers.filter(p=>['reading','skimming'].includes(p.reading_status)).length,'readingCount'],[workspace.papers.filter(p=>p.analysis_status==='ready').length,'analyzedCount'],[workspace.papers.filter(p=>p.is_favorite).length,'savedCount']].map(([value,label])=><div key={label}><strong>{value}</strong><span>{t(label as 'paperCount')}</span></div>)}</div>
    {workspace.papers.some(p=>p.is_demo) && <p className="sample-notice"><span className="demo-badge">DEMO</span>{t('demoNotice')}</p>}
    {error && <ErrorBanner error={error}/>}
    {(busy || outcomes.length>0) && <div className="import-report" role="status"><strong>{t('batchResult')}</strong>{progress && <p><LoaderCircle className="spin" size={13}/>{progress}</p>}{outcomes.map((item,i)=><div key={i} className={item.ok?'import-ok':'import-failed'}>{item.ok?<CheckCircle2 size={14}/>:<X size={14}/>}<span>{item.name}</span><small>{item.message}</small></div>)}</div>}
    <div className="library-controls"><label className="search-field"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={t('search')} aria-label={t('search')}/></label><select aria-label={t('status')} value={status} onChange={e=>setStatus(e.target.value)}><option value="">{t('allStatus')}</option>{statuses.map(s=><option key={s} value={s}>{t(s)}</option>)}</select><button className={'btn secondary ' + (favorite?'selected':'')} onClick={()=>setFavorite(!favorite)}><Bookmark size={14}/>{t('favoritesOnly')}</button><select aria-label={t('title')} value={sort} onChange={e=>setSort(e.target.value)}><option value="recent">{t('recent')}</option><option value="year">{t('year')}</option><option value="title">{t('title')}</option></select></div>
    <div className="paper-table"><div className="paper-table-head"><span>{t('paper')}</span><span>{t('status')}</span><span>{t('year')}</span><span>{t('collections')}</span><span/></div>{filtered.map(paper=><article className="paper-row" key={paper.id}><div className="paper-main"><div className="paper-icon"><FileText size={20} strokeWidth={1.5}/></div><div className="paper-name"><button onClick={()=>openPaper(paper.id)}>{paper.title}</button><p>{paper.authors.join(', ') || t('unknown')}<span> · </span>{paper.venue || t('unknown')}{paper.is_demo && <span className="demo-badge">{t('demo')}</span>}</p><div className="paper-tags">{paper.tags.map(tag=><span key={tag}>{tag}</span>)}</div></div></div><select className={'status-select status-'+paper.reading_status} value={paper.reading_status} disabled={mutation===paper.id} aria-label={paper.title+' '+t('status')} onChange={e=>void update(paper,{reading_status:e.target.value as ReadingStatus})}>{statuses.map(s=><option value={s} key={s}>{t(s)}</option>)}</select><span className="paper-year">{paper.year ?? '—'}</span><button className="collection-summary" onClick={()=>{setEditing(paper);setTags(paper.tags.join(', '))}} title={t('manageCollections')}><FolderPlus size={14}/><span>{paper.collection_ids.map(id=>workspace.collections.find(c=>c.id===id)?.name).filter(Boolean).join(', ') || '—'}</span></button><div className="row-actions"><button className="icon-btn" aria-label={paper.title+' '+t('paperMetadata')} title={t('paperMetadata')} onClick={()=>setMetadataPaper(paper)}><Info size={16}/></button><button className={'icon-btn '+(paper.is_favorite?'bookmarked':'')} aria-label={paper.title+' '+t('favorite')} disabled={mutation===paper.id} onClick={()=>void update(paper,{is_favorite:!paper.is_favorite})}><Bookmark size={16} fill={paper.is_favorite?'currentColor':'none'}/></button><button className="icon-btn" aria-label={t('open')} onClick={()=>openPaper(paper.id)}><ArrowUpRight size={17}/></button></div></article>)}{filtered.length===0 && <Empty title={t(!workspace.papers.length?'libraryEmpty':collectionId?'collectionEmpty':'searchEmpty')} text={t('emptyHint')}><button className="text-btn" onClick={()=>{setQuery('');setStatus('');setFavorite(false)}}>{t('clearFilters')}</button></Empty>}</div>
    {searchError&&<ErrorBanner error={searchError}/>}
    {hits.length>0&&<section className="fulltext-results"><h2>{t('fulltextMatches')}</h2>{hits.filter(hit=>!collectionId||workspace.papers.find(p=>p.id===hit.paper_id)?.collection_ids.includes(collectionId)).map(hit=><button key={hit.chunk_id} className="fulltext-hit" onClick={()=>openPaper(hit.paper_id,{page:hit.page,source_text:hit.content})}><strong>{hit.title}</strong><span>{t('page')} {hit.page} · {hit.section}</span><p>{hit.content}</p><small>{t('viewSource')}</small></button>)}</section>}
    <div className="drop-hint"><Upload size={14}/>{t('importHint')} · PDF · 50 MB</div>
    {urlImport && <ImportUrlDialog close={()=>setUrlImport(false)} openPaper={openPaper} retryLabel={t(collectionId?'retryAddCollection':'retry')} imported={async paper=>{try{if(collectionId)await api.membership(collectionId,paper.id,true)}finally{await workspace.reload()}notify(t('importDone'))}}/>}
    {metadataPaper && <MetadataDialog paper={metadataPaper} close={()=>setMetadataPaper(null)} saved={workspace.reload}/>}
    {editing && <Modal title={t('manageCollections')} close={()=>setEditing(null)}><p className="muted">{editing.title}</p><div className="membership-list">{workspace.collections.map(c=><label key={c.id}><input type="checkbox" checked={editing.collection_ids.includes(c.id)} disabled={mutation===editing.id} onChange={e=>void membership(editing,c.id,e.target.checked)}/><span>{c.name}</span></label>)}</div>{!workspace.collections.length && <Empty title={t('noCollections')}/>}<label>{t('editTags')}<input aria-label={t('tags')} value={tags} onChange={e=>setTags(e.target.value)} placeholder={t('tagPlaceholder')}/></label><div className="modal-actions"><button className="btn primary" disabled={!!mutation} onClick={async()=>{await update(editing,{tags:[...new Set(tags.split(/[,，]/).map(s=>s.trim()).filter(Boolean))]});setEditing(null)}}><Tag size={14}/>{t('save')}</button></div></Modal>}
  </div>
}
