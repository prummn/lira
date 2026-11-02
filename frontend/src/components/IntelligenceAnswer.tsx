import { useEffect, useState } from 'react'
import { ArrowUpRight, ChevronDown, X } from 'lucide-react'
import type { IntelligenceReport, LibraryAnswer, LibraryCitation, Usage } from '../types'
import { useUi } from '../lib/i18n'
import { ResearchMarkdown } from './ResearchMarkdown'
import { ScientificText } from './ScientificText'
import './research-answer.css'

export function UsageLine({usage,cached=false}:{usage?:Usage|null;cached?:boolean}) {
  const {t}=useUi()
  const total=usage?.total_tokens??(usage?.input_tokens!=null&&usage.output_tokens!=null?usage.input_tokens+usage.output_tokens:null)
  const calls=usage?.model_calls??usage?.remote_calls
  const connections=new Map<string,{name:string;model:string;failed:number}>()
  for(const call of usage?.calls??[]){const info=call.provider;if(!info?.profile_id)continue;const key=info.profile_id+':'+call.model;const item=connections.get(key)??{name:info.profile_name??info.profile_id,model:call.model,failed:0};if(info.failure)item.failed++;connections.set(key,item)}
  return <><div className="intelligence-usage"><span>{total!=null?`${t(usage?.unknown_usage_calls?'reportedTokens':'tokenUsage')} · ${total.toLocaleString()}`:t('usageUnknown')}</span>
    {calls!=null&&<span>{t('modelCalls')} · {calls}</span>}{usage?.cache_hits!=null&&<span>{t('cacheHits')} · {usage.cache_hits}</span>}{!!usage?.unknown_usage_calls&&<span>{t('usagePartial')} · {usage.unknown_usage_calls}</span>}{cached&&<span>{t('cachedResponse')}</span>}</div>
    {connections.size>0&&<details className="model-call-history"><summary>{t('modelConnectionsUsed')} · {Array.from(connections.values(),p=>p.name).join(' / ')}</summary><ul>{Array.from(connections.entries(),([key,p])=><li key={key}>{p.name} · {p.model}{p.failed>0&&` · ${t('modelConnectionFailure')} ${p.failed}`}</li>)}</ul></details>}
  </>
}
export function CoverageSummary({report}:{report?:IntelligenceReport|null}) {
  const {t}=useUi();const coverage=report?.coverage??report??{}
  const done=coverage.completed_windows??coverage.processed_windows??coverage.windows_completed
  const total=coverage.total_windows??coverage.windows_total
  const chars=coverage.processed_characters??coverage.processed_chars
  const charsTotal=coverage.total_characters??coverage.total_chars
  const science=report?.science_review
  const review=science&&typeof science==='object'&&!Array.isArray(science)?science as Record<string,unknown>:null
  const structure=report?.source_structure
  const sourceSections=structure&&typeof structure==='object'&&!Array.isArray(structure)?structure as Record<string,unknown>:null
  const reviewPending=(typeof review?.pending_items==='number'?review.pending_items:0)+(typeof review?.deferred_items==='number'?review.deferred_items:0)
  const reasonKeys={quote_not_found:'rejectionQuote',unknown_source:'rejectionSource',source_mismatch:'rejectionSource',invalid_source_ids:'rejectionSource',invalid_citation_ids:'rejectionSource',quote_outside_evidence:'rejectionSource',section_mismatch:'rejectionSection',incomplete_lineage:'rejectionLineage',missing_parent_citations:'rejectionLineage',invalid_parent_ids:'rejectionLineage',citation_budget:'rejectionBudget',science_support:'rejectionScienceSupport',science_review_format:'rejectionScienceReviewFormat'} as const
  const reasons:Partial<Record<(typeof reasonKeys)[keyof typeof reasonKeys]|'rejectionFormat',number>>={}
  if(Array.isArray(report?.rejections))for(const item of report.rejections) {
    if(item&&typeof item==='object'&&item.resolved!==true&&typeof item.reason==='string') {
      const category=reasonKeys[item.reason as keyof typeof reasonKeys]??'rejectionFormat'
      reasons[category]=(reasons[category]??0)+1
    }
  }
  return <div className="coverage-summary">
    {done!=null||total!=null?<span>{t('analysisCoverage')} · {String(done??'—')} / {String(total??'—')}</span>:<span>{t('analysisCoverageMissing')}</span>}
    {chars!=null&&<span>{t('analysisCoverageCharacters')} · {String(chars)}{charsTotal!=null?` / ${String(charsTotal)}`:''}</span>}
    {report?.citation_count!=null&&<span>{t('matchedCitations')} · {String(report.citation_count)}</span>}
    {Array.isArray(report?.accepted_card_fields)&&<span>{t('acceptedFields')} · {report.accepted_card_fields.length}</span>}
    {Array.isArray(report?.missing_fields)&&report.missing_fields.length>0&&<span>{t('missingFields')} · {report.missing_fields.length}</span>}
    {typeof report?.invalid_entries==='number'&&report.invalid_entries>0&&<span>{t('rejectedEntries')} · {report.invalid_entries}</span>}
    {typeof report?.repaired_entries==='number'&&report.repaired_entries>0&&<span>{t('repairedEntries')} · {report.repaired_entries}</span>}
    {Object.entries(reasons).map(([reason,count])=><span key={reason}>{t(reason as keyof typeof reasons)} · {count}</span>)}
    {sourceSections&&<>
      {sourceSections.available===false&&<span>{t('sourceSectionsUnavailable')}</span>}
      {sourceSections.available===true&&sourceSections.applied===true&&typeof sourceSections.changed_chunks==='number'&&<span>{t('sourceSectionsReidentified')} · {sourceSections.changed_chunks}</span>}
      {sourceSections.available===true&&typeof sourceSections.unmatched_chunks==='number'&&sourceSections.unmatched_chunks>0&&<span>{t('sourceSectionsUnmatched')} · {sourceSections.unmatched_chunks}</span>}
    </>}
    {(report?.source_structure_stale===true||sourceSections?.retained_card_uses_previous_structure===true)&&<span>{t('sourceSectionsPreviousCard')}</span>}
    {review&&<>
      {(typeof review.checked_items==='number'||typeof review.scheduled_items==='number')&&<span>{t('scienceReviewChecked')} · {String(review.checked_items??'—')} / {String(review.scheduled_items??'—')}</span>}
      {typeof review.corrected_items==='number'&&<span>{t('scienceReviewCorrected')} · {review.corrected_items}</span>}
      {reviewPending>0&&<span>{t('scienceReviewPending')} · {reviewPending}</span>}
      {typeof review.unreviewed_card_entries==='number'&&<span>{t('scienceReviewUnreviewed')} · {review.unreviewed_card_entries}</span>}
      {review.context_partial===true&&<span>{t('scienceReviewLimitedContext')}</span>}
      <span className="source-check-note">{t('scienceReviewNotProven')}</span>
    </>}
    <UsageLine usage={report?.usage}/>
  </div>
}
const claimKeys={fact:'claimFact',comparison:'claimComparison',inference:'claimInference',background:'claimBackground',user_note:'claimUser',metadata:'claimMetadata'} as const
const sourceGroup = (citation:LibraryCitation) => citation.source_type==='paper'&&citation.page!=null
  ? `${citation.paper_id}:page:${citation.page}` : `${citation.source_type}:${citation.id}`
export type AnswerSourceSelection={item:number;group:string}
export function IntelligenceAnswer({answer,onCitation,showSourceTitles=false,sourceSelection,onSourceSelection}:{answer:LibraryAnswer;onCitation:(citation:LibraryCitation)=>void;showSourceTitles?:boolean;sourceSelection?:AnswerSourceSelection|null;onSourceSelection?:(source:AnswerSourceSelection|null)=>void}) {
  const {t}=useUi()
  const [localActive,setLocalActive]=useState<AnswerSourceSelection|null>(null)
  const active=sourceSelection===undefined?localActive:sourceSelection
  const setActive=(source:AnswerSourceSelection|null)=>{setLocalActive(source);onSourceSelection?.(source)}
  useEffect(()=>setLocalActive(null),[answer])
  const numbers=new Map<string,number>()
  const paperIds=new Set<string>()
  for(const item of answer.items??[])for(const citation of item.citations){const key=sourceGroup(citation);if(!numbers.has(key))numbers.set(key,numbers.size+1);paperIds.add(citation.paper_id)}
  return <div className="intelligence-answer research-answer" role="status">
    {answer.insufficient_evidence&&<strong className="insufficient-evidence">{t('noAnswer')}</strong>}
    {answer.items?.length?answer.items.map((item,index)=>{
      const grouped=new Map<string,LibraryCitation[]>()
      for(const citation of item.citations){const key=sourceGroup(citation);const group=grouped.get(key)??[];if(!group.some(s=>s.id===citation.id))group.push(citation);grouped.set(key,group)}
      const selected=active?.item===index?grouped.get(active.group):undefined
      return <article className={'intelligence-claim claim-'+item.kind} key={index}>
        <span className="answer-kind-label">{t(claimKeys[item.kind])}</span>
        <ResearchMarkdown text={item.content}/>
        {grouped.size>0&&<div className="claim-citations answer-references">{[...grouped].map(([key,citations])=>{
          const citation=citations[0],number=numbers.get(key)
          return <button className="answer-reference" key={key} aria-label={`${t('viewSource')} ${number}`} aria-expanded={active?.item===index&&active.group===key} title={`${t(claimKeys[item.kind])} · ${citation.title}${citation.page!=null?` · ${t('page')} ${citation.page}`:''}`} onClick={()=>{
            if(citation.source_type==='external_metadata'||citation.source_type==='user'){onCitation(citation);return}
            setActive(active?.item===index&&active.group===key?null:{item:index,group:key})
          }}>[{number}]</button>
        })}</div>}
        {selected&&<section className="answer-source-panel" aria-label={t('explainSources')}>
          <header><span>{t('explainSources')}{selected[0].page!=null&&` · ${t('page')} ${selected[0].page}`}{selected[0].section&&` · ${selected[0].section}`}</span><button className="icon-btn" aria-label={t('close')} onClick={()=>setActive(null)}><X size={14}/></button></header>
          {(showSourceTitles||paperIds.size>1)&&<p className="answer-source-title">{selected[0].title}</p>}
          {selected.map(citation=><div className="answer-source-quote" key={citation.id}>
            <ScientificText text={citation.source_text}/>
            <button className="text-btn" onClick={()=>onCitation(citation)}><ArrowUpRight size={12}/>{t('jump')}</button>
          </div>)}
        </section>}
      </article>
    }):<ResearchMarkdown text={answer.answer}/>}
    <details className="answer-details"><summary>{numbers.size>0&&<span>{numbers.size} {t('answerSourceLocations')} · </span>}{t('explainResponseDetails')}<ChevronDown size={12}/></summary>
      <div className="answer-details-body">
        <p>{answer.provider}{answer.model&&` · ${answer.model}`} · {answer.mode}</p>
        {answer.coverage?.reading_mode==='full_paper'&&<p>{t('answerFullTextContext')}</p>}
        {answer.coverage?.retrieval_is_partial===true&&<p>{t('answerPartialContext')}</p>}
        {!!answer.limitations?.length&&<aside className="answer-reading-limits">{answer.limitations.map((limit,i)=><ResearchMarkdown text={limit} key={i}/>)}</aside>}
        <p>{t('semanticReview')}</p><UsageLine usage={answer.usage} cached={answer.cached}/>
      </div>
    </details>
  </div>
}
