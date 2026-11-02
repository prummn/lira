import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, BookOpen, ChevronDown, LoaderCircle, Square } from 'lucide-react'
import type { HistoryItem, LibrarianThread, LibraryAnswer, LibraryCitation, NotebookTab, Paper } from '../types'
import type { PdfLocator } from '../components/PdfViewer'
import type { Workspace } from '../lib/useWorkspace'
import { useUi } from '../lib/i18n'
import { api, errorMessage } from '../lib/api'
import { remoteAvailable } from '../lib/intelligence'
import { ErrorBanner } from '../components/Shared'
import { IntelligenceAnswer, type AnswerSourceSelection } from '../components/IntelligenceAnswer'
import { MetadataDialog } from '../components/MetadataDialog'
import { useConversation } from '../lib/useConversation'
import { ConversationHistory } from '../components/ConversationHistory'
import { LibrarianScopeDialog } from '../components/LibrarianScopeDialog'
import { LibrarianCoverageNote, LibrarianSources } from '../components/LibrarianSources'
import './librarian.css'

export function LibrarianPage({ workspace, thread, setThread, openPaper, openSettings }: {
  workspace: Workspace; thread: LibrarianThread; setThread: (thread: LibrarianThread) => void
  openPaper: (id: string, locator?: PdfLocator, tab?: NotebookTab) => void; openSettings: () => void
}) {
  const { t } = useUi()
  const [question, setQuestion] = useState('')
  const [pending, setPending] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [metadata, setMetadata] = useState<Paper | null>(null)
  const [scopeOpen, setScopeOpen] = useState(false)
  const [away, setAway] = useState(false)
  const [sourceSelections, setSourceSelections] = useState<Record<string, AnswerSourceSelection | null>>({})
  const returnPosition = useRef<{top:number;details:boolean[]}|null>(null)
  const generation = useRef(0)
  const busyRef = useRef(false)
  const controller = useRef<AbortController>()
  const input = useRef<HTMLTextAreaElement>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const restored = useRef<string | null>()
  const available = remoteAvailable(workspace.settings)
  const scoped = useMemo(() => workspace.papers.filter(paper => !paper.is_demo && (thread.scope === 'selected'
    ? thread.selectedIds.includes(paper.id) : !thread.scope || paper.collection_ids.includes(thread.scope))), [workspace.papers, thread.scope, thread.selectedIds])
  const scopeKey = thread.scope + '|' + scoped.map(paper => paper.id).sort().join(',')
  const chat = useConversation<LibraryAnswer>('librarian', undefined, thread.scope === 'selected'
    ? { paper_ids: scoped.map(paper => paper.id).sort() } : thread.scope ? { collection_id: thread.scope } : {})
  const turns = chat.turns
  const hasConversation = turns.length > 0 || busy
  const scopeName = thread.scope === 'selected' ? t('librarianSelected')
    : thread.scope ? workspace.collections.find(collection => collection.id === thread.scope)?.name ?? t('librarianScope') : t('librarianAll')

  useEffect(() => {
    generation.current++; controller.current?.abort(); busyRef.current = false; setBusy(false); setPending('')
    return () => { generation.current++; controller.current?.abort(); busyRef.current = false }
  }, [scopeKey])
  const focusComposer = () => { if (!document.querySelector('[role="dialog"]')) input.current?.focus({ preventScroll: true }) }
  useEffect(() => { if (!chat.loading) focusComposer() }, [chat.loading])
  useEffect(() => {
    const element = input.current
    if (element) { element.style.height = 'auto'; element.style.height = `${Math.min(element.scrollHeight, 150)}px` }
  }, [question])
  const latestQuestion = () => transcript.current?.querySelector<HTMLElement>('.librarian-turn:last-child')
  const goToLatest = () => {
    const element = transcript.current, latest = latestQuestion()
    if (element && latest) element.scrollTop = Math.max(0, latest.offsetTop - 28)
    setAway(false)
  }
  useEffect(() => {
    if (chat.loading || !transcript.current) return
    if (restored.current !== chat.id) {
      restored.current = chat.id
      if (chat.id) try {
        const key = `riw-librarian-source-view:${chat.id}`, saved = sessionStorage.getItem(key)
        sessionStorage.removeItem(key)
        if (saved !== null) {
          const view=JSON.parse(saved)
          if (Number.isFinite(view.top) && Array.isArray(view.details) && view.sources && typeof view.sources==='object') {
            returnPosition.current={top:Math.max(0,view.top),details:view.details}
            setSourceSelections(view.sources)
            return
          }
        }
      } catch { /* The saved conversation is available even without browser storage. */ }
    }
    goToLatest()
  }, [chat.loading, chat.id, busy, turns.length])
  useLayoutEffect(() => {
    const view=returnPosition.current, element=transcript.current
    if (!view || !element) return
    element.querySelectorAll('details').forEach((detail,index)=>{detail.open=!!view.details[index]})
    element.scrollTop=view.top
    returnPosition.current=null
  }, [sourceSelections])

  const cancelActive = () => {
    generation.current++; controller.current?.abort(); busyRef.current = false; setBusy(false); setPending('')
  }
  const stop = () => { cancelActive(); setNotice(t('librarianStopped')); void chat.refresh(); input.current?.focus({ preventScroll: true }) }
  const changeScope = (scope: string, selectedIds: string[]) => {
    cancelActive(); setError(''); setNotice(''); setScopeOpen(false)
    setThread({ scope, selectedIds, turns: [] })
  }
  const ask = async () => {
    const value = question.trim()
    if (!value || busyRef.current || !available || !scoped.length || chat.loading || chat.pending) return
    if (thread.scope === 'selected' && scoped.length > 50) { setError(t('librarianSelectionLimit')); return }
    const token = ++generation.current
    const history: HistoryItem[] = turns.filter(turn => turn.response).slice(-4).flatMap(turn => [
      { role: 'user' as const, content: turn.question.slice(0, 4000) },
      { role: 'assistant' as const, content: turn.response!.answer.slice(0, 6000) },
    ])
    const abort = new AbortController()
    controller.current = abort; busyRef.current = true; setBusy(true); setPending(value); setError(''); setNotice('')
    try {
      const scope = thread.scope === 'selected' ? { paper_ids: scoped.map(paper => paper.id) } : thread.scope ? { collection_id: thread.scope } : {}
      const conversation_id = await chat.ensure()
      if (generation.current !== token) return
      const response = await api.librarian({ question: value, ...scope, history, conversation_id, request_id: crypto.randomUUID() }, abort.signal)
      if (generation.current !== token) return
      chat.append(value, response, response.turn_id)
      setQuestion(current => current.trim() === value ? '' : current)
    } catch (failure) {
      if (generation.current === token && (failure as Error).name !== 'AbortError') { setError(errorMessage(failure)); void chat.refresh() }
    } finally {
      if (generation.current === token) { busyRef.current = false; setBusy(false); setPending(''); focusComposer() }
    }
  }
  const citation = (item: LibraryCitation) => {
    if (item.source_type === 'external_metadata') { setMetadata(workspace.papers.find(paper => paper.id === item.paper_id) ?? null); return }
    if (chat.id && transcript.current) try {
      sessionStorage.setItem(`riw-librarian-source-view:${chat.id}`, JSON.stringify({top:transcript.current.scrollTop,
        sources:sourceSelections,details:Array.from(transcript.current.querySelectorAll('details'),detail=>detail.open)}))
    } catch { /* optional */ }
    const locator = item.page == null ? undefined : { page: item.page, source_text: item.source_text, bbox: item.bbox, page_width: item.page_width, page_height: item.page_height }
    openPaper(item.paper_id, locator, item.source_type === 'user' ? 'notes' : 'overview')
  }

  return <div className={`librarian-page${hasConversation ? ' has-conversation' : ' is-empty'}`}>
    <header className="librarian-toolbar"><h1>{t('librarian')}</h1>
      <ConversationHistory items={chat.items} current={chat.id} loading={chat.loading} hasMore={chat.hasMore} onMore={() => void chat.more()}
        onSelect={id => { cancelActive(); setQuestion(''); setError(''); setNotice(''); void chat.select(id) }}
        onNew={() => { cancelActive(); setQuestion(''); setError(''); setNotice(''); chat.newChat(); input.current?.focus({ preventScroll: true }) }}/>
    </header>
    <section className="librarian-dialogue" aria-label={t('librarianTitle')}>
      {hasConversation ? <div className="librarian-conversation" ref={transcript} aria-label={t('explainHistory')} onScroll={() => {
        const element = transcript.current, latest = latestQuestion()
        setAway(!!element && !!latest && latest.offsetTop > element.scrollTop + element.clientHeight)
      }}><div className="librarian-reading-column">
        {turns.map(turn => <article className="librarian-turn" key={turn.id}>
          <p className="librarian-user-question">{turn.question}</p>
          {turn.response ? <div className="librarian-answer"><IntelligenceAnswer answer={turn.response} onCitation={citation} showSourceTitles
            sourceSelection={sourceSelections[turn.id]??null} onSourceSelection={source=>setSourceSelections(previous=>({...previous,[turn.id]:source}))}/>
            <LibrarianCoverageNote answer={turn.response}/><LibrarianSources answer={turn.response} onCitation={citation}/></div>
            : <div className="saved-turn-status" role="status">{turn.status === 'running' ? t('librarianBackground') : turn.error}
              {turn.status !== 'running' && <button type="button" onClick={() => { setQuestion(turn.question); input.current?.focus() }}>{t('chatRetryQuestion')}</button>}</div>}
        </article>)}
        {busy && <article className="librarian-turn"><p className="librarian-user-question">{pending}</p>
          <div className="librarian-pending" role="status"><LoaderCircle className="spin" size={16}/>{t('asking')}</div></article>}
      </div></div> : <div className="librarian-welcome"><h2>{t(scoped.length ? 'librarianTitle' : 'librarianNoPapers')}</h2>
        <p>{t(scoped.length ? 'librarianWelcomeHint' : 'librarianNoPapersHint')}</p></div>}
      <div className="librarian-composer">
        {away && <button type="button" className="librarian-latest" onClick={goToLatest}>{t('librarianLatest')}<ArrowDown size={13}/></button>}
        {(error || chat.error) && <ErrorBanner error={error || chat.error} retry={() => void ask()}/>}
        {notice && <p className="librarian-notice" role="status">{notice}</p>}
        {!available && <p className="librarian-capability-notice">{t('librarianNeedsConnection')}<button type="button" onClick={openSettings}>{t('settings')}</button></p>}
        <form className="librarian-form" onSubmit={event => { event.preventDefault(); void ask() }}>
          <textarea ref={input} aria-label={t('librarianQuestion')} disabled={chat.loading} maxLength={4000} rows={2} value={question}
            onChange={event => setQuestion(event.target.value)} placeholder={t(hasConversation ? 'explainFollowUp' : 'librarianPlaceholder')}
            onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) { event.preventDefault(); void ask() } }}/>
          <footer><button type="button" className="librarian-scope-trigger" aria-label={t('librarianScope')} aria-haspopup="dialog" onClick={() => setScopeOpen(true)}>
            <BookOpen size={14}/><span>{scopeName}</span><span className="librarian-scope-count">{scoped.length}</span><ChevronDown size={12}/></button>
            {busy ? <button type="button" className="librarian-send" onClick={event=>{event.preventDefault();stop()}} aria-label={t('librarianStop')}><Square size={13}/></button>
              : <button type="submit" className="librarian-send" disabled={!available || !scoped.length || !question.trim() || chat.loading || chat.pending} aria-label={t('send')}><ArrowUp size={19}/></button>}
          </footer>
        </form>
        {!hasConversation && <p className="librarian-save-hint">{t('librarianThreadHint')}</p>}
      </div>
    </section>
    {scopeOpen && <LibrarianScopeDialog papers={workspace.papers} collections={workspace.collections} scope={thread.scope} selectedIds={thread.selectedIds} close={() => setScopeOpen(false)} apply={changeScope}/>}
    {metadata && <MetadataDialog paper={metadata} close={() => setMetadata(null)} saved={workspace.reload}/>}
  </div>
}
