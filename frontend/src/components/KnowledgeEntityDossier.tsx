import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowLeft, ArrowUpRight, ExternalLink, LoaderCircle, Pencil, Plus, X } from 'lucide-react'
import type { KnowledgeEntityDetail, KnowledgeEvidence, KnowledgeRelation } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi, type LocaleKey } from '../lib/i18n'
import { roleLabel, typeLabel } from '../lib/knowledgeLabels'
import { readableQuote } from '../lib/knowledgeReview'
import { ScientificText } from './ScientificText'
import type { PdfLocator } from './PdfViewer'
import { KnowledgeEntityEditor } from './KnowledgeEntityEditor'
import { KnowledgeRelationComposer } from './KnowledgeRelationComposer'
import { KnowledgeRelationCard } from './KnowledgeRelationCard'
import './knowledge-curation.css'

type Props = {
  entityId?:string|null; entityName?:string; pendingRelation?:KnowledgeRelation|null
  openPaper:(paperId:string,locator?:PdfLocator)=>void; onClose:()=>void
  onResolved?:(relation:KnowledgeRelation)=>void; onChanged?:(detail?:KnowledgeEntityDetail)=>void
  onSelectEntity?:(id:string,name:string)=>void
}
const historyLabels:Record<string,LocaleKey>={create_relation:'kCreateRelationAction',edit_entity:'kEditEntityAction',merge_entity:'kMergeEntityAction',edit_relation:'kEditRelationAction',confirm_relation:'kConfirmAction',reject_relation:'kRejectAction',restore_relation:'kRestoreAction',resolve_relation:'kResolveAction',endpoint_rejected:'kEndpointRejected',merge_relation_conflict:'kMergeConflict'}
const tabs=['overview','relations','sources','history'] as const

export function KnowledgeEntityDossier({entityId,entityName,pendingRelation,openPaper,onClose,onResolved,onChanged,onSelectEntity}:Props) {
  const {t,language}=useUi()
  const [detail,setDetail]=useState<KnowledgeEntityDetail|null>(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [tab,setTab]=useState<typeof tabs[number]>('overview')
  const [filter,setFilter]=useState('all')
  const [editing,setEditing]=useState(false)
  const [notice,setNotice]=useState('')
  const [saving,setSaving]=useState(false)
  const [composing,setComposing]=useState(false)
  const panel=useRef<HTMLElement>(null)
  const busy=useRef(false)
  const pendingOperations=useRef(0)
  const detailRefresh=useRef(0)
  const epoch=useRef(0)
  const closeRef=useRef(onClose);closeRef.current=onClose
  const editingRef=useRef(editing);editingRef.current=editing
  const entityRef=useRef(entityId);entityRef.current=entityId
  const setBusy=(value:boolean)=>{pendingOperations.current=Math.max(0,pendingOperations.current+(value?1:-1));busy.current=pendingOperations.current>0;setSaving(busy.current)}
  useEffect(()=>{
    const current=++epoch.current
    detailRefresh.current++
    setDetail(null);setError('');setTab('overview');setEditing(false);setComposing(false);setNotice('')
    if(!entityId){setLoading(false);return}
    setLoading(true)
    api.knowledgeEntity(entityId).then(value=>{if(epoch.current===current)setDetail(value)}).catch(e=>{if(epoch.current===current)setError(errorMessage(e))}).finally(()=>{if(epoch.current===current)setLoading(false)})
    return()=>{epoch.current++}
  },[entityId])
  useEffect(()=>{
    const opener=document.activeElement as HTMLElement|null
    const focusables=()=>Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex="0"]')??[]).filter(el=>el.getClientRects().length)
    panel.current?.focus()
    const keydown=(e:KeyboardEvent)=>{
      if(e.key==='Escape'){e.stopPropagation();if(busy.current)return;if(editingRef.current)setEditing(false);else closeRef.current()}
      if(e.key==='Tab'){
        const list=focusables(),first=list[0],last=list.at(-1)
        if(!panel.current?.contains(document.activeElement)||document.activeElement===panel.current){e.preventDefault();(e.shiftKey?last:first)?.focus()}
        else if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}
        else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}
      }
    }
    document.addEventListener('keydown',keydown)
    return()=>{document.removeEventListener('keydown',keydown);if(opener?.isConnected)opener.focus({preventScroll:true})}
  },[])
  const close=()=>{if(!busy.current)onClose()}
  const source=(e:KnowledgeEvidence)=>{
    if(e.paper_id)openPaper(e.paper_id,{page:e.page??1,bbox:e.bbox,page_width:e.page_width,page_height:e.page_height,source_text:e.quote})
  }
  const changedRelation=(next:KnowledgeRelation)=>{
    if(entityId!==entityRef.current){onChanged?.();return}
    const current=epoch.current
    const refresh=++detailRefresh.current
    setDetail(value=>value?{...value,relations:value.relations.some(row=>row.id===next.id)?value.relations.map(row=>row.id===next.id?next:row):[...value.relations,next]}:value)
    onResolved?.(next)
    if(detail)api.knowledgeEntity(detail.id).then(value=>{if(epoch.current===current&&detailRefresh.current===refresh)setDetail(value)}).catch(e=>{if(epoch.current===current&&detailRefresh.current===refresh)setError(errorMessage(e))})
    onChanged?.()
  }
  const title=detail?.name??pendingRelation?.target_name??entityName??t('knowledgeEntity')
  const relations=detail?.relations.filter(row=>filter==='ignored'?row.status==='rejected':filter==='confirmed'?['confirmed','known','alias'].includes(row.status):filter==='pending'?!['confirmed','known','alias','rejected'].includes(row.status):true)??[]
  const count=detail?.relations.filter(row=>row.status!=='rejected').length??0
  const activeCandidates=detail?.candidates?.filter(candidate=>candidate.status!=='rejected')??[]
  const contextual=activeCandidates.flatMap(candidate=>{
    const context=candidate.conflict._steward_context as {verdict?:string;reason?:string}|undefined
    return context&&['incidental','incorrect'].includes(context.verdict??'')&&context.reason?[{paperId:candidate.paper_id,reason:context.reason}]:[]
  })
  const contextOnly=detail?.context_only??(activeCandidates.length>0&&contextual.length===activeCandidates.length)
  const contextPapers=[...new Set(contextual.map(item=>item.paperId))].map(paperId=>({paperId,title:detail?.papers.find(paper=>paper.paper_id===paperId)?.title??paperId,reasons:[...new Set(contextual.filter(item=>item.paperId===paperId).map(item=>item.reason))]}))
  const renderRelation=(relation:KnowledgeRelation)=><KnowledgeRelationCard key={relation.id} relation={relation} paperTitle={detail?.papers.find(p=>p.paper_id===relation.paper_id)?.title} openPaper={openPaper} onChange={changedRelation} onEntitySelect={onSelectEntity} onBusy={setBusy}/>
  return createPortal(<div className="knowledge-dossier-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)close()}}>
    <aside ref={panel} className="knowledge-entity-dossier curation-dossier" role="dialog" aria-modal="true" aria-label={t('knowledgeEntity')} tabIndex={-1}>
      <header className="curation-dossier-header"><div><span className="eyebrow">{detail?t(typeLabel(detail.entity_type)):t('kRelationReview')}</span><h2>{title}</h2>{detail&&detail.aliases.length>0&&<p className="curation-alias-line">{detail.aliases.join(' · ')}</p>}</div><div className="curation-header-actions">{detail&&!editing&&<button className="text-btn" disabled={saving} onClick={()=>{setEditing(true);setNotice('')}}><Pencil size={14}/>{t('kEdit')}</button>}<button className="icon-btn" aria-label={t('close')} disabled={saving} onClick={close}><X size={19}/></button></div></header>
      {error&&<p className="dossier-error" role="alert">{error}</p>}
      {notice&&<p className="curation-notice" role="status">{notice}</p>}
      {loading&&<div className="knowledge-loading"><LoaderCircle size={16} className="spin"/>{t('loading')}</div>}
      {!loading&&!detail&&pendingRelation&&<div className="curation-dossier-body"><p className="curation-hint">{t('kReviewedHint')}</p>{renderRelation(pendingRelation)}</div>}
      {!loading&&detail&&(editing?<div className="curation-dossier-body"><button className="text-btn curation-back" onClick={()=>{if(!busy.current)setEditing(false)}}><ArrowLeft size={14}/>{t('kOverview')}</button><KnowledgeEntityEditor key={detail.id} detail={detail} onBusy={setBusy} onCancel={()=>setEditing(false)} onSaved={next=>{setDetail(next);setEditing(false);setNotice(t('kChangesSaved'));onChanged?.(next)}}/></div>:<>
        <div className="curation-dossier-tabs" role="tablist" aria-label={t('knowledgeEntity')}>{tabs.map(value=><button key={value} role="tab" aria-selected={tab===value} disabled={saving} onClick={()=>{setTab(value);setNotice('')}}>{t(value==='overview'?'kOverview':value==='relations'?'dossierRelations':value==='sources'?'kSources':'kHistory')}{value==='relations'&&<span>{count}</span>}</button>)}</div>
        <div className="curation-dossier-body" role="tabpanel">
          {tab==='overview'&&<>
            {!contextOnly&&<section className="curation-definition"><p>{detail.description||t('entityNoDescription')}</p></section>}
            {contextPapers.length>0&&<section className="dossier-context-notes" aria-label={t('kContextByPaper')}><h3>{t('kContextByPaper')}</h3>{contextPapers.map(paper=><article key={paper.paperId}><header><strong>{paper.title}</strong><span className="catalog-context-badge">{t('kContextBadge')}</span></header>{paper.reasons.map(reason=><p key={reason}>{reason}</p>)}<button className="text-btn" onClick={()=>openPaper(paper.paperId)}>{t('knowledgeOpenPaper')}<ArrowUpRight size={13}/></button></article>)}</section>}
            {contextOnly&&detail.description&&<details className="curation-preserved-description"><summary>{t('kPreservedDescription')}</summary><p>{detail.description}</p></details>}
            <div className="curation-object-stats"><button onClick={()=>panel.current?.querySelector('.knowledge-dossier-papers')?.scrollIntoView({block:'nearest',behavior:'smooth'})}><strong>{detail.papers.length}</strong>{t('dossierPapers')}</button><button onClick={()=>setTab('relations')}><strong>{count}</strong>{t('dossierRelations')}</button><button onClick={()=>setTab('sources')}><strong>{detail.evidence.length}</strong>{t('dossierEvidence')}</button></div>
            <section className="knowledge-dossier-papers"><h3>{t('dossierRelatedPapers')}</h3>{detail.papers.map(paper=><button className="dossier-paper-row" key={paper.paper_id} onClick={()=>openPaper(paper.paper_id)}><span><strong>{paper.title}</strong><small>{contextPapers.some(context=>context.paperId===paper.paper_id)?t('kContextBadge'):t(roleLabel(paper.role))} · {paper.evidence_count} {t('dossierEvidence')}</small></span><ArrowUpRight size={15}/></button>)}</section>
            <section className="knowledge-dossier-links"><h3>{t('dossierLinks')}</h3>{detail.links.map(link=><a key={link.url} href={link.url} target="_blank" rel="noreferrer"><ExternalLink size={15}/><span>{link.label}</span><small>{t(`klink_${link.kind}` as LocaleKey)}</small></a>)}</section>
          </>}
          {tab==='relations'&&<>{composing?<KnowledgeRelationComposer detail={detail} onBusy={setBusy} onCancel={()=>setComposing(false)} onCreated={next=>{changedRelation(next);setComposing(false);setFilter('pending')}}/>:<><button className="text-btn curation-add-relation" disabled={saving||!detail.papers.length} onClick={()=>setComposing(true)}><Plus size={14}/>{t('kAddRelation')}</button><div className="curation-filter" aria-label={t('kRelationReview')}>{[['all','kReviewAll'],['pending','kReviewPending'],['confirmed','kReviewConfirmed'],['ignored','kReviewIgnored']].map(([value,label])=><button key={value} className={filter===value?'active':''} onClick={()=>setFilter(value)}>{t(label as LocaleKey)}</button>)}</div>{relations.length?relations.map(renderRelation):<p className="curation-empty">{t('kRelationsEmpty')}</p>}</>}</>}
          {tab==='sources'&&<section className="dossier-evidence">{detail.evidence.length?detail.evidence.map((e,index)=><button key={`${e.paper_id}-${index}`} className="dossier-evidence-row" disabled={!e.paper_id} onClick={()=>source(e)}><span className="curation-evidence-meta"><strong>{e.paper_title??t('kSourcePaper')}</strong><small>{e.section} · p.{e.page??'—'}</small><ArrowUpRight size={14}/></span><ScientificText className="curation-source-quote" text={readableQuote(e.quote)}/></button>):<p className="curation-empty">{t('kNoEvidence')}</p>}</section>}
          {tab==='history'&&<section className="curation-history">{detail.history?.length?detail.history.map(change=><article key={change.id}><time>{new Date(change.created_at.endsWith('Z')?change.created_at:change.created_at+'Z').toLocaleString(language,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</time><div><strong>{t(historyLabels[change.action]??'kEditEntityAction')}</strong>{change.action==='edit_entity'&&change.before.name!==change.after.name&&<p>{String(change.before.name)} → {String(change.after.name)}</p>}{change.action==='merge_entity'&&<p>{String((change.before.source as Record<string,unknown>)?.name??'')} → {String(change.after.name)}</p>}{change.subject_type==='relation'&&<p>{String(change.after.source_name??'')} → {String(change.after.target_name??'')}</p>}</div></article>):<p className="curation-empty">{t('kNoHistory')}</p>}</section>}
        </div>
      </>)}
    </aside>
  </div>,document.body)
}
