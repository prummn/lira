import { BookMarked, LoaderCircle, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { QuickTranslation } from '../types'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import './quick-translation.css'

/** Keep this action for dictionary-sized selections; paragraphs belong in the reader translation flow. */
export function isShortTranslationSelection(value: string): boolean {
  const text = value.trim().replace(/\s+/g, ' ')
  if (!text || text.length > 80 || !/[A-Za-z]/.test(text)) return false
  const cleaned = text.replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/g, '')
  return /^[A-Za-z0-9]+(?:[’'/-][A-Za-z0-9]+)*(?:\s+[A-Za-z0-9]+(?:[’'/-][A-Za-z0-9]+)*){0,3}$/.test(cleaned)
}

const quickTranslationRequests = new Map<string, Promise<QuickTranslation>>()
function requestQuickTranslation(text: string): Promise<QuickTranslation> {
  const key = text.trim().replace(/\s+/g, ' ').toLocaleLowerCase()
  const existing = quickTranslationRequests.get(key)
  if (existing) return existing
  const request = api.quickTranslate(text).finally(() => quickTranslationRequests.delete(key))
  quickTranslationRequests.set(key, request)
  return request
}

export function QuickTranslationPopover({ text, close }: { text: string; close: () => void }) {
  const { t } = useUi()
  const [result, setResult] = useState<QuickTranslation | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    setResult(null); setError('')
    requestQuickTranslation(text).then(value => {
      if (alive) setResult(value)
    }).catch(reason => {
      if (alive) setError(errorMessage(reason))
    })
    return () => { alive = false }
  }, [text])
  return <div className="quick-translation-popover" role="status" aria-live="polite">
    <div className="quick-translation-head">
      <div><BookMarked size={14}/><strong>{t('quickTranslate')}</strong><span>{text.trim()}</span></div>
      <button type="button" className="icon-btn" aria-label={t('close')} title={t('close')} onClick={close}><X size={14}/></button>
    </div>
    {result ? <>
      <div className="quick-translation-main">
        {result.translation && <strong>{result.translation}</strong>}
        {result.phonetic && <span className="quick-translation-phonetic">{result.phonetic}</span>}
      </div>
      {!!result.definitions.length && <><small className="quick-translation-definition-label">{result.source === 'dictionaryapi' ? t('quickTranslateEnglishDefinitions') : t('quickTranslateSource')}</small><ul className="quick-translation-definitions">{result.definitions.map((definition, index) => <li key={`${definition.part_of_speech ?? ''}-${index}`}><span>{definition.part_of_speech}</span><p>{definition.text}</p>{definition.example && <small>{definition.example}</small>}</li>)}</ul></>}
      <small className="quick-translation-source">{result.cached ? t('quickTranslateCached') : t('quickTranslateLive')}</small>
    </> : error ? <div className="quick-translation-error"><p>{error}</p><button type="button" className="text-btn" onClick={() => { setError(''); setResult(null); void requestQuickTranslation(text).then(setResult).catch(reason => setError(errorMessage(reason))) }}>{t('retry')}</button></div>
      : <div className="quick-translation-loading"><LoaderCircle size={14} className="spin"/>{t('quickTranslateLoading')}</div>}
  </div>
}
