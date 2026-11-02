import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, CheckCheck, LoaderCircle, RotateCcw, Search, X } from 'lucide-react'
import type { KnowledgeCandidate, KnowledgePaper } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi, type LocaleKey } from '../lib/i18n'
import { statusLabel } from '../lib/knowledgeLabels'
import { intakeGroup, intakeGroups, readingOrder, reviewCounts, reviewMatches, type ReviewFilter } from '../lib/knowledgeReview'
import { KnowledgeRelationCard } from './KnowledgeRelationCard'
import { KnowledgeCandidateCard, type CandidateEdits } from './KnowledgeCandidateCard'
import { KnowledgeEntityDossier } from './KnowledgeEntityDossier'
import { Empty, ErrorBanner } from './Shared'
import type { PdfLocator } from './PdfViewer'
import './knowledge-curation.css'
import './knowledge-intake.css'

const filterLabels:Record<ReviewFilter,LocaleKey>={pending:'kReviewPending',settled:'kIntakeSettled',ignored:'kReviewIgnored'}
export function KnowledgePanel({paperId,active,locate,paragraphId,openPaper}:{paperId:string;active:boolean;locate:(locator:PdfLocator)=>void;paragraphId?:string|null;openPaper:(id:string,locator?:PdfLocator)=>void}) {
  const {t}=useUi()
  const [data,setData]=useState<KnowledgePaper|null>(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [busy,setBusy]=useState('')
  const [view,setView]=useState<'objects'|'relations'>('objects')
  const [filter,setFilter]=useState<ReviewFilter>('pending')
  const [query,setQuery]=useState('')
  const [selection,setSelection]=useState<string[]>([])
  const [entity,setEntity]=useState<{id:string;name:string}|null>(null)
  const loadVersion=useRef(0)
  const scope=useRef(0)
  const scopeKey=useRef(`${paperId}:${active}`);scopeKey.current=`${paperId}:${active}`
  const load=useCallback(async()=>{
    const version=++loadVersion.current,currentKey=`${paperId}:${active}`
    if(scopeKey.current!==currentKey)return
    setLoading(true);setError('')
    try{const value=await api.paperKnowledge(paperId);if(version===loadVersion.current&&scopeKey.current===currentKey)setData(value)}
    catch(e){if(version===loadVersion.current&&scopeKey.current===currentKey)setError(errorMessage(e))}
    finally{if(version===loadVersion.current&&scopeKey.current===currentKey)setLoading(false)}
  },[paperId,active])
  useEffect(()=>{
    scope.current++;setData(null);setBusy('');setError('');setNotice('');setSelection([]);setQuery('');setFilter('pending');setView('objects');setEntity(null)
    if(active)void load()
    return()=>{loadVersion.current++;scope.current++}
  },[active,load])
  const rows=view==='objects'?data?.candidates??[]:data?.relations??[]
  const counts=reviewCounts(rows)
  const candidates=useMemo(()=>data?.candidates.filter(item=>reviewMatches(item,filter,query)).sort(readingOrder)??[],[data,filter,query])
  const relations=data?.relations.filter(item=>reviewMatches(item,filter,query))??[]
  const selectable=candidates.filter(item=>!['confirmed','known','alias','rejected'].includes(item.status))
  const visibleSelection=selection.filter(id=>selectable.some(row=>row.id===id))
  const allSelected=selectable.length>0&&selectable.every(item=>selection.includes(item.id))
  const selectEntity=(id:string,name:string)=>setEntity({id,name})
  const navigate=(id:string,locator?:PdfLocator)=>{setEntity(null);if(id===paperId&&locator)locate(locator);else openPaper(id,locator)}
  const perform=async(key:string,action:()=>Promise<KnowledgePaper|void>)=>{
    if(busy)return false
    const version=scope.current,currentKey=`${paperId}:${active}`
    const current=()=>version===scope.current&&scopeKey.current===currentKey
    loadVersion.current++;setLoading(false)
    setBusy(key);setError('');setNotice('')
    try{
      const value=await action()
      if(current()){
        if(value){loadVersion.current++;setLoading(false);setData(value)}else await load()
        setSelection([])
      }
      return current()
    }catch(e){if(current())setError(errorMessage(e));return false}
    finally{if(current())setBusy('')}
  }
  const decide=(item:KnowledgeCandidate,decision:'confirm'|'reject',edits?:CandidateEdits)=>perform(item.id,async()=>{
    if(decision==='confirm')await api.confirmKnowledgeCandidate(item.id,edits)
    else await api.rejectKnowledgeCandidate(item.id)
  })
  const extract=()=>perform('paragraph',async()=>{
    if(!paragraphId)return
    return api.extractKnowledgeParagraph(paperId,paragraphId)
  }).then(ok=>{if(ok&&scopeKey.current===`${paperId}:${active}`)setNotice(t('kParagraphChecked'))})
  return <section className="knowledge-panel intake-panel" aria-label={t('knowledge')}>
    <header className="intake-heading"><div><h3>{t('knowledge')}</h3><p>{data?<span className={`intake-paper-state state-${data.paper_status}`}>{t(statusLabel(data.paper_status))}</span>:t('knowledgeHint')}</p></div><button className="icon-btn" aria-label={t('refresh')} onClick={()=>void load()} disabled={loading||!!busy}><RotateCcw size={15} className={loading?'spin':''}/></button></header>
    {error&&<ErrorBanner error={error}/>}
    {notice&&<p className="intake-notice" role="status"><Check size={13}/>{notice}</p>}
    {loading&&!data?<div className="knowledge-loading"><LoaderCircle size={16} className="spin"/>{t('loading')}</div>:!data?<Empty title={t('knowledgeEmpty')} text={t('knowledgeEmptyHint')}/>:<>
      {paragraphId&&<div className="intake-summary"><button className="text-btn" disabled={!!busy||loading} onClick={()=>void extract()}>{busy==='paragraph'&&<LoaderCircle size={13} className="spin"/>}{t('identifyParagraph')}</button></div>}
      <div className="intake-view-switch" role="tablist" aria-label={t('kIntakeViews')}>{(['objects','relations'] as const).map(value=><button key={value} role="tab" aria-selected={view===value} onClick={()=>{setView(value);setSelection([])}}>{t(value==='objects'?'kIntakeObjects':'dossierRelations')}<span>{value==='objects'?data.candidates.length:data.relations.length}</span></button>)}</div>
      {!data.candidates.length&&!data.relations.length?<Empty title={t('knowledgeEmpty')} text={t('knowledgeEmptyHint')}/>:<>
        <div className="intake-filters" aria-label={t('kReviewState')}>{(['pending','settled','ignored'] as const).map(value=><button key={value} aria-pressed={filter===value} onClick={()=>{setFilter(value);setSelection([])}}>{t(filterLabels[value])}<span>{counts[value]}</span></button>)}</div>
        <label className="intake-search"><Search size={14}/><input type="search" aria-label={t('kSearchIntake')} placeholder={t('kSearchIntake')} value={query} onChange={e=>{setQuery(e.target.value);setSelection([])}}/>{query&&<button className="icon-btn" aria-label={t('clear')} onClick={()=>{setQuery('');setSelection([])}}><X size={13}/></button>}</label>
        {view==='relations'&&filter==='pending'&&<p className="intake-help">{t('kReviewEndpointsFirst')}</p>}
        {view==='objects'&&filter==='pending'&&selectable.length>0&&<div className="intake-selection-bar"><label><input type="checkbox" checked={allSelected} disabled={!!busy} onChange={e=>setSelection(e.target.checked?selectable.map(item=>item.id):[])}/>{t('kSelectVisible')}</label>{visibleSelection.length>0&&<div><span>{visibleSelection.length} {t('selected')}</span><button className="text-btn intake-confirm" disabled={!!busy} onClick={()=>void perform('batch',()=>api.reviewKnowledgeCandidates(paperId,visibleSelection,'confirm'))}><CheckCheck size={13}/>{t('kConfirmSelected')}</button><button className="text-btn" disabled={!!busy} onClick={()=>void perform('batch',()=>api.reviewKnowledgeCandidates(paperId,visibleSelection,'reject'))}>{t('kIgnoreSelected')}</button></div>}</div>}
        {view==='objects'?intakeGroups.map(group=>{const items=candidates.filter(item=>intakeGroup(item)===group);return items.length?<section className="intake-group" key={group}><h4>{t(`kIntakeGroup_${group}` as LocaleKey)}<span>{items.length}</span></h4>{items.map(item=><KnowledgeCandidateCard key={item.id} item={item} busy={!!busy} saving={busy===item.id} selected={selection.includes(item.id)} onSelect={checked=>setSelection(ids=>checked?[...ids,item.id]:ids.filter(id=>id!==item.id))} onDecide={(decision,edits)=>decide(item,decision,edits)} onEntitySelect={selectEntity} onLocate={e=>locate({page:e.page??1,bbox:e.bbox,page_width:e.page_width,page_height:e.page_height,source_text:e.quote})}/>)}</section>:null}):relations.map(item=><KnowledgeRelationCard key={item.id} relation={item} openPaper={navigate} onChange={()=>void load()} onEntitySelect={selectEntity}/>)}
        {(view==='objects'?candidates.length===0:relations.length===0)&&<div className="intake-empty"><CheckCheck size={22} strokeWidth={1.3}/><strong>{query?t('kIntakeNoMatch'):filter==='pending'?t('kIntakeReviewed'):t('kIntakeNoItems')}</strong><p>{query?t('kIntakeSearchHint'):filter==='pending'?t('kIntakeReviewedHint'):t('kIntakeFilterHint')}</p>{filter==='pending'&&counts.settled>0&&!query&&<button className="text-btn" onClick={()=>setFilter('settled')}>{t('kViewSettled')}</button>}</div>}
      </>}
    </>}
    {entity&&<KnowledgeEntityDossier entityId={entity.id} entityName={entity.name} onClose={()=>setEntity(null)} onSelectEntity={selectEntity} onChanged={()=>void load()} openPaper={navigate}/>}
  </section>
}
