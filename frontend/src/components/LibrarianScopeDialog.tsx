import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import type { Collection, Paper } from '../types'
import { useUi } from '../lib/i18n'
import { Modal } from './Shared'

export function LibrarianScopeDialog({ papers, collections, scope: currentScope, selectedIds, close, apply }: {
  papers: Paper[]; collections: Collection[]; scope: string; selectedIds: string[]
  close: () => void; apply: (scope: string, ids: string[]) => void
}) {
  const { t } = useUi()
  const realPapers = useMemo(() => papers.filter(paper => !paper.is_demo), [papers])
  const [scope, setScope] = useState(currentScope)
  const [selected, setSelected] = useState(() => new Set(selectedIds.filter(id => realPapers.some(paper => paper.id === id))))
  const [query, setQuery] = useState('')
  const [selectedOnly, setSelectedOnly] = useState(false)
  const [limit, setLimit] = useState(60)
  const deferredQuery = useDeferredValue(query)
  const content = useRef<HTMLDivElement>(null)
  const select = useRef<HTMLSelectElement>(null)
  const words = deferredQuery.normalize('NFKC').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  const filtered = realPapers.filter(paper => {
    if (selectedOnly && !selected.has(paper.id)) return false
    const text = [paper.title, ...paper.authors, paper.year, paper.venue, ...paper.tags].join(' ').normalize('NFKC').toLocaleLowerCase()
    return words.every(word => text.includes(word))
  })
  const inScope = scope === 'selected' ? realPapers.filter(paper => selected.has(paper.id))
    : scope ? realPapers.filter(paper => paper.collection_ids.includes(scope)) : realPapers

  useEffect(() => { setLimit(60) }, [deferredQuery, selectedOnly])
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const dialog = content.current?.closest('[role="dialog"]')
    const trap = (event: Event) => {
      const key = event as KeyboardEvent
      if (key.key !== 'Tab' || !dialog) return
      const elements = Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select, [tabindex="0"]'))
        .filter(element => element.getClientRects().length)
      const first = elements[0], last = elements.at(-1)
      if (key.shiftKey && document.activeElement === first) { key.preventDefault(); last?.focus() }
      else if (!key.shiftKey && document.activeElement === last) { key.preventDefault(); first?.focus() }
    }
    select.current?.focus()
    dialog?.addEventListener('keydown', trap)
    return () => { dialog?.removeEventListener('keydown', trap); if (opener?.isConnected) opener.focus({ preventScroll: true }) }
  }, [])

  return <Modal title={t('librarianScope')} close={close} className="librarian-scope-dialog">
    <div ref={content} className="librarian-scope-content">
      <label className="librarian-scope-kind">{t('librarianScope')}
        <select ref={select} aria-label={t('librarianScope')} value={scope} onChange={event => setScope(event.target.value)}>
          <option value="">{t('librarianAll')}</option>
          {collections.map(collection => <option value={collection.id} key={collection.id}>{collection.name}</option>)}
          <option value="selected">{t('librarianSelected')}</option>
        </select>
      </label>
      {scope === 'selected' ? <>
        <div className="librarian-scope-selection-head">
          <span>{selected.size} / 50 <span>{t('paperCount')}</span></span>
          <div><button type="button" aria-pressed={selectedOnly} onClick={() => setSelectedOnly(!selectedOnly)}>{t('librarianSelectedOnly')}</button>
            <button type="button" disabled={!selected.size} onClick={() => setSelected(new Set())}>{t('librarianClearSelection')}</button></div>
        </div>
        <label className="librarian-scope-search"><Search size={16}/><input type="search" aria-label={t('librarianFindPaper')}
          placeholder={t('librarianFindPaperHint')} value={query} onChange={event => setQuery(event.target.value)}/></label>
        <div className="librarian-scope-list" aria-label={t('librarianChoose')}>
          {filtered.slice(0, limit).map(paper => <label key={paper.id}>
            <input type="checkbox" checked={selected.has(paper.id)} disabled={!selected.has(paper.id) && selected.size >= 50}
              onChange={event => { const next = new Set(selected); if (event.target.checked) next.add(paper.id); else next.delete(paper.id); setSelected(next) }}/>
            <span><strong>{paper.title}</strong><small>{[paper.authors.slice(0, 2).join(', '), paper.year].filter(Boolean).join(' · ')}</small></span>
          </label>)}
          {!filtered.length && <p className="librarian-scope-empty">{t('searchEmpty')}</p>}
          {filtered.length > limit && <button type="button" className="librarian-load-more" onClick={() => setLimit(value => value + 60)}>{t('librarianMorePapers')} · {limit} / {filtered.length}</button>}
        </div>
        <p className="librarian-scope-help">{t('librarianSelectionLimit')}</p>
      </> : <div className="librarian-scope-summary"><strong>{inScope.length} <span>{t('paperCount')}</span></strong><p>{t('librarianCoverageHint')}</p></div>}
      <p className="librarian-scope-archive-note">{t('librarianScopeArchiveHint')}</p>
    </div>
    <div className="modal-actions"><button type="button" className="btn secondary" onClick={close}>{t('cancel')}</button>
      <button type="button" className="btn primary" disabled={scope === 'selected' && !selected.size} onClick={() => apply(scope, [...selected])}>{t('librarianApplyScope')}</button></div>
  </Modal>
}
