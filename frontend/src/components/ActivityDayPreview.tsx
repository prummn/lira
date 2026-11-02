import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { BookOpen, PencilLine } from 'lucide-react'
import type { ActivityDay } from '../types'
import { useUi } from '../lib/i18n'
import { researchActivityLevel } from '../lib/researchActivity'
import './research-activity-preview.css'

export type ActivityPreviewTarget = { date: string; element: HTMLButtonElement }

export function ActivityDayPreview({ id, target, day, onEnter, onLeave, onDismiss }: {
  id: string; target: ActivityPreviewTarget; day: ActivityDay | undefined
  onEnter: () => void; onLeave: () => void; onDismiss: () => void
}) {
  const { t, language } = useUi()
  const ref = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ left: number; top: number; arrow: number; above: boolean }>()
  const date = useMemo(() => new Date(`${target.date}T00:00:00`), [target.date])
  const label = new Intl.DateTimeFormat(language, { year: 'numeric', month: 'short', day: 'numeric' }).format(date)
  const weekday = new Intl.DateTimeFormat(language, { weekday: 'short' }).format(date)
  const level = researchActivityLevel(day)

  useEffect(() => {
    // Keep focus on the day while letting keyboard users read clipped preview content.
    const scrollContent = (event: KeyboardEvent) => {
      const content = contentRef.current
      if (!content || content.scrollHeight <= content.clientHeight
        || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
      let top = content.scrollTop
      switch (event.key) {
        case 'ArrowDown': top += 40; break
        case 'ArrowUp': top -= 40; break
        case 'PageDown': top += content.clientHeight; break
        case 'PageUp': top -= content.clientHeight; break
        case 'Home': top = 0; break
        case 'End': top = content.scrollHeight; break
        default: return
      }
      event.preventDefault()
      content.scrollTop = top
    }
    target.element.addEventListener('keydown', scrollContent)
    return () => target.element.removeEventListener('keydown', scrollContent)
  }, [target])

  useLayoutEffect(() => {
    const place = () => {
      const box = ref.current?.getBoundingClientRect()
      if (!box) return
      const anchor = target.element.getBoundingClientRect()
      const clip = target.element.closest('.research-activity-scroll')?.getBoundingClientRect()
      if (anchor.bottom <= 0 || anchor.top >= innerHeight || anchor.right <= Math.max(0, clip?.left ?? 0)
        || anchor.left >= Math.min(innerWidth, clip?.right ?? innerWidth)) { onDismiss(); return }
      const center = anchor.left + anchor.width / 2
      const left = Math.max(12, Math.min(center - box.width / 2, window.innerWidth - box.width - 12))
      const above = anchor.top - box.height - 12 >= 12
      const top = above ? anchor.top - box.height - 12
        : Math.max(12, Math.min(anchor.bottom + 12, window.innerHeight - box.height - 12))
      setPosition({ left, top, above, arrow: Math.max(18, Math.min(center - left, box.width - 18)) })
    }
    place()
    // Scrolling a clipped grid into view must not immediately dismiss a new preview.
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => { window.removeEventListener('scroll', place, true); window.removeEventListener('resize', place) }
  }, [target, day, language, onDismiss])

  return createPortal(<div ref={ref} id={id} role="tooltip" className="research-activity-preview"
    data-side={position?.above ? 'above' : 'below'} onMouseEnter={onEnter} onMouseLeave={onLeave}
    style={{ left: position?.left ?? 0, top: position?.top ?? 0, visibility: position ? 'visible' : 'hidden', '--preview-arrow': `${position?.arrow ?? 18}px` } as CSSProperties}>
    <div ref={contentRef} className="activity-preview-content">
    <header><strong><i className={`activity-level-${level}`} aria-hidden="true"/>{label}</strong><span>{weekday}</span></header>
    {level ? <>
      <dl className="activity-preview-primary">
        <div data-kind="reading"><dt><BookOpen size={13}/>{t('activityReading')}</dt><dd>{day?.reading ?? 0}<span>{t('activityTimesUnit')}</span></dd></div>
        <div data-kind="notes"><dt><PencilLine size={13}/>{t('activityNotes')}</dt><dd>{day?.notes ?? 0}<span>{t('activityNotesUnit')}</span></dd></div>
      </dl>
      <dl className="activity-preview-supporting">
        <div data-kind="language"><dt>{t('activityLanguage')}</dt><dd>{day?.language ?? 0}<span>{t('activityTimesUnit')}</span></dd></div>
        <div data-kind="search"><dt>{t('activitySearch')}</dt><dd>{day?.search ?? 0}<span>{t('activityTimesUnit')}</span></dd></div>
        <div data-kind="imports"><dt>{t('activityImports')}</dt><dd>{day?.imports ?? 0}<span>{t('activityReadingUnit')}</span></dd></div>
      </dl>
      <footer>{!!day?.paper_ids.length && <span>{day.paper_ids.length} {t('activityPapers')}</span>}<p>{t('activityColorHint')}</p></footer>
    </> : <p className="activity-preview-empty">{t('activityEmptyDay')}</p>}
    </div>
    <span className="activity-preview-arrow" aria-hidden="true"/>
  </div>, document.body)
}
