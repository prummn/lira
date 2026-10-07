import { useState } from 'react'
import { Link2 } from 'lucide-react'
import { useUi } from '../lib/i18n'
import type { LocaleKey } from '../lib/i18n'
import type { CardField, CardItem, Evidence, PaperDetail } from '../types'
import { Empty, SourceBadge } from './Shared'

const dimensions: [CardField,LocaleKey][] = [
  ['one_sentence_summary','summary'],['problem','problem'],['motivation','motivation'],
  ['background','background'],['core_idea','coreIdea'],['method','method'],
  ['contributions','contributions'],['datasets','datasets'],['metrics','metrics'],
  ['baselines','baselines'],['main_results','results'],['ablation_findings','ablationFindings'],
  ['limitations','limitations'],['future_work','futureWork'],['prerequisite_concepts','prerequisites'],
  ['claims','claims'],['related_methods','relatedMethods'],
]
const legacyFields:Partial<Record<CardField,'one_liner'|'problem'|'method'|'findings'|'limitations'>>={one_sentence_summary:'one_liner',problem:'problem',method:'method',main_results:'findings',limitations:'limitations'}

export function PaperCard({paper,locate}:{paper:PaperDetail;locate:(e:Evidence)=>void}) {
  const {t}=useUi()
  const [level,setLevel]=useState<'tldr'|'structuredSummary'|'sectionSummary'>('structuredSummary')
  const analysis=paper.analysis
  if(!analysis)return <Empty title={t('analysisEmpty')} text={t('analysisHint')}/>
  const readItems=(field:CardField):CardItem[]=>{
    const value=analysis.card?.[field]
    if(value)return Array.isArray(value)?value:[value]
    const legacyKey=legacyFields[field]
    const content=legacyKey?analysis[legacyKey]:null
    return content?[{content,evidence_ids:paper.evidence.filter(e=>e.claim===content||content.includes(e.source_text)).map(e=>e.id)}]:[]
  }
  const renderItem=(item:CardItem,index:number)=>{
    const citations=paper.evidence.filter(e=>item.evidence_ids.includes(e.id))
    return <div className="card-entry" key={index}><p>{item.content}</p><div className="card-citations">{citations.length>0&&<SourceBadge source={citations[0].source_type}/>} {citations.map(e=><button key={e.id} className="text-btn" onClick={()=>locate(e)}><Link2 size={12}/>{t('jump')} · {t('page')} {e.page}</button>)}</div></div>
  }
  const primary:CardField[]=['one_sentence_summary','problem','motivation','method','contributions','main_results','limitations']
  const renderDimension=([field,label]:[CardField,LocaleKey])=>{const items=readItems(field);return <section key={field}><h3>{t(label)}</h3>{items.length?items.map(renderItem):<p className="muted">{t('unreported')}</p>}</section>}
  return <div className="paper-card"><div className="summary-levels" role="group" aria-label={t('summaryLevels')}>{(['tldr','structuredSummary','sectionSummary'] as const).map(key=><button key={key} className={level===key?'active':''} onClick={()=>setLevel(key)}>{t(key)}</button>)}</div>
    {level==='tldr'&&(readItems('tldr').length?<div className="analysis-fields">{readItems('tldr').map(renderItem)}</div>:<Empty title={t('summaryNotReady')} text={t('summaryNeedsEvidence')}/>)}
    {level==='structuredSummary'&&<div className="analysis-fields">{dimensions.filter(([field])=>primary.includes(field)).map(renderDimension)}<details className="abstract-details"><summary>{t('fieldDetails')}</summary>{dimensions.filter(([field])=>!primary.includes(field)).map(renderDimension)}</details><details className="abstract-details"><summary>{t('abstracts')}</summary>{(['abstract_zh','abstract_en'] as const).map(field=><section key={field}><h3>{t(field==='abstract_zh'?'chineseAbstract':'englishAbstract')}</h3>{readItems(field).length?readItems(field).map(renderItem):<p className="muted">{t('unreported')}</p>}</section>)}</details></div>}
    {level==='sectionSummary'&&(readItems('section_summaries').length?<div className="analysis-fields">{readItems('section_summaries').map((item,index)=><section key={index}><h3>{item.section||t('unknown')}</h3>{renderItem(item,index)}</section>)}</div>:<Empty title={t('summaryNotReady')} text={t('summaryNeedsEvidence')}/>)}
  </div>
}
