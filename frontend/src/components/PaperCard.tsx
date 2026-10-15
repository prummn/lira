import { useEffect, useState } from 'react'
import { useUi } from '../lib/i18n'
import type { LocaleKey } from '../lib/i18n'
import type { CardField, CardItem, Evidence, PaperDetail } from '../types'
import { Empty } from './Shared'
import { ScientificText } from './ScientificText'
import { EvidenceDisclosure } from './EvidenceSources'
import { readCardItems } from './evidence-model'

const dimensions: [CardField,LocaleKey][] = [
  ['one_sentence_summary','summary'],['problem','problem'],['motivation','motivation'],
  ['background','background'],['core_idea','coreIdea'],['method','method'],
  ['contributions','contributions'],['datasets','datasets'],['metrics','metrics'],
  ['baselines','baselines'],['main_results','results'],['ablation_findings','ablationFindings'],
  ['limitations','limitations'],['future_work','futureWork'],['prerequisite_concepts','prerequisites'],
  ['claims','claims'],['related_methods','relatedMethods'],
]
export function PaperCard({paper,locate,sourceTarget}:{paper:PaperDetail;locate:(e:Evidence)=>void;sourceTarget?:string|null}) {
  const {t}=useUi()
  const [level,setLevel]=useState<'tldr'|'structuredSummary'|'sectionSummary'>('structuredSummary')
  useEffect(()=>{
    if(!sourceTarget)return
    if(sourceTarget.startsWith('tldr-'))setLevel('tldr')
    else if(sourceTarget.startsWith('section_summaries-'))setLevel('sectionSummary')
    else setLevel('structuredSummary')
    const frame=requestAnimationFrame(()=>document.getElementById(`paper-card-${sourceTarget}`)?.closest('details')?.setAttribute('open',''))
    return()=>cancelAnimationFrame(frame)
  },[sourceTarget])
  const analysis=paper.analysis
  if(!analysis)return <Empty title={t('analysisEmpty')} text={t('analysisHint')}/>
  const readItems=(field:CardField):CardItem[]=>readCardItems(paper,field)
  const renderItem=(item:CardItem,index:number,field:CardField)=>{
    const entryId=`${field}-${index}`
    return <article id={`paper-card-${entryId}`} tabIndex={sourceTarget===entryId?-1:undefined} aria-current={sourceTarget===entryId?'true':undefined} className={`card-entry ${sourceTarget===entryId?'source-target':''}`} key={index}><ScientificText text={item.content}/><EvidenceDisclosure paper={paper} item={item} locate={locate}/></article>
  }
  const primary:CardField[]=['one_sentence_summary','problem','motivation','method','contributions','main_results','limitations']
  const renderDimension=([field,label]:[CardField,LocaleKey])=>{const items=readItems(field);return <section key={field}><h3>{t(label)}</h3>{items.length?items.map((item,index)=>renderItem(item,index,field)):<p className="muted">{t('unreported')}</p>}</section>}
  return <div className="paper-card"><div className="summary-levels" role="group" aria-label={t('summaryLevels')}>{(['tldr','structuredSummary','sectionSummary'] as const).map(key=><button key={key} className={level===key?'active':''} onClick={()=>setLevel(key)}>{t(key)}</button>)}</div>
    {level==='tldr'&&(readItems('tldr').length?<div className="analysis-fields">{readItems('tldr').map((item,index)=>renderItem(item,index,'tldr'))}</div>:<Empty title={t('summaryNotReady')} text={t('summaryNeedsEvidence')}/>)}
    {level==='structuredSummary'&&<div className="analysis-fields">{dimensions.filter(([field])=>primary.includes(field)).map(renderDimension)}<details className="abstract-details"><summary>{t('fieldDetails')}</summary>{dimensions.filter(([field])=>!primary.includes(field)).map(renderDimension)}</details><details className="abstract-details"><summary>{t('abstracts')}</summary>{(['abstract_zh','abstract_en'] as const).map(field=><section key={field}><h3>{t(field==='abstract_zh'?'chineseAbstract':'englishAbstract')}</h3>{readItems(field).length?readItems(field).map((item,index)=>renderItem(item,index,field)):<p className="muted">{t('unreported')}</p>}</section>)}</details></div>}
    {level==='sectionSummary'&&(readItems('section_summaries').length?<div className="analysis-fields">{readItems('section_summaries').map((item,index)=><section key={index}><h3>{item.section||t('unknown')}</h3>{renderItem(item,index,'section_summaries')}</section>)}</div>:<Empty title={t('summaryNotReady')} text={t('summaryNeedsEvidence')}/>)}
  </div>
}
