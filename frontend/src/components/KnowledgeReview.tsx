import { useEffect, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import type { KnowledgeCandidate, KnowledgeRelation, Paper } from '../types'
import type { PdfLocator } from './PdfViewer'
import { KnowledgeRelationCard } from './KnowledgeRelationCard'
import { KnowledgeCandidateCard, type CandidateEdits } from './KnowledgeCandidateCard'
import { readingOrder, reviewCounts, reviewMatches, type ReviewFilter } from '../lib/knowledgeReview'
import './knowledge-intake.css'

export function KnowledgeReview({candidates,relations,papers,openPaper,onChanged,onSelectEntity}: {
  candidates:KnowledgeCandidate[]; relations:KnowledgeRelation[]; papers:Paper[]
  openPaper:(id:string,locator?:PdfLocator)=>void; onChanged:()=>void; onSelectEntity:(id:string,name:string)=>void
}) {
  const {t}=useUi()
  const [tab,setTab]=useState<'objects'|'relations'>('objects')
  const [filter,setFilter]=useState<ReviewFilter>('pending')
  const [paperId,setPaperId]=useState('')
  const [query,setQuery]=useState('')
  const [busy,setBusy]=useState('')
  const [error,setError]=useState('')
  const paperKey=papers.map(p=>p.id).join(',')
  const activeScope=useRef(paperKey);activeScope.current=paperKey
  const mounted=useRef(true)
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
  useEffect(()=>{setPaperId('');setQuery('');setError('');setBusy('')},[paperKey])
  const scopedCandidates=candidates.filter(row=>!paperId||row.paper_id===paperId)
  const scopedRelations=relations.filter(row=>!paperId||row.paper_id===paperId)
  const pendingCandidates=reviewCounts(scopedCandidates).pending
  const pendingRelations=reviewCounts(scopedRelations).pending
  const counts=reviewCounts(tab==='objects'?scopedCandidates:scopedRelations)
  const items=scopedCandidates.filter(row=>reviewMatches(row,filter,query)).sort(readingOrder)
  const relationItems=scopedRelations.filter(row=>reviewMatches(row,filter,query))
  const sourcePapers=papers.filter(p=>candidates.some(c=>c.paper_id===p.id)||relations.some(r=>r.paper_id===p.id))
  const decide=async(item:KnowledgeCandidate,decision:'confirm'|'reject',edits?:CandidateEdits)=>{
    if(busy)return false
    const current=()=>mounted.current&&activeScope.current===paperKey
    setBusy(item.id);setError('')
    try{
      if(decision==='confirm')await api.confirmKnowledgeCandidate(item.id,edits)
      else await api.rejectKnowledgeCandidate(item.id)
      if(current())onChanged()
      return true
    }catch(e){if(current())setError(errorMessage(e));return false}
    finally{if(current())setBusy('')}
  }
  return <section className="knowledge-inbox-curation intake-inbox">
    <header><button className={tab==='objects'?'active':''} onClick={()=>setTab('objects')}>{t('kObjectReview')} <span>{pendingCandidates}</span></button><button className={tab==='relations'?'active':''} onClick={()=>setTab('relations')}>{t('kRelationReview')} <span>{pendingRelations}</span></button></header>
    <div className="intake-inbox-tools"><label className="intake-search"><Search size={15}/><input type="search" aria-label={t('kSearchIntake')} placeholder={t('kSearchIntake')} value={query} onChange={e=>setQuery(e.target.value)}/></label><select aria-label={t('kSourceFilter')} value={paperId} onChange={e=>setPaperId(e.target.value)}><option value="">{t('allPapers')}</option>{sourcePapers.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></div>
    <div className="intake-filters">{(['pending','settled','ignored'] as const).map(value=><button key={value} aria-pressed={filter===value} onClick={()=>setFilter(value)}>{t(value==='pending'?'kReviewPending':value==='settled'?'kIntakeSettled':'kReviewIgnored')}<span>{counts[value]}</span></button>)}</div>
    {tab==='relations'&&filter==='pending'&&<p className="intake-help">{t('kReviewEndpointsFirst')}</p>}
    {error&&<p className="dossier-error" role="alert">{error}</p>}
    {tab==='relations'?relationItems.map(relation=><KnowledgeRelationCard key={relation.id} relation={relation} paperTitle={papers.find(p=>p.id===relation.paper_id)?.title} openPaper={openPaper} onChange={()=>{if(activeScope.current===paperKey)onChanged()}} onEntitySelect={onSelectEntity}/>):items.map(item=><KnowledgeCandidateCard key={item.id} item={item} busy={!!busy} saving={busy===item.id} paperTitle={papers.find(p=>p.id===item.paper_id)?.title} onDecide={(decision,edits)=>decide(item,decision,edits)} onEntitySelect={onSelectEntity} onLocate={e=>openPaper(item.paper_id,{page:e.page??1,bbox:e.bbox,page_width:e.page_width,page_height:e.page_height,source_text:e.quote})}/>)}
    {(tab==='objects'?!items.length:!relationItems.length)&&<p className="curation-empty">{query?t('kIntakeNoMatch'):filter==='pending'?t('knowledgeInboxEmpty'):t('kIntakeNoItems')}</p>}
  </section>
}
