import type { CardField, CardItem, Evidence, PaperDetail } from '../types'

export interface CardEntryDescriptor {
  id:string
  field:CardField
  label:string
  content:string
  evidenceIds:string[]
  section?:string|null
}

export interface EvidenceGroup {
  key:string
  evidence:Evidence
  evidenceIds:string[]
  sourceTypes:string[]
  claims:string[]
  entries:CardEntryDescriptor[]
}

export const CARD_FIELDS:CardField[] = [
  'one_sentence_summary','problem','motivation','background','core_idea','method',
  'contributions','datasets','metrics','baselines','main_results','ablation_findings',
  'limitations','future_work','prerequisite_concepts','claims','related_methods',
  'abstract_zh','abstract_en','tldr','section_summaries',
]

const legacyFields:Partial<Record<CardField,'one_liner'|'problem'|'method'|'findings'|'limitations'>>={
  one_sentence_summary:'one_liner',problem:'problem',method:'method',main_results:'findings',limitations:'limitations',
}

export function readCardItems(paper:PaperDetail,field:CardField):CardItem[] {
  const value=paper.analysis?.card?.[field]
  if(value)return Array.isArray(value)?value:[value]
  const legacyKey=legacyFields[field]
  const content=legacyKey?paper.analysis?.[legacyKey]:null
  if(!content)return []
  return [{content,evidence_ids:paper.evidence.filter(item=>item.claim===content||content.includes(item.source_text)).map(item=>item.id)}]
}

export function buildCardEntries(paper:PaperDetail,label:(field:CardField)=>string):CardEntryDescriptor[] {
  return CARD_FIELDS.flatMap(field=>readCardItems(paper,field).map((item,index)=>({
    id:`${field}-${index}`,
    field,
    label:field==='section_summaries'&&item.section?item.section:label(field),
    content:item.content,
    evidenceIds:item.evidence_ids,
    section:item.section,
  })))
}

function normalizedSource(value:string) {
  return value.normalize('NFKC').replace(/\s+/g,' ').trim().toLocaleLowerCase()
}

export function evidenceIdentity(item:Evidence) {
  const bbox=item.bbox?.length===4?item.bbox.map(value=>Number.isFinite(value)?Math.round(value*100)/100:value).join(','):''
  return `${item.page??'unknown'}\u001f${item.chunk_id??''}\u001f${normalizedSource(item.source_text)}\u001f${bbox}\u001f${item.page_width??''}\u001f${item.page_height??''}`
}

export function buildEvidenceIndex(evidence:Evidence[],entries:CardEntryDescriptor[]):EvidenceGroup[] {
  const groups=new Map<string,EvidenceGroup>()
  for(const item of evidence) {
    const key=evidenceIdentity(item)
    const current=groups.get(key)
    if(current) {
      current.evidenceIds.push(item.id)
      if(!current.sourceTypes.includes(item.source_type))current.sourceTypes.push(item.source_type)
      if(item.claim&&!current.claims.includes(item.claim))current.claims.push(item.claim)
    } else groups.set(key,{key,evidence:item,evidenceIds:[item.id],sourceTypes:[item.source_type],claims:item.claim?[item.claim]:[],entries:[]})
  }
  for(const group of groups.values()) {
    const ids=new Set(group.evidenceIds)
    group.entries=entries.filter(entry=>entry.evidenceIds.some(id=>ids.has(id)))
  }
  return [...groups.values()].sort((a,b)=>(a.evidence.page??Number.MAX_SAFE_INTEGER)-(b.evidence.page??Number.MAX_SAFE_INTEGER)||a.evidence.source_text.localeCompare(b.evidence.source_text))
}
