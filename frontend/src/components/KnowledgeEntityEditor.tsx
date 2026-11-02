import { useEffect, useState } from 'react'
import { ArrowRight, GitMerge, LoaderCircle, Plus, Trash2 } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import { useUi, type LocaleKey } from '../lib/i18n'
import { entityTypes, typeLabel } from '../lib/knowledgeLabels'
import type { KnowledgeEntityDetail, KnowledgeEntityIndexItem, KnowledgeEntityInput, KnowledgeMergePreview } from '../types'

export function KnowledgeEntityEditor({detail,onSaved,onCancel,onBusy}: {
  detail:KnowledgeEntityDetail; onSaved:(detail:KnowledgeEntityDetail)=>void; onCancel:()=>void; onBusy:(busy:boolean)=>void
}) {
  const {t}=useUi()
  const [form,setForm]=useState<KnowledgeEntityInput>(()=>({name:detail.name,entity_type:detail.entity_type,aliases:detail.aliases,description:detail.description,links:detail.links.filter(link=>link.source!=='search').map(link=>({kind:link.kind==='github'?'repository':link.kind as KnowledgeEntityInput['links'][number]['kind'],label:link.label,url:link.url}))}))
  const [aliases,setAliases]=useState(detail.aliases.join('\n'))
  const [merging,setMerging]=useState(false)
  const [targets,setTargets]=useState<KnowledgeEntityIndexItem[]>([])
  const [target,setTarget]=useState('')
  const [preview,setPreview]=useState<KnowledgeMergePreview|null>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  useEffect(()=>{
    if(!merging)return
    let active=true
    api.knowledgeEntities(detail.entity_type).then(result=>{if(active)setTargets(result.items.filter(item=>item.id!==detail.id))}).catch(e=>{if(active)setError(errorMessage(e))})
    return()=>{active=false}
  },[merging,detail.id,detail.entity_type])
  const perform=async(action:()=>Promise<void>)=>{
    if(busy)return
    setBusy(true);onBusy(true);setError('')
    try {await action()} catch(e){setError(errorMessage(e))} finally {setBusy(false);onBusy(false)}
  }
  return <div className="curation-editor">
    <p className="curation-hint">{t(merging?'kMergeHint':'kEditHint')}</p>
    {error&&<p className="dossier-error" role="alert">{error}</p>}
    {!merging?<form onSubmit={event=>{event.preventDefault();void perform(async()=>onSaved(await api.updateKnowledgeEntity(detail.id,{...form,aliases:aliases.split('\n').map(s=>s.trim()).filter(Boolean)})))}}>
      <fieldset disabled={busy} className="curation-fields">
        <div className="curation-two-fields"><label>{t('kName')}<input autoFocus required maxLength={300} value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label><label>{t('kType')}<select aria-label={t('kType')} value={form.entity_type} onChange={e=>setForm({...form,entity_type:e.target.value as KnowledgeEntityInput['entity_type']})}>{entityTypes.map(type=><option key={type} value={type}>{t(typeLabel(type))}</option>)}</select></label></div>
        <label>{t('kDescription')}<textarea aria-label={t('kDescription')} rows={5} maxLength={12000} value={form.description??''} onChange={e=>setForm({...form,description:e.target.value})}/></label>
        <div><label>{t('kAliases')}<textarea aria-label={t('kAliases')} rows={3} value={aliases} onChange={e=>setAliases(e.target.value)} aria-describedby="alias-help"/></label><small id="alias-help">{t('kAliasesHint')}</small></div>
        <section className="curation-links-editor"><h3>{t('kStoredLinks')}</h3>{form.links.map((link,index)=><div className="curation-link-input" key={index}>
          <label>{t('kLinkKind')}<select aria-label={t('kLinkKind')} value={link.kind} onChange={e=>setForm({...form,links:form.links.map((v,i)=>i===index?{...v,kind:e.target.value as typeof link.kind}:v)})}>{['official','repository','paper','dataset'].map(kind=><option value={kind} key={kind}>{t(`klink_${kind}` as LocaleKey)}</option>)}</select></label>
          <label>{t('kLinkLabel')}<input required maxLength={150} value={link.label} onChange={e=>setForm({...form,links:form.links.map((v,i)=>i===index?{...v,label:e.target.value}:v)})}/></label>
          <label className="curation-link-url">{t('kLinkUrl')}<input required type="url" placeholder="https://" value={link.url} onChange={e=>setForm({...form,links:form.links.map((v,i)=>i===index?{...v,url:e.target.value}:v)})}/></label>
          <button type="button" className="icon-btn" aria-label={t('kRemoveLink')} onClick={()=>setForm({...form,links:form.links.filter((_,i)=>i!==index)})}><Trash2 size={15}/></button>
        </div>)}<button type="button" className="text-btn" onClick={()=>setForm({...form,links:[...form.links,{kind:'official',label:'',url:''}]})}><Plus size={14}/>{t('kLinkAdd')}</button></section>
      </fieldset>
      <div className="curation-form-actions"><button type="submit" className="btn primary" disabled={busy||!form.name.trim()}>{busy&&<LoaderCircle size={14} className="spin"/>}{t('save')}</button><button type="button" className="btn secondary" disabled={busy} onClick={onCancel}>{t('cancel')}</button></div>
      <button type="button" className="text-btn curation-merge-start" disabled={busy} onClick={()=>{setMerging(true);setError('')}}><GitMerge size={15}/>{t('kMerge')}</button>
    </form>:<div className="curation-fields">
      <label>{t('kMergeTarget')}<select aria-label={t('kMergeTarget')} value={target} disabled={busy} onChange={e=>{setTarget(e.target.value);setPreview(null)}}><option value="">{t('kMergeChoose')}</option>{targets.map(item=><option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
      {!targets.length&&<p className="curation-hint">{t('kMergeNone')}</p>}
      {preview&&<section className="curation-merge-preview"><div><strong>{preview.source_name}</strong><ArrowRight size={17}/><strong>{preview.target_name}</strong></div><p><b>{preview.candidate_count}</b> {t('kMergeRecords')} · {preview.paper_count} {t('dossierPapers')} · {preview.relation_count} {t('dossierRelations')}</p><p>{t('kAliases')} · {preview.aliases.join(' · ')||'—'}</p>{preview.target_description&&<p>{preview.target_description}</p>}{!!preview.relations_to_review?.length&&<p className="curation-merge-conflicts">{preview.relations_to_review.length} {t('kMergeRelationsReview')}</p>}<p>{t('kMergeRetain')}</p></section>}
      <div className="curation-form-actions"><button className="btn primary" disabled={busy||!target} onClick={()=>void perform(async()=>{if(preview)onSaved(await api.mergeKnowledgeEntity(detail.id,target));else setPreview(await api.previewKnowledgeMerge(detail.id,target))})}>{busy&&<LoaderCircle size={14} className="spin"/>}{t(preview?'kMergeConfirm':'kMergePreview')}</button><button className="btn secondary" disabled={busy} onClick={()=>{setMerging(false);setPreview(null);setError('')}}>{t('cancel')}</button></div>
    </div>}
  </div>
}
