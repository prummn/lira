import { useState } from 'react'
import { ArrowUpRight, Check, LoaderCircle, Pencil, RotateCcw, X } from 'lucide-react'
import type { KnowledgeCandidate, KnowledgeEvidence } from '../types'
import { useUi } from '../lib/i18n'
import { roleLabel, statusLabel, typeLabel } from '../lib/knowledgeLabels'
import { ScientificText } from './ScientificText'
import { readableQuote, settled } from '../lib/knowledgeReview'

export type CandidateEdits = {name:string;description:string}
export function KnowledgeCandidateCard({item,busy=false,saving=false,paperTitle,selected,onSelect,onDecide,onLocate,onEntitySelect}: {
  item:KnowledgeCandidate;busy?:boolean;saving?:boolean;paperTitle?:string;selected?:boolean;onSelect?:(checked:boolean)=>void
  onDecide:(decision:'confirm'|'reject',edits?:CandidateEdits)=>Promise<boolean>
  onLocate:(evidence:KnowledgeEvidence)=>void;onEntitySelect?:(id:string,name:string)=>void
}) {
  const {t}=useUi()
  const [editing,setEditing]=useState(false)
  const [name,setName]=useState(item.name)
  const [description,setDescription]=useState(item.description??'')
  const accepted=settled(item.status)
  const pending=!accepted&&item.status!=='rejected'
  const context=item.conflict._steward_context as {verdict?:string;reason?:string}|undefined
  return <article className={`knowledge-candidate intake-candidate candidate-${item.status}${selected?' is-selected':''}`} aria-busy={saving}>
    <div className="intake-candidate-heading">
      {onSelect&&pending&&<input type="checkbox" checked={!!selected} disabled={busy} aria-label={`${t('select')} ${item.name}`} onChange={e=>onSelect(e.target.checked)}/>}
      <div className="intake-candidate-name">{item.entity_id&&onEntitySelect?<button onClick={()=>onEntitySelect(item.entity_id!,item.name)}>{item.name}<ArrowUpRight size={13}/></button>:<strong>{item.name}</strong>}</div>
      <span className={`intake-status status-${item.status}`}>{t(statusLabel(item.status))}</span>
    </div>
    <div className="intake-candidate-meta"><span>{t(typeLabel(item.entity_type))}</span><span>{t(roleLabel(item.role))}</span>{paperTitle&&<span className="intake-source-paper">{paperTitle}</span>}</div>
    {item.aliases.length>0&&<div className="intake-aliases">{item.aliases.join(' · ')}</div>}
    {editing?<form className="curation-fields intake-edit" onSubmit={async e=>{e.preventDefault();if(await onDecide('confirm',{name:name.trim(),description}))setEditing(false)}}>
      <label>{t('kName')}<input required maxLength={300} value={name} disabled={busy} onChange={e=>setName(e.target.value)}/></label>
      <label>{t('kDescription')}<textarea rows={4} maxLength={8000} value={description} disabled={busy} onChange={e=>setDescription(e.target.value)}/></label>
      <div className="curation-form-actions"><button className="btn primary" disabled={busy||!name.trim()}>{saving&&<LoaderCircle size={13} className="spin"/>}{t('kSaveAndConfirm')}</button><button type="button" className="btn secondary" disabled={busy} onClick={()=>setEditing(false)}>{t('cancel')}</button></div>
    </form>:<>
      {item.description&&<ScientificText className="intake-definition" text={item.description}/>}
      {context?.reason&&<p className="intake-context"><strong>{t('kContextExample')}</strong>{context.reason}</p>}
      <details className="intake-evidence"><summary>{t('kReadSource')}<span>{item.evidence.length}</span></summary><div>{item.evidence.map((e,index)=><button key={`${e.chunk_id}-${index}`} onClick={()=>onLocate(e)}><span>{e.section||t('viewSource')} · p.{e.page??'—'}<ArrowUpRight size={13}/></span><blockquote><ScientificText text={readableQuote(e.quote)}/></blockquote></button>)}</div></details>
      <footer className="intake-candidate-actions">
        {accepted&&context?.reason&&<button className="text-btn intake-confirm" disabled={busy} onClick={()=>void onDecide('confirm')}>{saving?<LoaderCircle size={13} className="spin"/>:<Check size={13}/>} {t('kKeepResearchObject')}</button>}
        {!accepted&&<button className="text-btn intake-confirm" disabled={busy} onClick={()=>void onDecide('confirm')}>{saving?<LoaderCircle size={13} className="spin"/>:item.status==='rejected'?<RotateCcw size={13}/>:<Check size={13}/>} {t(item.status==='rejected'?'kRestore':'confirm')}</button>}
        {pending&&<button className="text-btn" disabled={busy} onClick={()=>{setName(item.name);setDescription(item.description??'');setEditing(true)}}><Pencil size={12}/>{t('kEditBeforeConfirm')}</button>}
        {item.status!=='rejected'&&<button className="text-btn intake-ignore" disabled={busy} onClick={()=>void onDecide('reject')}><X size={12}/>{t('reject')}</button>}
      </footer>
    </>}
  </article>
}
