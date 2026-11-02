import { useEffect, useRef, useState } from 'react'
import { ArrowRight, ArrowUpRight, ArrowUpDown, Check, LoaderCircle, Pencil, RotateCcw, X } from 'lucide-react'
import type { KnowledgeCandidate, KnowledgeEntityType, KnowledgeRelation, KnowledgeRelationInput } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { entityTypes, relationLabel, relationTypes, statusLabel, typeLabel } from '../lib/knowledgeLabels'
import { readableQuote } from '../lib/knowledgeReview'
import { ScientificText } from './ScientificText'
import type { PdfLocator } from './PdfViewer'

export function KnowledgeRelationCard({relation,paperTitle,openPaper,onChange,onEntitySelect,onBusy}: {
  relation:KnowledgeRelation; paperTitle?:string; openPaper:(id:string,locator?:PdfLocator)=>void
  onChange:(relation:KnowledgeRelation)=>void; onEntitySelect?:(id:string,name:string)=>void; onBusy?:(busy:boolean)=>void
}) {
  const {t}=useUi()
  const [editing,setEditing]=useState(false)
  const [resolving,setResolving]=useState(false)
  const [candidates,setCandidates]=useState<KnowledgeCandidate[]>([])
  const [form,setForm]=useState<KnowledgeRelationInput>({source_candidate_id:relation.source_candidate_id??'',target_candidate_id:relation.target_candidate_id??'',relation:relation.relation,description:relation.description})
  const [targetName,setTargetName]=useState(relation.target_name)
  const [targetType,setTargetType]=useState<KnowledgeEntityType>('method')
  const [busy,setBusy]=useState(false)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const mounted=useRef(true)
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
  useEffect(()=>{
    if(!editing)return
    let active=true;setLoading(true);setError('')
    api.paperKnowledge(relation.paper_id).then(result=>{if(active)setCandidates(result.candidates.filter(row=>row.status!=='rejected'))}).catch(e=>{if(active)setError(errorMessage(e))}).finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[editing,relation.paper_id])
  const perform=async(action:()=>Promise<KnowledgeRelation>)=>{
    if(busy)return
    setBusy(true);onBusy?.(true);setError('')
    try {const next=await action();onChange(next);if(mounted.current){setEditing(false);setResolving(false)}} catch(e){if(mounted.current)setError(errorMessage(e))} finally{if(mounted.current)setBusy(false);onBusy?.(false)}
  }
  const name=(id:string|null|undefined,label:string)=>id&&onEntitySelect?<button onClick={()=>onEntitySelect(id,label)} disabled={busy}>{label}</button>:<strong>{label}</strong>
  const pending=!['confirmed','known','alias','rejected'].includes(relation.status)
  return <article className={`curation-relation ${relation.status==='rejected'?'is-ignored':''}`}>
    <div className="curation-relation-top"><span className={`curation-relation-status chip-${relation.status}`}>{t(statusLabel(relation.status))}</span>{paperTitle&&<span className="curation-relation-paper">{paperTitle}</span>}</div>
    <div className="curation-relation-path">{name(relation.source_entity_id,relation.source_name)}<span>{t(relationLabel(relation.relation))}<ArrowRight size={14}/></span>{name(relation.target_entity_id,relation.target_name)}</div>
    {relation.description&&<p className="curation-relation-description">{relation.description}</p>}
    <details className="curation-relation-evidence"><summary>{t('kReadSource')} <span>{relation.evidence.length}</span></summary>{relation.evidence.map((e,index)=><button key={index} onClick={()=>openPaper(relation.paper_id,{page:e.page??1,bbox:e.bbox,page_width:e.page_width,page_height:e.page_height,source_text:e.quote})}><span>{e.section} · p.{e.page??'—'}<ArrowUpRight size={13}/></span><blockquote><ScientificText text={readableQuote(e.quote)}/></blockquote></button>)}</details>
    {error&&<p role="alert" className="dossier-error">{error}</p>}
    {editing?<form className="curation-fields curation-relation-editor" onSubmit={event=>{event.preventDefault();void perform(()=>api.updateKnowledgeRelation(relation.id,form))}}>
      <p className="curation-hint">{t('kRelationHint')}</p>
      {loading&&<LoaderCircle size={15} className="spin"/>}
      <fieldset disabled={busy||loading} className="curation-fields">
        <div className="curation-endpoint-fields"><label>{t('kRelationSource')}<select required aria-label={t('kRelationSource')} value={form.source_candidate_id} onChange={e=>setForm({...form,source_candidate_id:e.target.value})}><option value="">{t('kChooseEndpoint')}</option>{candidates.map(c=><option key={c.id} value={c.id}>{c.name} · {t(typeLabel(c.entity_type))}</option>)}</select></label><button type="button" className="icon-btn" aria-label={t('kSwap')} onClick={()=>setForm({...form,source_candidate_id:form.target_candidate_id,target_candidate_id:form.source_candidate_id})}><ArrowUpDown size={17}/></button><label>{t('kRelationTarget')}<select required aria-label={t('kRelationTarget')} value={form.target_candidate_id} onChange={e=>setForm({...form,target_candidate_id:e.target.value})}><option value="">{t('kChooseEndpoint')}</option>{candidates.map(c=><option key={c.id} value={c.id}>{c.name} · {t(typeLabel(c.entity_type))}</option>)}</select></label></div>
        <label>{t('kRelationType')}<select aria-label={t('kRelationType')} value={form.relation} onChange={e=>setForm({...form,relation:e.target.value})}>{relationTypes.map(kind=><option value={kind} key={kind}>{t(relationLabel(kind))}</option>)}</select></label>
        <label>{t('kRelationDescription')}<textarea aria-label={t('kRelationDescription')} rows={3} value={form.description??''} onChange={e=>setForm({...form,description:e.target.value})}/></label>
      </fieldset>
      <div className="curation-form-actions"><button className="btn primary" disabled={busy||loading||!form.source_candidate_id||!form.target_candidate_id}>{t('save')}</button><button type="button" className="btn secondary" disabled={busy} onClick={()=>setEditing(false)}>{t('cancel')}</button></div>
    </form>:resolving?<form className="curation-fields curation-relation-editor" onSubmit={e=>{e.preventDefault();void perform(()=>api.resolveKnowledgeRelation(relation.id,{target_name:targetName,target_type:targetType}))}}>
      <label>{t('relationTargetName')}<input required value={targetName} onChange={e=>setTargetName(e.target.value)}/></label><label>{t('relationTargetType')}<select value={targetType} onChange={e=>setTargetType(e.target.value as KnowledgeEntityType)}>{entityTypes.map(type=><option key={type} value={type}>{t(typeLabel(type))}</option>)}</select></label><div className="curation-form-actions"><button className="btn primary" disabled={busy||!targetName.trim()}>{t('resolveRelation')}</button><button type="button" className="btn secondary" disabled={busy} onClick={()=>setResolving(false)}>{t('cancel')}</button></div>
    </form>:<footer className="curation-relation-actions">
      {busy&&<LoaderCircle size={14} className="spin"/>}
      {relation.status==='rejected'?<button className="text-btn" disabled={busy} onClick={()=>void perform(()=>api.restoreKnowledgeRelation(relation.id))}><RotateCcw size={13}/>{t('kRestore')}</button>:<>
        {pending&&(relation.target_candidate_id?(relation.source_candidate_id&&<button className="text-btn" disabled={busy} onClick={()=>void perform(()=>api.confirmKnowledgeRelation(relation.id))}><Check size={14}/>{t('kConfirmRelation')}</button>):<button className="text-btn" disabled={busy} onClick={()=>setResolving(true)}>{t('kResolve')}</button>)}
        <button className="text-btn" disabled={busy} onClick={()=>{setForm({source_candidate_id:relation.source_candidate_id??'',target_candidate_id:relation.target_candidate_id??'',relation:relation.relation,description:relation.description});setEditing(true)}}><Pencil size={13}/>{t('kRelationEdit')}</button>
        <button className="text-btn curation-ignore" disabled={busy} onClick={()=>void perform(()=>api.rejectKnowledgeRelation(relation.id))}><X size={13}/>{t('kIgnoreRelation')}</button>
      </>}
    </footer>}
  </article>
}
