import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowUp, ArrowUpRight, ChartNoAxesCombined, ChevronDown, FileText, Image as ImageIcon, LoaderCircle, PanelRightClose, Sigma, SlidersHorizontal, Table2 } from 'lucide-react'
import type { Answer, Evidence, PaperDetail, SavedConversation } from '../types'
import type { PdfSelection } from './PdfViewer'
import { api, errorMessage } from '../lib/api'
import { useUi, type LocaleKey } from '../lib/i18n'
import { ErrorBanner, Modal, SourceBadge } from './Shared'
import { ScientificText } from './ScientificText'
import { ResearchMarkdown } from './ResearchMarkdown'
import './explain-panel.css'
import { useConversation } from '../lib/useConversation'
import { ConversationHistory } from './ConversationHistory'
import { QuestionSource } from './QuestionSource'
import { selectionChunk } from '../lib/selectionSource'

type ContextScope = 'auto' | 'paragraph' | 'section' | 'full'
const normalize = (value: string) => value.replace(/\s+/g, ' ').trim()

function AnswerBlock({ answer, locate, close }: { answer: Answer; locate: (e: Evidence) => void; close: () => void }) {
  const { t } = useUi()
  const scopeLabel: LocaleKey = answer.context_scope === 'external' ? 'explainContextExternal' : answer.context_scope === 'full' ? 'explainContextFull' : answer.context_scope === 'related' ? 'explainContextRelated' : answer.context_scope === 'section' ? 'explainContextSection' : answer.context_scope === 'paragraph' ? 'explainContextParagraph' : 'explainContextAuto'
  const provenance = [
    { key: 'facts', label: t('explainFacts'), values: answer.facts ?? [], className: 'is-fact' },
    { key: 'inferences', label: t('explainInferences'), values: answer.inferences ?? [], className: 'is-inference' },
    { key: 'unknowns', label: t('explainUnknowns'), values: answer.unknowns ?? [], className: 'is-unknown' },
  ].filter(group => group.values.length > 0)
  return <div className="explain-answer">
    {answer.insufficient_evidence && <strong className="explain-no-answer">{t('noAnswer')}</strong>}
    <ResearchMarkdown text={answer.answer} className="explain-answer-text"/>
    <div className="explain-answer-foot">
      {provenance.length > 0 && <details className="explain-provenance">
        <summary><span>{t('explainProvenance')}</span><span className="explain-provenance-count">{provenance.reduce((count, group) => count + group.values.length, 0)}</span><ChevronDown size={12}/></summary>
        <div className="explain-provenance-list">
          {provenance.map(group => <section className={`explain-provenance-group ${group.className}`} key={group.key}>
            <h4>{group.label}</h4>
            <ul>{group.values.map((value, index) => <li key={`${group.key}-${index}`}>{value}</li>)}</ul>
          </section>)}
        </div>
      </details>}
      {answer.citations.length > 0 && <details className="explain-sources">
        <summary>{t('explainSources')}<span>{answer.citations.length}</span><ChevronDown size={12}/></summary>
        <div className="explain-source-list">{answer.citations.map(e => <article key={e.id} className="answer-citation">
          <header><SourceBadge source={e.source_type}/>{e.page != null && <span>{t('page')} {e.page}</span>}</header>
          <ScientificText text={e.source_text}/>
          {e.source_url ? <a className="text-btn" href={e.source_url} target="_blank" rel="noreferrer"><ArrowUpRight size={13}/>{t('openExternalSource')}</a> : e.page != null && <button className="text-btn" onClick={() => { locate(e); close() }}><ArrowUpRight size={13}/>{t('jump')} · {t('page')} {e.page}</button>}
        </article>)}</div>
      </details>}
      <details className="explain-answer-details">
        <summary>{t('explainResponseDetails')}<ChevronDown size={12}/></summary>
        <div><span>{answer.provider} · {answer.mode} · {t(scopeLabel)}</span>{answer.visual_used && <span><ImageIcon size={12}/>{t('explainVisualUsed')}</span>}</div>
      </details>
    </div>
  </div>
}

export interface ExplanationState { id:string|null; status:'running'|'completed'|'failed'|'interrupted'|null; question:string }
// Paper-wide discovery is separate from the hook's selection-specific auto-restore.
export interface ExplanationArchive { items:SavedConversation[]; hasMore:boolean; loading:boolean; error:string; select:(id:string)=>void; more:()=>void }

export function ExplainPanel({ paper, selection, visualPage, visualImage, close, locate, hidden=false, conversationId, savedContext, onState, archive }: { paper: PaperDetail; selection?: PdfSelection | null; visualPage?: number; visualImage?: string; close: () => void; locate: (e: Evidence) => void; hidden?:boolean; conversationId?:string; savedContext?:Record<string,unknown>; onState?:(state:ExplanationState)=>void; archive:ExplanationArchive }) {
  const { t } = useUi()
  const [busy, setBusy] = useState(false)
  const [pendingQuestion, setPendingQuestion] = useState('')
  const [error, setError] = useState('')
  const [question, setQuestion] = useState('')
  const [scope, setScope] = useState<ContextScope>('auto')
  const [external, setExternal] = useState(false)
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [contextOpen, setContextOpen] = useState(false)
  const alive = useRef(true)
  const busyRef = useRef(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const optionsRef = useRef<HTMLDivElement>(null)
  const [restoredImage, setRestoredImage] = useState('')
  const [imageError, setImageError] = useState('')
  const [imageAttempt, setImageAttempt] = useState(0)
  const image = visualImage || restoredImage
  const visual = Boolean(visualPage)
  const visualKind=selection?.visualKind??(savedContext?.visual_kind==='figure'||savedContext?.visual_kind==='table'||savedContext?.visual_kind==='equation'?savedContext.visual_kind:undefined)
  const visualLabel=selection?.visualLabel??(typeof savedContext?.visual_label==='string'?savedContext.visual_label:'')
  const sourceSelection = selection?.sourceText ?? selection?.text ?? (typeof savedContext?.selected_text==='string'?savedContext.selected_text:'')
  const selectionPage = selection?.page ?? (typeof savedContext?.page === 'number' ? savedContext.page : undefined)
  const translatedSelection = selection?.origin === 'translation' ? selection.text : typeof savedContext?.translated_text === 'string' ? savedContext.translated_text : ''
  const formulaImageOnly=visualKind==='equation'&&/[\uf000-\uf8ff\ufffd■]/.test(sourceSelection)
  const chunk = savedContext?.chunk_id
    ? paper.chunks.find(c => c.id === savedContext.chunk_id)
    : visual
    ? paper.chunks.find(c => c.page === visualPage)
    : selection
      ? selectionChunk(paper.chunks, sourceSelection, selectionPage)
      : undefined
  // A rendered page can be image-only, so visual questions do not require a
  // text chunk. Text questions still carry a verified page anchor.
  const hasContext = visual ? Boolean(image) : Boolean(sourceSelection && (chunk || selectionPage))
  const bbox=selection?.bbox??(Array.isArray(savedContext?.bbox)?savedContext.bbox as number[]:undefined)
  const context = savedContext ?? {page:visual?visualPage:selection?.page,chunk_id:visual?undefined:chunk?.id,selected_text:normalize(sourceSelection),...(visual&&bbox?{bbox}:{}),...(visualKind?{visual_kind:visualKind}:{}),...(visualLabel?{visual_label:visualLabel}:{}),visual,...(selection?.origin==='translation'?{translated_text:selection.text}:{})}
  const chat=useConversation<Answer>('explanation',paper.id,context,conversationId)
  const turns=chat.turns
  const hasConversation = turns.length > 0 || busy

  useEffect(() => { alive.current = true; inputRef.current?.focus(); return () => { alive.current = false } }, [])
  useEffect(()=>{if(!hidden&&!chat.loading)inputRef.current?.focus({preventScroll:true})},[chat.loading,hidden])
  const onStateRef=useRef(onState)
  onStateRef.current=onState
  const latest=turns.at(-1)
  const status=busy||chat.pending?'running':error?'failed':latest?.status??null
  const latestQuestion=pendingQuestion||latest?.question||''
  useEffect(()=>{onStateRef.current?.({id:chat.id,status,question:latestQuestion})},[chat.id,status,latestQuestion])
  // Page images are not stored in browser storage or the archive. Re-render
  // an archived page locally so visual follow-ups retain their original scope.
  useEffect(()=>{
    if(!visualPage||visualImage||restoredImage||hidden)return
    let active=true
    let task:import('pdfjs-dist').PDFDocumentLoadingTask|undefined
    setImageError('')
    void (async()=>{
      const {getDocument}=await import('pdfjs-dist')
      if(!active)return
      task=getDocument(`/api/papers/${encodeURIComponent(paper.id)}/pdf`)
      const pdf=await task.promise, page=await pdf.getPage(visualPage)
      const natural=page.getViewport({scale:1})
      const scale=Math.min(1.6,1600/natural.width)
      const viewport=page.getViewport({scale})
      const canvas=document.createElement('canvas')
      canvas.width=Math.ceil(viewport.width);canvas.height=Math.ceil(viewport.height)
      const canvasContext=canvas.getContext('2d')!
      await page.render({canvasContext,viewport,background:'#fff'}).promise
      let imageCanvas=canvas
      const bbox=selection?.bbox??(Array.isArray(savedContext?.bbox)?savedContext.bbox as number[]:undefined)
      if(bbox?.length===4&&bbox.every(Number.isFinite)){
        const canonical=page.getViewport({scale:1,rotation:0})
        const points=[[bbox[0],bbox[1]],[bbox[2],bbox[1]],[bbox[0],bbox[3]],[bbox[2],bbox[3]]].map(([x,y])=>{
          const [pdfX,pdfY]=canonical.convertToPdfPoint(x,y)
          return viewport.convertToViewportPoint(pdfX,pdfY)
        })
        const xs=points.map(point=>point[0]),ys=points.map(point=>point[1])
        const left=Math.max(0,Math.floor(Math.min(...xs))),top=Math.max(0,Math.floor(Math.min(...ys)))
        const right=Math.min(canvas.width,Math.ceil(Math.max(...xs))),bottom=Math.min(canvas.height,Math.ceil(Math.max(...ys)))
        if(right>left&&bottom>top){
          const crop=document.createElement('canvas')
          crop.width=right-left;crop.height=bottom-top
          crop.getContext('2d')?.drawImage(canvas,left,top,crop.width,crop.height,0,0,crop.width,crop.height)
          imageCanvas=crop
        }
      }
      if(active)setRestoredImage(imageCanvas.toDataURL('image/jpeg',.88))
    })().catch(e=>{if(active)setImageError(errorMessage(e))}).finally(()=>{void task?.destroy()})
    return()=>{active=false;void task?.destroy()}
  },[paper.id,visualPage,visualImage,restoredImage,hidden,imageAttempt])
  useEffect(() => {
    const input = inputRef.current
    if (input) { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 160)}px` }
  }, [question,hidden])
  useEffect(() => {
    if (!optionsOpen) return
    const dismiss = (event: PointerEvent) => { if (!optionsRef.current?.contains(event.target as Node)) setOptionsOpen(false) }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [optionsOpen])
  useEffect(() => {
    const transcript = transcriptRef.current
    if (!transcript) return
    // Keep the beginning of a new answer in view, even when it is several screens long.
    const latest = transcript.lastElementChild as HTMLElement | null
    transcript.scrollTop = busy ? transcript.scrollHeight : Math.max(0, (latest?.offsetTop ?? 0) - 20)
  }, [busy, turns.length,hidden])

  const ask = async () => {
    const trimmed = question.trim()
    if (!hasContext || busyRef.current || !trimmed || chat.loading || chat.pending) return
    busyRef.current = true
    setBusy(true)
    setPendingQuestion(trimmed)
    setOptionsOpen(false)
    setContextOpen(false)
    setError('')
    try {
      const conversation_id=await chat.ensure()
      // A submitted question must finish even if the reader leaves while the
      // conversation is being created. SQLite owns the eventual response.
      const result = await api.explain(paper.id, {
        conversation_id,request_id:crypto.randomUUID(),
        ...(visual ? { page: visualPage, image_data_url: image, ...(bbox?{bbox}:{}), ...(sourceSelection ? { selected_text: sourceSelection } : {}),...(visualKind?{visual_kind:visualKind}:{}),...(visualLabel?{visual_label:visualLabel}:{}) } : { page:selectionPage, chunk_id: savedContext?.chunk_id as string | undefined ?? chunk?.id, selected_text: sourceSelection, ...(translatedSelection ? { translated_text: translatedSelection } : {}) }),
        question: trimmed,
        style: 'technical',
        context_scope: scope,
        allow_external: external,
        history: turns.filter(turn=>turn.response).slice(-6).map(turn => ({ question: turn.question, answer: turn.response!.answer })),
      })
      if (alive.current) {
        chat.append(trimmed,result,result.turn_id)
        setQuestion(current => current.trim() === trimmed ? '' : current)
      }
    } catch (e) {
      if (alive.current) {setError(errorMessage(e));void chat.refresh()}
    } finally {
      busyRef.current = false
      if (alive.current) {
        setBusy(false)
        setPendingQuestion('')
        inputRef.current?.focus({ preventScroll: true })
      }
    }
  }
  const submit = (event: FormEvent) => { event.preventDefault(); void ask() }

  if(hidden)return null
  const visualTitle=visualKind==='equation'?t('askVisualEquation'):visualKind==='table'?t('askVisualTable'):visualKind==='figure'?t('askVisualFigure'):t('askVisualRegion')
  const visualContextLabel=visualKind==='equation'?t('explainVisualEquation'):visualKind==='table'?t('explainVisualTable'):visualKind==='figure'?t('explainVisualFigure'):t('explainVisualRegion')
  return <Modal title={visual ? visualTitle : t('explainSelection')} close={close} variant="drawer" className="ask-drawer-modal" headerActions={<button type="button" className="explain-minimize" aria-label={t('readingChatMinimize')} title={t('readingChatBackgroundHint')} onClick={close}><PanelRightClose size={15}/><span>{t('readingChatReadOn')}</span></button>}>
    <div className={`explain-panel${hasConversation ? ' has-conversation' : ' is-empty'}`}>
      <ConversationHistory items={archive.items} current={chat.id} loading={chat.loading||archive.loading} disabled={busy} hasMore={archive.hasMore} onMore={archive.more} onSelect={archive.select} onNew={()=>{setQuestion('');chat.newChat()}}/>
      {hasConversation && <div ref={transcriptRef} className="explain-transcript" role="log" aria-label={t('explainHistory')}>
        {turns.map((turn, index) => <article className="explain-turn" key={index}>
          <div className="explain-question"><QuestionSource context={chat.context} paper={paper} locate={source=>{locate(source);close()}}/><p className="explain-user-question">{turn.question}</p></div>
          {turn.response?<AnswerBlock answer={turn.response} locate={locate} close={close}/>:<div className="saved-turn-status">{turn.status==='running'?t('asking'):turn.error}{turn.status!=='running'&&<button type="button" onClick={()=>setQuestion(turn.question)}>{t('chatRetryQuestion')}</button>}</div>}
        </article>)}
        {busy && <article className="explain-turn explain-pending-turn"><div className="explain-question"><QuestionSource context={chat.context} paper={paper} locate={source=>{locate(source);close()}}/><p className="explain-user-question">{pendingQuestion}</p></div><div className="explain-thinking" role="status"><LoaderCircle size={15} className="spin"/>{t('explaining')}</div></article>}
      </div>}
      <div className="explain-composer">
        {!hasConversation && <p className="explain-paper-name" title={paper.title}>{paper.title}</p>}
        {!visual && !hasContext && <ErrorBanner error={t('selectionNoChunk')}/>}
        {imageError&&<ErrorBanner error={imageError} retry={()=>setImageAttempt(value=>value+1)}/>}
        {(error||chat.error||archive.error) && <ErrorBanner error={error||chat.error||archive.error}/>}
        <form className="explain-question-form" onSubmit={submit}>
          <details className="explain-context" open={contextOpen} onToggle={event => setContextOpen(event.currentTarget.open)}>
            <summary className="explain-context-toggle">
              {visual ? visualKind==='equation'?<Sigma size={15}/>:visualKind==='table'?<Table2 size={15}/>:<ChartNoAxesCombined size={15}/> : <FileText size={15}/>}
              <span className="explain-context-label">{visual ? visualContextLabel : t('selectedPassage')}{visualLabel&&<span> · {visualLabel}</span>}<span> · {t('page')} {visual ? visualPage : selectionPage}</span></span>
              {sourceSelection && <span className="explain-context-excerpt">{formulaImageOnly?t('equationImageSource'):translatedSelection || sourceSelection}</span>}
              <ChevronDown className="explain-context-chevron" size={14}/>
            </summary>
            {visual ? image ? <><figure className="explain-page-preview"><img src={image} alt={t('explainVisualPreview')}/></figure>{formulaImageOnly?<p className="explain-selection-quote">{t('equationImageSource')}</p>:sourceSelection && <ScientificText text={sourceSelection} className="explain-selection-quote"/>}</> : <p className="explain-restoring-page"><LoaderCircle size={14} className="spin"/>{t('loading')}</p> : <>
              <ScientificText text={translatedSelection || sourceSelection} className="explain-selection-quote"/>
              {translatedSelection && <div className="explain-selection-source"><span>{t('translationSource')}</span><ScientificText text={sourceSelection} /></div>}
            </>}
          </details>
          <textarea ref={inputRef} disabled={chat.loading} aria-label={t('explainQuestion')} value={question} onChange={event => setQuestion(event.target.value)} placeholder={t(hasConversation ? 'explainFollowUp' : visual ? 'explainVisualQuestionPlaceholder' : 'explainQuestionPlaceholder')} rows={2} onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) { event.preventDefault(); void ask() }
          }}/>
          <div className="explain-composer-tools">
            <div ref={optionsRef} className="explain-options" onKeyDown={event => { if (event.key === 'Escape' && optionsOpen) { event.stopPropagation(); setOptionsOpen(false); optionsRef.current?.querySelector('button')?.focus() } }}>
              <button className={`explain-options-toggle${scope !== 'auto' || external ? ' is-custom' : ''}`} type="button" aria-label={t('explainOptions')} aria-expanded={optionsOpen} onClick={() => { if (!optionsOpen) setContextOpen(false); setOptionsOpen(!optionsOpen) }}><SlidersHorizontal size={15}/><span>{t('explainOptions')}</span></button>
              {optionsOpen && <div className="explain-options-popover">
                <label><span>{t('explainContext')}</span><select aria-label={t('explainContext')} value={scope} onChange={event => setScope(event.target.value as ContextScope)}><option value="auto">{t('explainContextAuto')}</option><option value="paragraph">{t('explainContextParagraph')}</option><option value="section">{t('explainContextSection')}</option><option value="full">{t('explainContextFull')}</option></select></label>
                <label className="explain-web-option"><span>{t('explainAllowExternal')}</span><input type="checkbox" checked={external} onChange={event => setExternal(event.target.checked)}/></label>
              </div>}
            </div>
            <button className="explain-submit" type="submit" aria-label={t('explainAsk')} title={t('explainAsk')} disabled={!hasContext || busy || !question.trim()||chat.loading||chat.pending}>{busy ? <LoaderCircle size={17} className="spin"/> : <ArrowUp size={19}/>}</button>
          </div>
        </form>
        <p className="explain-keyboard-hint">{t('explainSendHint')}</p>
      </div>
    </div>
  </Modal>
}
