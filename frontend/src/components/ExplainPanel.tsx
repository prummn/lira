import { useEffect, useRef, useState } from 'react'
import { Link2, LoaderCircle } from 'lucide-react'
import type { Answer, Evidence, ExplainStyle, PaperDetail } from '../types'
import type { PdfSelection } from './PdfViewer'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { ErrorBanner, Modal, SourceBadge } from './Shared'

const styles=[['technical','explainTechnical'],['simple','explainSimple'],['mathematical','explainMathematical'],['prerequisites','explainPrerequisites']] as const
const normalize=(value:string)=>value.replace(/\s+/g,' ').trim()
export function ExplainPanel({paper,selection,close,locate}:{paper:PaperDetail;selection:PdfSelection;close:()=>void;locate:(e:Evidence)=>void}) {
  const {t}=useUi()
  const [busy,setBusy]=useState<ExplainStyle|null>(null)
  const [answer,setAnswer]=useState<Answer|null>(null)
  const [error,setError]=useState('')
  const alive=useRef(true)
  useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[])
  const chunk=paper.chunks.find(c=>c.page===selection.page&&normalize(c.content).includes(normalize(selection.text)))
  const explain=async(style:ExplainStyle)=>{
    if(!chunk||busy)return
    setBusy(style);setError('');setAnswer(null)
    try{const result=await api.explain(paper.id,{chunk_id:chunk.id,selected_text:selection.text,style});if(alive.current)setAnswer(result)}
    catch(e){if(alive.current)setError(errorMessage(e))}finally{if(alive.current)setBusy(null)}
  }
  return <Modal title={t('explainSelection')} close={close}><div className="explain-panel"><p className="capability-notice">{t('explainHint')}</p><blockquote>{selection.text}</blockquote><div className="explain-styles" role="group" aria-label={t('explainStyle')}>{styles.map(([style,label])=><button key={style} className="btn secondary" disabled={!chunk||!!busy} onClick={()=>void explain(style)}>{busy===style&&<LoaderCircle size={13} className="spin"/>}{t(label)}</button>)}</div>{!chunk&&<ErrorBanner error={t('selectionNoChunk')}/>} {error&&<ErrorBanner error={error}/>}{answer&&<div className="ask-answer" role="status"><span className="provider-line">{answer.provider} · {answer.mode}</span>{answer.insufficient_evidence&&<strong>{t('noAnswer')}</strong>}<p>{answer.answer}</p>{answer.citations.map(e=><article key={e.id} className="answer-citation"><SourceBadge source={e.source_type}/><blockquote>{e.source_text}</blockquote><button className="text-btn" onClick={()=>{locate(e);close()}}><Link2 size={12}/>{t('jump')} · {t('page')} {e.page}</button></article>)}</div>}</div></Modal>
}
