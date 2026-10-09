import { AlertCircle, ArrowUpRight, Inbox, LoaderCircle, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useUi } from '../lib/i18n'
export function Empty({ title, text, children }: { title: string; text?: string; children?: ReactNode }) {
  return <div className="empty-state"><Inbox size={28} strokeWidth={1.4}/><strong>{title}</strong>{text && <p>{text}</p>}{children}</div>
}
export function Loading({ text }: { text: string }) { return <div className="empty-state"><LoaderCircle size={22} className="spin"/><p>{text}</p></div> }
export function ErrorBanner({ error, retry }: {error: string; retry?: () => void}) {
  const {t} = useUi(); return <div className="error-banner" role="alert"><AlertCircle size={16}/><span>{error}</span>{retry && <button className="text-btn" onClick={retry}>{t('retry')}</button>}</div>
}
export function Modal({ title, children, close }: {title: string; children: ReactNode; close: () => void}) {
  const {t} = useUi()
  return createPortal(<div className="modal-backdrop" onClick={close} onKeyDown={e => { if(e.key === 'Escape') close() }}><section role="dialog" aria-modal="true" aria-label={title} className="modal" onClick={e => e.stopPropagation()}><div className="modal-head"><h2>{title}</h2><button className="icon-btn" aria-label={t('close')} onClick={close}><X size={18}/></button></div>{children}</section></div>, document.body)
}
export function SourceBadge({ source }: {source: string}) {
  const {t} = useUi(); const key = source === 'user' ? 'sourceUser' : source === 'llm_summary' ? 'sourceAiSummary' : source === 'llm_inferred' || source === 'ai' ? 'sourceAi' : source === 'metadata' ? 'sourceMetadata' : 'sourceExplicit'
  return <span className={`source-badge source-${source}`}>{t(key)}</span>
}
export function PaperLink({ title, onClick }: { title: string; onClick: () => void }) { return <button className="paper-link" onClick={onClick}><span>{title}</span><ArrowUpRight size={14}/></button> }
export function exportJson(filename: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}))
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
