import { useEffect, useRef, useState } from 'react'
import { ArrowUp, LoaderCircle, Square } from 'lucide-react'
import type { Answer, HistoryItem, LibraryAnswer, LibraryCitation, PaperDetail } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { IntelligenceAnswer } from './IntelligenceAnswer'
import { ErrorBanner } from './Shared'
import './paper-question.css'
import { useConversation } from '../lib/useConversation'
import { ConversationHistory } from './ConversationHistory'

function localAnswer(result: Answer, paper: PaperDetail): LibraryAnswer {
  const citations: LibraryCitation[] = result.citations.map(c => ({ ...c, paper_id: paper.id, title: paper.title,
    source_id: c.chunk_id ?? c.id, source_type: 'paper' }))
  return { ...result, citations, items: citations.length ? [{ content: result.answer, kind: 'fact', citations }] : [],
    limitations: [], retrieved_paper_ids: [paper.id], queries: [], coverage: {}, usage: {}, cached: false }
}

export function PaperQuestion({ paper, page, remote, active, onCitation }: {
  paper: PaperDetail; page: number; remote: boolean; active: boolean; onCitation: (citation: LibraryCitation) => void
}) {
  const { t } = useUi()
  const [draft,setDraft] = useState('')
  const chat=useConversation<LibraryAnswer|Answer>('paper',paper.id,{})
  const turns=chat.turns.map(turn=>({...turn,response:turn.response&&('items' in turn.response?turn.response:localAnswer(turn.response,paper))}))
  const [pending,setPending] = useState('')
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  const generation = useRef(0)
  const busyRef = useRef(false)
  const controller = useRef<AbortController>()
  const input = useRef<HTMLTextAreaElement>(null)
  const transcript = useRef<HTMLDivElement>(null)
  useEffect(()=>()=>{generation.current++;controller.current?.abort()},[])
  useEffect(()=>{if(active&&!chat.loading)input.current?.focus({preventScroll:true})},[active,chat.loading])
  useEffect(()=>{
    const element=input.current
    if(element){element.style.height='auto';element.style.height=`${Math.min(element.scrollHeight,140)}px`}
  },[draft])
  useEffect(()=>{
    const element=transcript.current
    if(element){const latest=element.lastElementChild as HTMLElement|null;element.scrollTop=busy?element.scrollHeight:Math.max(0,(latest?.offsetTop??0)-22)}
  },[busy,turns.length])
  const stop=()=>{generation.current++;controller.current?.abort();busyRef.current=false;setBusy(false);setPending('');void chat.refresh();input.current?.focus()}
  const ask=async()=>{
    const question=draft.trim()
    if(!question||busyRef.current||chat.loading||chat.pending)return
    const token=++generation.current
    busyRef.current=true;setBusy(true);setPending(question);setError('')
    controller.current=new AbortController()
    try{
      const history:HistoryItem[]=turns.filter(turn=>turn.response).slice(-4).flatMap(turn=>[
        {role:'user' as const,content:turn.question.slice(0,4000)},
        {role:'assistant' as const,content:turn.response!.answer.slice(0,6000)}])
      const conversation_id=await chat.ensure()
      if(generation.current!==token)return
      const identity={conversation_id,request_id:crypto.randomUUID()}
      const result=remote?await api.librarian({question,paper_ids:[paper.id],history,reading_page:page,conversation_kind:'paper',...identity},controller.current.signal)
        :localAnswer(await api.ask(paper.id,question,identity,controller.current.signal),paper)
      if(generation.current===token){chat.append(question,result,result.turn_id);setDraft(current=>current.trim()===question?'':current)}
    }catch(e){if(generation.current===token&&(e as Error).name!=='AbortError'){setError(errorMessage(e));void chat.refresh()}}
    finally{if(generation.current===token){busyRef.current=false;setBusy(false);setPending('');if(active)input.current?.focus({preventScroll:true})}}
  }
  const hasConversation=turns.length>0||busy
  return <div className={`ask-panel paper-question${hasConversation?' has-conversation':' is-empty'}`} hidden={!active}>
    <ConversationHistory items={chat.items} current={chat.id} loading={chat.loading} hasMore={chat.hasMore} onMore={()=>void chat.more()} onSelect={id=>{stop();setDraft('');void chat.select(id)}} onNew={()=>{stop();setDraft('');chat.newChat()}}/>
    {hasConversation&&<div className="paper-question-transcript" ref={transcript} aria-label={t('explainHistory')}>
      {turns.map((turn,index)=><article className="paper-question-turn" key={index}>
        <p className="paper-question-user">{turn.question}</p>
        {turn.response?<div className="ask-answer"><IntelligenceAnswer answer={turn.response} onCitation={onCitation}/></div>:<div className="saved-turn-status">{turn.status==='running'?t('asking'):turn.error}<button type="button" disabled={turn.status==='running'} onClick={()=>setDraft(turn.question)}>{turn.status!=='running'&&t('chatRetryQuestion')}</button></div>}
      </article>)}
      {busy&&<article className="paper-question-turn"><p className="paper-question-user">{pending}</p><div className="paper-question-thinking" role="status"><LoaderCircle size={15} className="spin"/>{t('asking')}</div></article>}
    </div>}
    <div className="paper-question-composer">
      {!hasConversation&&<p className="paper-question-context">{paper.title}</p>}
      {(error||chat.error)&&<ErrorBanner error={error||chat.error}/>}
      <form className="ask-form paper-question-form" onSubmit={event=>{event.preventDefault();void ask()}}>
        <textarea ref={input} disabled={chat.loading} aria-label={t('ask')} placeholder={t(hasConversation?'explainFollowUp':'explainQuestionPlaceholder')} value={draft} onChange={event=>setDraft(event.target.value)} rows={2} onKeyDown={event=>{
          if(event.key==='Enter'&&!event.shiftKey&&!event.nativeEvent.isComposing&&event.nativeEvent.keyCode!==229){event.preventDefault();void ask()}
        }}/>
        <div className="paper-question-tools"><span>{t('askPaperContext')}</span>{busy?<button type="button" className="paper-question-stop" onClick={stop} aria-label={t('cancelRequest')} title={t('cancelRequest')}><Square size={13}/></button>:<button type="submit" className="paper-question-send" disabled={!draft.trim()||chat.loading||chat.pending} aria-label={t('send')} title={t('send')}><ArrowUp size={18}/></button>}</div>
      </form>
    </div>
  </div>
}
