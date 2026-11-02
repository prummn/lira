import { useEffect, useRef, useState } from 'react'
import { Check, Folder, LoaderCircle, Search } from 'lucide-react'
import type { Collection, Paper } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { ErrorBanner, Modal } from './Shared'
import './collection-assignment.css'

export function AddToCollectionDialog({papers, collections, paperIds, collectionId, close, saved, createCollection}: {
  papers: Paper[]; collections: Collection[]; paperIds?: string[]; collectionId?: string
  close: () => void; saved: (paperIds: string[], collection: Collection) => Promise<void>
  createCollection?: () => void
}) {
  const {t} = useUi()
  const [targetId, setTargetId] = useState(collectionId ?? '')
  const [selected, setSelected] = useState(() => new Set(paperIds ?? []))
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const saving = useRef(false)
  const content = useRef<HTMLDivElement>(null)
  const search = useRef<HTMLInputElement>(null)
  const choosingPapers = !!collectionId
  const target = collections.find(collection => collection.id === targetId)
  const chosen = papers.filter(paper => selected.has(paper.id))
  const additions = target ? chosen.filter(paper => !paper.collection_ids.includes(target.id)) : []
  const words = query.normalize('NFKC').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  const matches = (value: string) => words.every(word => value.normalize('NFKC').toLocaleLowerCase().includes(word))
  const candidates = choosingPapers
    ? papers.filter(paper => !paper.is_demo && !paper.collection_ids.includes(collectionId) && matches([paper.title, ...paper.authors, ...paper.tags, paper.year].join(' ')))
    : []
  const destinations = collections.filter(collection => matches(collection.name + ' ' + (collection.description ?? '')))
  const canSave = !!target && additions.length > 0 && additions.length <= 500
  const dismiss = () => { if (!saving.current) close() }

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const dialog = content.current?.closest('[role="dialog"]')
    const focusables = () => Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]') ?? [])
      .filter(element => element.getClientRects().length)
    const trap = (event: Event) => {
      const key = event as KeyboardEvent
      if (key.key !== 'Tab' || !dialog) return
      const elements = focusables()
      const first = elements[0], last = elements.at(-1)
      if (!dialog.contains(document.activeElement)) {key.preventDefault(); (key.shiftKey ? last : first)?.focus()}
      else if (key.shiftKey && document.activeElement === first) {key.preventDefault(); last?.focus()}
      else if (!key.shiftKey && document.activeElement === last) {key.preventDefault(); first?.focus()}
    }
    const contain = (event: FocusEvent) => {if (dialog && !dialog.contains(event.target as Node)) focusables()[0]?.focus()}
    search.current?.focus()
    document.addEventListener('keydown', trap)
    document.addEventListener('focusin', contain)
    return () => {
      document.removeEventListener('keydown', trap); document.removeEventListener('focusin', contain)
      if (opener?.isConnected) opener.focus({preventScroll: true})
    }
  }, [])

  const save = async () => {
    if (saving.current || !canSave || !target) return
    saving.current = true; setBusy(true); setError('')
    // Disabling the focused submit button otherwise sends focus to the page body.
    content.current?.closest('[role="dialog"]')?.querySelector<HTMLButtonElement>('.modal-head button')?.focus()
    try {
      const updated = await api.addCollectionPapers(target.id, additions.map(paper => paper.id))
      await saved(chosen.map(paper => paper.id), updated)
      close()
    } catch (failure) {setError(errorMessage(failure))}
    finally {saving.current = false; setBusy(false)}
  }

  return <Modal title={t(choosingPapers ? 'addExistingPapers' : 'addToCollection')} close={dismiss} className="collection-assignment-dialog">
    <div ref={content} className="collection-assignment-content">
      <div className="collection-assignment-context">
        {choosingPapers ? <><Folder size={18}/><div><strong>{target?.name}</strong><p>{t('collectionPickPapersHint')}</p></div></>
          : <div><strong>{chosen.length === 1 ? chosen[0].title : `${chosen.length} ${t('paperCount')}`}</strong><p>{t('collectionPickDestinationHint')}</p></div>}
      </div>
      <label className="collection-assignment-search"><Search size={16}/><input ref={search} type="search" aria-label={t(choosingPapers ? 'findExistingPapers' : 'findCollection')}
        placeholder={t(choosingPapers ? 'findExistingPapers' : 'findCollection')} value={query} disabled={busy} onChange={event => setQuery(event.target.value)}/></label>
      {choosingPapers && <div className="collection-assignment-selection"><span>{chosen.length} {t('selectedCount')}</span>
        <button className="text-btn" type="button" disabled={busy || !selected.size} onClick={() => setSelected(new Set())}>{t('clearSelection')}</button></div>}
      <div className="collection-assignment-list" role="group" aria-label={t(choosingPapers ? 'addExistingPapers' : 'chooseDestination')}>
        {choosingPapers ? candidates.map(paper => <label key={paper.id} className={selected.has(paper.id) ? 'is-selected' : ''}>
          <input type="checkbox" aria-label={paper.title} checked={selected.has(paper.id)} disabled={busy || (!selected.has(paper.id) && selected.size >= 500)}
            onChange={event => setSelected(current => {const next = new Set(current); if (event.target.checked) next.add(paper.id); else next.delete(paper.id); return next})}/>
          <span className="collection-assignment-item"><strong>{paper.title}</strong><small>{[paper.authors.slice(0, 2).join(', '), paper.year].filter(Boolean).join(' · ')}</small></span>
        </label>) : destinations.map(collection => {
          const alreadyIn = chosen.length > 0 && chosen.every(paper => paper.collection_ids.includes(collection.id))
          return <label key={collection.id} className={targetId === collection.id ? 'is-selected' : ''}>
            <input type="radio" name="collection-destination" aria-label={collection.name} checked={targetId === collection.id} disabled={busy || alreadyIn} onChange={() => setTargetId(collection.id)}/>
            <span className="collection-dot" style={{background: collection.color}}/>
            <span className="collection-assignment-item"><strong>{collection.name}</strong>{collection.description && <small>{collection.description}</small>}</span>
            <span className="collection-assignment-count">{alreadyIn ? <><Check size={13}/>{t('alreadyInCollection')}</> : `${collection.paper_count} ${t('paperCount')}`}</span>
          </label>
        })}
        {(choosingPapers ? !candidates.length : !destinations.length) && <div className="collection-assignment-empty">
          <p>{t(choosingPapers ? 'noPapersToAdd' : !collections.length ? 'noCollections' : 'noMatchingCollections')}</p>
          {!choosingPapers && !collections.length && createCollection && <button type="button" className="text-btn" onClick={() => {close(); createCollection()}}>{t('newCollection')}</button>}
        </div>}
      </div>
      {additions.length > 500 && <p className="collection-assignment-limit">{t('collectionBatchLimit')}</p>}
      {error && <ErrorBanner error={error}/>}
    </div>
    <div className="modal-actions"><span className="collection-assignment-footnote">{canSave ? `${additions.length} ${t('paperCount')}` : t('collectionSelectFirst')}</span>
      <button type="button" className="btn secondary" disabled={busy} onClick={dismiss}>{t('cancel')}</button>
      <button type="button" className="btn primary" disabled={busy || !canSave} onClick={() => void save()}>{busy && <LoaderCircle className="spin" size={14}/>} {t(busy ? 'collectionSaving' : 'confirmAddToCollection')}</button></div>
  </Modal>
}
