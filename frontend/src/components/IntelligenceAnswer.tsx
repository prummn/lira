import { ArrowUpRight, Link2 } from 'lucide-react'
import type { IntelligenceReport, LibraryAnswer, LibraryCitation, Usage } from '../types'
import { useUi } from '../lib/i18n'

export function UsageLine({usage,cached=false}:{usage?:Usage|null;cached?:boolean}) {
  const {t}=useUi()
  const total=usage?.total_tokens??(usage?.input_tokens!=null&&usage.output_tokens!=null?usage.input_tokens+usage.output_tokens:null)
  const calls=usage?.model_calls??usage?.remote_calls
  return <div className="intelligence-usage"><span>{total!=null?`${t(usage?.unknown_usage_calls?'reportedTokens':'tokenUsage')} · ${total.toLocaleString()}`:t('usageUnknown')}</span>
    {calls!=null&&<span>{t('modelCalls')} · {calls}</span>}{usage?.cache_hits!=null&&<span>{t('cacheHits')} · {usage.cache_hits}</span>}{!!usage?.unknown_usage_calls&&<span>{t('usagePartial')} · {usage.unknown_usage_calls}</span>}{cached&&<span>{t('cachedResponse')}</span>}</div>
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
const claimKeys={fact:'claimFact',comparison:'claimComparison',inference:'claimInference',user_note:'claimUser',metadata:'claimMetadata'} as const
export function IntelligenceAnswer({answer,onCitation}:{answer:LibraryAnswer;onCitation:(citation:LibraryCitation)=>void}) {
  const {t}=useUi()
  return <div className="intelligence-answer" role="status"><div className="provider-line">{answer.provider}{answer.model&&` · ${answer.model}`} · {answer.mode}</div>
    {answer.insufficient_evidence&&<strong className="insufficient-evidence">{t('noAnswer')}</strong>}
    {answer.items?.length?answer.items.map((item,index)=><article className={'intelligence-claim claim-'+item.kind} key={index}>
      <span className={'claim-kind claim-kind-'+item.kind}>{t(claimKeys[item.kind])}</span><p>{item.content}</p>
      <div className="claim-citations">{item.citations.map(citation=><button key={citation.id} onClick={()=>onCitation(citation)} title={t(citation.source_type==='external_metadata'?'viewRecord':'viewCitedPaper')}>
        {citation.source_type==='external_metadata'?<ArrowUpRight size={12}/>:<Link2 size={12}/>}<span>{citation.title}{citation.page!=null&&` · ${t('page')} ${citation.page}`}</span>
        <small>{t(citation.source_type==='external_metadata'?'claimMetadata':citation.source_type==='user'?'claimUser':citation.source_type==='ai'?'claimInference':'sourceMatched')}</small>
      </button>)}</div>
    </article>):<p className="intelligence-answer-text">{answer.answer}</p>}
    {!!answer.limitations?.length&&<ul className="answer-limitations">{answer.limitations.map((limit,i)=><li key={i}>{limit}</li>)}</ul>}
    <p className="source-check-note">{t('semanticReview')}</p><UsageLine usage={answer.usage} cached={answer.cached}/>
  </div>
}
