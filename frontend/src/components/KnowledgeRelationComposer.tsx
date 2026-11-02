import { useEffect, useState } from 'react'
import { ArrowUpDown, LoaderCircle } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { relationLabel, relationTypes, typeLabel } from '../lib/knowledgeLabels'
import type { KnowledgeCandidate, KnowledgeEntityDetail, KnowledgeRelation, KnowledgeRelationInput, PaperDetail } from '../types'

export function KnowledgeRelationComposer({detail,onCreated,onCancel,onBusy}: {
  detail:KnowledgeEntityDetail; onCreated:(relation:KnowledgeRelation)=>void; onCancel:()=>void; onBusy:(busy:boolean)=>void
}) {
  const {t}=useUi()
  const [paperId,setPaperId]=useState(detail.papers[0]?.paper_id??'')
  const [paper,setPaper]=useState<PaperDetail|null>(null)
  const [candidates,setCandidates]=useState<KnowledgeCandidate[]>([])
  const [form,setForm]=useState<KnowledgeRelationInput>({source_candidate_id:'',target_candidate_id:'',relation:'builds_on',description:''})
  const [chunkId,setChunkId]=useState('')
  const [quote,setQuote]=useState('')
  const [loading,setLoading]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  useEffect(()=>{
    if(!paperId)return
    let active=true;setLoading(true);setError('');setPaper(null);setCandidates([])
    Promise.all([api.paper(paperId),api.paperKnowledge(paperId)]).then(([source,knowledge])=>{
      if(!active)return
      setPaper(source);setCandidates(knowledge.candidates.filter(row=>row.status!=='rejected'))
      const local=knowledge.candidates.find(row=>row.entity_id===detail.id&&row.status!=='rejected')
      setForm({source_candidate_id:local?.id??'',target_candidate_id:'',relation:'builds_on',description:''})
      const evidence=local?.evidence[0],chunk=source.chunks.find(c=>c.id===evidence?.chunk_id)??source.chunks[0]
      setChunkId(chunk?.id??'');setQuote(chunk?.id===evidence?.chunk_id?evidence!.quote:chunk?.content.slice(0,4000)??'')
    }).catch(e=>{if(active)setError(errorMessage(e))}).finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[paperId,detail.id])
  const save=async()=>{
    const chunk=paper?.chunks.find(c=>c.id===chunkId)
    if(!chunk||busy)return
    setBusy(true);onBusy(true);setError('')
    try {onCreated(await api.createKnowledgeRelation(paperId,{...form,evidence:[{chunk_id:chunk.id,page:chunk.page,section:chunk.section,quote,bbox:null,page_width:null,page_height:null}]}))} catch(e){setError(errorMessage(e))} finally{setBusy(false);onBusy(false)}
  }
  return <form className="curation-relation-composer curation-fields" onSubmit={e=>{e.preventDefault();void save()}}>
    <h3>{t('kAddRelation')}</h3><p className="curation-hint">{t('kAddRelationHint')}</p>
    {error&&<p className="dossier-error" role="alert">{error}</p>}
    <fieldset className="curation-fields" disabled={busy}>
      <label>{t('kSourcePaper')}<select aria-label={t('kSourcePaper')} value={paperId} onChange={e=>setPaperId(e.target.value)}>{detail.papers.map(p=><option value={p.paper_id} key={p.paper_id}>{p.title}</option>)}</select></label>
      {loading?<LoaderCircle className="spin" size={15}/>:<>
        <div className="curation-endpoint-fields"><label>{t('kRelationSource')}<select required aria-label={t('kRelationSource')} value={form.source_candidate_id} onChange={e=>setForm({...form,source_candidate_id:e.target.value})}><option value="">{t('kChooseEndpoint')}</option>{candidates.map(c=><option key={c.id} value={c.id}>{c.name} · {t(typeLabel(c.entity_type))}</option>)}</select></label><button type="button" className="icon-btn" aria-label={t('kSwap')} onClick={()=>setForm({...form,source_candidate_id:form.target_candidate_id,target_candidate_id:form.source_candidate_id})}><ArrowUpDown size={16}/></button><label>{t('kRelationTarget')}<select required aria-label={t('kRelationTarget')} value={form.target_candidate_id} onChange={e=>setForm({...form,target_candidate_id:e.target.value})}><option value="">{t('kChooseEndpoint')}</option>{candidates.map(c=><option key={c.id} value={c.id}>{c.name} · {t(typeLabel(c.entity_type))}</option>)}</select></label></div>
        <label>{t('kRelationType')}<select aria-label={t('kRelationType')} value={form.relation} onChange={e=>setForm({...form,relation:e.target.value})}>{relationTypes.map(kind=><option value={kind} key={kind}>{t(relationLabel(kind))}</option>)}</select></label>
        <label>{t('kRelationDescription')}<textarea aria-label={t('kRelationDescription')} rows={3} value={form.description??''} onChange={e=>setForm({...form,description:e.target.value})}/></label>
        <label>{t('kEvidenceParagraph')}<select aria-label={t('kEvidenceParagraph')} value={chunkId} onChange={e=>{setChunkId(e.target.value);setQuote(paper?.chunks.find(c=>c.id===e.target.value)?.content.slice(0,4000)??'')}}>{paper?.chunks.map(c=><option value={c.id} key={c.id}>p.{c.page??'—'} · {c.section??''} · {c.content.slice(0,70)}</option>)}</select></label>
        <label>{t('kEvidenceQuote')}<textarea aria-label={t('kEvidenceQuote')} required maxLength={4000} rows={5} value={quote} onChange={e=>setQuote(e.target.value)}/></label>
      </>}
    </fieldset>
    <div className="curation-form-actions"><button className="btn primary" disabled={busy||loading||!quote.trim()||!form.source_candidate_id||!form.target_candidate_id||form.source_candidate_id===form.target_candidate_id}>{busy&&<LoaderCircle size={14} className="spin"/>}{t('kSaveForReview')}</button><button type="button" className="btn secondary" disabled={busy} onClick={onCancel}>{t('cancel')}</button></div>
  </form>
}
