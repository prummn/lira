import { ArrowUpRight, FileSearch, Link2 } from 'lucide-react'
import type { CardField, CardItem, Evidence, PaperDetail } from '../types'
import type { LocaleKey } from '../lib/i18n'
import { useUi } from '../lib/i18n'
import { ScientificText } from './ScientificText'
import { SourceBadge } from './Shared'
import { buildCardEntries, buildEvidenceIndex } from './evidence-model'

const labels:Record<CardField,LocaleKey>={
  one_sentence_summary:'summary',problem:'problem',motivation:'motivation',background:'background',core_idea:'coreIdea',method:'method',
  contributions:'contributions',datasets:'datasets',metrics:'metrics',baselines:'baselines',main_results:'results',ablation_findings:'ablationFindings',
  limitations:'limitations',future_work:'futureWork',prerequisite_concepts:'prerequisites',claims:'claims',related_methods:'relatedMethods',
  abstract_zh:'chineseAbstract',abstract_en:'englishAbstract',tldr:'tldr',section_summaries:'sectionSummary',
}

function pageSummary(items:Evidence[],unknown:string,pageLabel:string) {
  const pages=[...new Set(items.map(item=>item.page).filter((page):page is number=>page!=null))].sort((a,b)=>a-b)
  if(!pages.length)return unknown
  if(pages.length===1)return `${pageLabel} ${pages[0]}`
  return `${pageLabel} ${pages[0]}–${pages[pages.length-1]}`
}

export function EvidenceDisclosure({paper,item,locate}:{paper:PaperDetail;item:CardItem;locate:(e:Evidence)=>void}) {
  const {t}=useUi()
  const evidence=paper.evidence.filter(source=>item.evidence_ids.includes(source.id))
  const groups=buildEvidenceIndex(evidence,[])
  if(!groups.length)return <div className="evidence-missing"><FileSearch size={13}/><span>{t('evidenceUnlinked')}</span></div>
  return <details className="evidence-disclosure">
    <summary><span><Link2 size={13}/>{t('viewEvidence')}</span><small>{groups.length} {t('sourceCount')} · {pageSummary(groups.map(group=>group.evidence),t('pageUnknown'),t('page'))}</small></summary>
    <div className="evidence-disclosure-body">{groups.map(group=><article className="evidence-source-quote" key={group.key}>
      <header><span>{group.evidence.section||t('sectionUnknown')}</span><span className="evidence-source-types">{group.sourceTypes.map(source=><SourceBadge source={source} key={source}/>)}</span></header>
      <ScientificText text={group.evidence.source_text}/>
      <button type="button" onClick={()=>locate(group.evidence)}><ArrowUpRight size={13}/>{t('viewInPdf')} · {group.evidence.page==null?t('pageUnknown'):`${t('page')} ${group.evidence.page}`}</button>
    </article>)}</div>
  </details>
}

export function EvidenceIndex({paper,locate,onEntry}:{paper:PaperDetail;locate:(e:Evidence)=>void;onEntry:(id:string)=>void}) {
  const {t}=useUi()
  const entries=buildCardEntries(paper,field=>t(labels[field]))
  const groups=buildEvidenceIndex(paper.evidence,entries)
  const sections=new Map<string,typeof groups>()
  for(const group of groups) {
    const name=group.evidence.section||t('sectionUnknown')
    sections.set(name,[...(sections.get(name)||[]),group])
  }
  return <div className="evidence-index">
    <div className="evidence-index-head"><div><span className="eyebrow">SOURCE INDEX</span><strong>{groups.length} {t('uniqueSources')}</strong></div><small>{paper.evidence.length} {t('claimLinks')}</small></div>
    <p className="evidence-index-notice">{t('evidenceRelationshipNotice')}</p>
    {[...sections].map(([section,items])=><section className="evidence-section" key={section}>
      <header><h3>{section}</h3><span>{items.length}</span></header>
      {items.map(group=><article className="evidence-source-group" key={group.key}>
        <div className="evidence-source-meta"><span>{group.evidence.page==null?t('pageUnknown'):`${t('page')} ${group.evidence.page}`}</span><span className="evidence-source-types">{group.sourceTypes.map(source=><SourceBadge source={source} key={source}/>)}</span></div>
        <ScientificText text={group.evidence.source_text} className="evidence-source-text"/>
        <button className="evidence-locate" type="button" onClick={()=>locate(group.evidence)}><ArrowUpRight size={14}/>{t('viewInPdf')}</button>
        <div className="evidence-related"><span>{t('relatedConclusions')}</span>
          {group.entries.length?group.entries.map(entry=><button type="button" className="evidence-related-entry" key={entry.id} onClick={()=>onEntry(entry.id)}><small>{entry.label}</small><ScientificText text={entry.content}/><ArrowUpRight size={13}/></button>):group.claims.map((claim,index)=><div className="evidence-related-entry evidence-related-unlinked" key={`${group.key}-${index}`}><small>{t('analysisClaim')}</small><ScientificText text={claim}/></div>)}
        </div>
      </article>)}
    </section>)}
  </div>
}
