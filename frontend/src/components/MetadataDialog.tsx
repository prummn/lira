import { useState } from 'react'
import { ExternalLink, LoaderCircle, RefreshCw } from 'lucide-react'
import type { Paper, PaperMetadataUpdate } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import type { LocaleKey } from '../lib/i18n'
import { ErrorBanner, Modal } from './Shared'

const draftOf = (paper: Paper) => ({
  title: paper.title, authors: paper.authors.join('\n'), year: paper.year?.toString() ?? '',
  venue: paper.venue ?? '', doi: paper.doi ?? '', arxiv_id: paper.arxiv_id ?? '',
})
const labels: Record<keyof ReturnType<typeof draftOf>, LocaleKey> = {
  title: 'title', authors: 'metadataAuthors', year: 'year', venue: 'metadataVenue', doi: 'metadataDoi', arxiv_id: 'metadataArxiv',
}
const sources: Record<string, LocaleKey> = {
  manual: 'metadataManual', arxiv: 'metadataSourceArxiv', crossref: 'metadataSourceCrossref',
  filename: 'metadataFilename', pdf_layout: 'metadataPdfLayout', pdf_text: 'metadataPdfText', pdf_metadata: 'metadataPdfDocument',
  arxiv_identifier: 'metadataArxivIdentifier',
  pdf_front_matter: 'metadataPdfFrontMatter', source_url: 'metadataSourceUrl',
}

export function MetadataDialog({ paper: initial, close, saved }: { paper: Paper; close: () => void; saved: () => Promise<void> }) {
  const { t } = useUi()
  const [paper, setPaper] = useState(initial)
  const [draft, setDraft] = useState(() => draftOf(initial))
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [confirmRefresh, setConfirmRefresh] = useState(false)
  const originUrl = paper.source_url || (paper.arxiv_id ? 'https://arxiv.org/abs/' + encodeURI(paper.arxiv_id) : null)
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(paper))
  const refresh = async () => {
    if (busy) return
    if (dirty && !confirmRefresh) { setConfirmRefresh(true); return }
    setBusy('refresh'); setError(''); setMessage(''); setConfirmRefresh(false)
    try {
      const next = await api.refreshMetadata(paper.id)
      setPaper(next); setDraft(draftOf(next)); setMessage(t('metadataRefreshed'))
      await saved()
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy('') }
  }
  const save = async () => {
    if (busy || !draft.title.trim()) return
    setBusy('save'); setError('')
    const values: PaperMetadataUpdate = {
      title: draft.title.trim(), authors: draft.authors.split('\n').map(s => s.trim()).filter(Boolean),
      year: draft.year ? Number(draft.year) : null, venue: draft.venue.trim() || null,
      doi: draft.doi.trim() || null, arxiv_id: draft.arxiv_id.trim() || null,
    }
    const original: PaperMetadataUpdate = {
      title: paper.title, authors: paper.authors, year: paper.year, venue: paper.venue, doi: paper.doi, arxiv_id: paper.arxiv_id,
    }
    const changes = Object.fromEntries(Object.entries(values).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(original[key as keyof PaperMetadataUpdate])))
    try { if (Object.keys(changes).length) await api.update(paper.id, changes); await saved(); close() }
    catch (e) { setError(errorMessage(e)) }
    finally { setBusy('') }
  }
  return <Modal title={t('paperMetadata')} close={() => { if (!busy) close() }}>
    <p className="dialog-description">{t('metadataHint')}</p>
    {error && <ErrorBanner error={error}/>} {message && <p className="metadata-message" role="status">{message}</p>}
    {!!paper.metadata_warnings?.length && <div className="metadata-warnings">{paper.metadata_warnings.map((warning, index) => <p key={index}>{warning}</p>)}</div>}
    <form className="metadata-form" onSubmit={e => { e.preventDefault(); void save() }}>
      {(Object.keys(labels) as (keyof typeof labels)[]).map(field => {
        const source = paper.metadata_sources?.[field]
        return <label key={field}>{t(labels[field])}
          {field === 'authors' ? <textarea aria-label={t(labels[field])} value={draft[field]} disabled={!!busy} onChange={e => { setDraft({ ...draft, [field]: e.target.value }); setConfirmRefresh(false) }}/>
            : <input aria-label={t(labels[field])} value={draft[field]} disabled={!!busy} required={field === 'title'} type={field === 'year' ? 'number' : 'text'} min={field === 'year' ? 1900 : undefined} max={field === 'year' ? 2200 : undefined} onChange={e => { setDraft({ ...draft, [field]: e.target.value }); setConfirmRefresh(false) }}/>}
          <small className="metadata-source">{t('metadataSource')}: {source ? sources[source] ? t(sources[source]) : source : t('unknown')}</small>
        </label>
      })}
      {originUrl && /^https?:\/\//i.test(originUrl) && <a className="metadata-origin" href={originUrl} target="_blank" rel="noreferrer">{t('metadataOriginalLink')}<ExternalLink size={13}/></a>}
      {confirmRefresh && <p className="metadata-warnings" role="status">{t('metadataDiscardDraft')}</p>}
      <div className="modal-actions metadata-actions"><button type="button" className="btn secondary" disabled={!!busy || !paper.pdf_available} onClick={() => void refresh()}>{busy === 'refresh' ? <LoaderCircle size={14} className="spin"/> : <RefreshCw size={14}/>} {t(confirmRefresh ? 'metadataConfirmRefresh' : 'refreshMetadata')}</button>
        <button className="btn primary" disabled={!!busy || !draft.title.trim()}>{busy === 'save' && <LoaderCircle size={14} className="spin"/>}{t('save')}</button></div>
    </form>
  </Modal>
}
