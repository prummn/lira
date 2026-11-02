import type { KnowledgeCandidate, KnowledgeRelation } from '../types'

export type ReviewFilter = 'pending' | 'settled' | 'ignored'
export const settled = (status:string) => ['confirmed','known','alias'].includes(status)
// Display PDF soft line breaks as prose; evidence and PDF locators stay verbatim.
export const readableQuote = (quote:string) => quote.replace(/(\p{L})-\s*\n\s*(?=\p{Ll})/gu,'$1').replace(/\s+/g,' ').trim()
export const reviewState = (status:string):ReviewFilter => settled(status)?'settled':status==='rejected'?'ignored':'pending'
export const reviewMatches = (item:KnowledgeCandidate|KnowledgeRelation, filter:ReviewFilter, query:string) => {
  if(reviewState(item.status)!==filter)return false
  const haystack='name' in item?[item.name,item.extracted_name,...item.aliases,item.description]:[item.source_name,item.target_name,item.description]
  return haystack.filter(Boolean).join(' ').normalize('NFKC').toLocaleLowerCase().includes(query.trim().normalize('NFKC').toLocaleLowerCase())
}
export const reviewCounts = (items:Array<KnowledgeCandidate|KnowledgeRelation>) => items.reduce((counts,item)=>{
  counts[reviewState(item.status)]++;return counts
},{pending:0,settled:0,ignored:0})
export const intakeGroups = ['methods','evaluation','components','background'] as const
export type IntakeGroup = typeof intakeGroups[number]
export function intakeGroup(item:KnowledgeCandidate):IntakeGroup {
  if(['dataset','benchmark','task','metric'].includes(item.entity_type))return 'evaluation'
  if(item.entity_type==='concept'||item.layer==='component')return 'components'
  if(item.entity_type==='method')return ['baseline','compared','cited','ablation'].includes(item.role)?'background':'methods'
  return 'background'
}
export function readingOrder(a:KnowledgeCandidate,b:KnowledgeCandidate) {
  const weight=(item:KnowledgeCandidate)=>item.role==='proposed'?0:item.layer==='ablation'?3:item.layer==='baseline'?2:1
  return weight(a)-weight(b)||(a.evidence[0]?.page??Infinity)-(b.evidence[0]?.page??Infinity)||a.name.localeCompare(b.name)
}
