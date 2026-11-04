import { useId, useLayoutEffect, useRef, useState } from 'react'
import { ArrowUpRight, ChevronDown, Quote } from 'lucide-react'
import type { Evidence, PaperDetail } from '../types'
import { useUi } from '../lib/i18n'
import { ScientificText } from './ScientificText'

/** The source belongs to the saved conversation, never to the reader's current selection. */
export function QuestionSource({context,paper,locate}:{context:Record<string,unknown>;paper:PaperDetail;locate:(source:Evidence)=>void}) {
  const {t}=useUi()
  const [expanded,setExpanded]=useState(false)
  const [truncated,setTruncated]=useState(false)
  const contentRef=useRef<HTMLDivElement>(null)
  const contentId=useId()
  const original=typeof context.selected_text==='string'?context.selected_text:''
  const translated=typeof context.translated_text==='string'?context.translated_text:''
  const text=context.visual_kind==='equation'&&/[\uf000-\uf8ff\ufffd■]/.test(original)?t('equationImageSource'):translated||original
  const label=typeof context.visual_label==='string'?context.visual_label:''
  const chunk=paper.chunks.find(item=>item.id===context.chunk_id)
  const page=typeof context.page==='number'?context.page:chunk?.page
  useLayoutEffect(()=>{
    if(expanded)return
    const quote=contentRef.current?.querySelector<HTMLElement>('.question-source-quote')
    if(!quote)return
    const measure=()=>setTruncated(quote.scrollHeight>quote.clientHeight+1)
    measure()
    const observer=new ResizeObserver(measure)
    observer.observe(quote)
    return()=>observer.disconnect()
  },[text,expanded])
  if(!text&&!label)return null
  const expandable=truncated||!!translated||expanded
  const bbox=context.visual&&Array.isArray(context.bbox)&&context.bbox.length===4&&context.bbox.every(Number.isFinite)?context.bbox as number[]:null
  const source:Evidence={id:'question-selection',claim:'',source_text:original,page:page??null,section:chunk?.section??null,confidence:1,source_type:'paper',chunk_id:chunk?.id,bbox}
  return <aside className={'question-source'+(expanded?' is-expanded':'')} aria-label={t('questionSource')}>
    <div className="question-source-head"><span><Quote size={12}/>{label||t('questionSource')}{page!=null&&<span> · {t('page')} {page}</span>}</span>
      {page!=null&&<button type="button" aria-label={t('questionSourceLocate')} onClick={()=>locate(source)}>{t('jump')}<ArrowUpRight size={12}/></button>}
    </div>
    <div id={contentId} ref={contentRef}>
      {text&&<ScientificText text={text} className="question-source-quote"/>}
      {expanded&&translated&&original&&<div className="question-source-original"><span>{t('translationSource')}</span><ScientificText text={original}/></div>}
    </div>
    {expandable&&<button type="button" className="question-source-expand" aria-expanded={expanded} aria-controls={contentId} onClick={()=>setExpanded(value=>!value)}>{t(expanded?'questionSourceCollapse':'questionSourceExpand')}<ChevronDown size={12}/></button>}
  </aside>
}
