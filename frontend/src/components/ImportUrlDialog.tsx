import { useState } from 'react'
import { ArrowUpRight, CheckCircle2, Download, Link2, LoaderCircle } from 'lucide-react'
import type { ModelSettings, PaperDetail } from '../types'
import { remoteAvailable, useAnalysisPreference } from '../lib/intelligence'
import { AnalysisImportChoice } from './ImportFilesDialog'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import { ErrorBanner, Modal } from './Shared'

export function ImportUrlDialog({ close, imported, openPaper, retryLabel,settings }: {
  close: () => void; imported: (paper: PaperDetail) => Promise<void>; openPaper: (id: string) => void; retryLabel?: string;settings:ModelSettings|null
}) {
  const { t } = useUi()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<PaperDetail | null>(null)
  const [completed, setCompleted] = useState(false)
  const [analyze,setAnalyze]=useAnalysisPreference()
  const finish = async (paper: PaperDetail) => {
    try { await imported(paper); setCompleted(true) }
    catch (e) { setError(errorMessage(e)); setCompleted(false) }
  }
  const retry = async () => {
    if (!result || busy) return
    setBusy(true); setError('')
    try { await finish(result) } finally { setBusy(false) }
  }
  const submit = async () => {
    if (busy || !url.trim()) return
    setBusy(true); setError('')
    try {
      const paper = await api.importUrl(url.trim(),remoteAvailable(settings)&&analyze)
      setResult(paper)
      await finish(paper)
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <Modal title={t('importUrlTitle')} close={() => { if (!busy) close() }}>
    <p className="dialog-description">{t('importUrlHint')}</p>
    {error && <ErrorBanner error={error} />}
    {result ? <div className="link-import-success" role="status">
      <CheckCircle2 size={23} /><strong>{t(completed ? 'importDone' : 'paperSaved')}</strong>
      <h3>{result.title}</h3><p>{result.authors.join(', ') || t('unknown')}</p>
      <small>{result.year ?? '—'} · {result.venue || t('unknown')} · {result.page_count} {t('page')}</small>
      {!!result.metadata_warnings?.length && <p className="muted">{t('metadataPartial')}</p>}
      <div className="modal-actions">{!completed && !busy && <button className="btn secondary" onClick={()=>void retry()}>{retryLabel || t('retry')}</button>}<button className="btn secondary" disabled={busy} onClick={close}>{t('close')}</button>
        <button className="btn primary" disabled={busy} onClick={() => { close(); openPaper(result.id) }}>{t('open')}<ArrowUpRight size={15}/></button></div>
    </div> : <form onSubmit={e => { e.preventDefault(); void submit() }}>
      <label>{t('paperUrl')}<div className="url-input"><Link2 size={16}/><input autoFocus type="url" required aria-label={t('paperUrl')} value={url} onChange={e => setUrl(e.target.value)} disabled={busy} placeholder="https://arxiv.org/abs/1706.03762" /></div></label>
      <p className="dialog-footnote">{t('importUrlLocal')}</p>
      <AnalysisImportChoice settings={settings} value={analyze} change={setAnalyze}/>
      {busy && <p className="download-progress" role="status"><LoaderCircle size={15} className="spin"/>{t('downloadingPaper')}</p>}
      <div className="modal-actions"><button type="button" className="btn secondary" disabled={busy} onClick={close}>{t('cancel')}</button>
        <button className="btn primary" disabled={busy || !url.trim()}>{busy ? <LoaderCircle size={15} className="spin"/> : <Download size={15}/>} {t(busy ? 'importing' : 'downloadImport')}</button></div>
    </form>}
  </Modal>
}
