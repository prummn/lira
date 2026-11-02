import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Activity, X } from 'lucide-react'
import type { ResearchActivity } from '../types'
import { useUi } from '../lib/i18n'
import { researchActivityLevel } from '../lib/researchActivity'
import { ActivityDayPreview } from './ActivityDayPreview'
import type { ActivityPreviewTarget } from './ActivityDayPreview'

type Props = {
  activity: ResearchActivity | null
  selectedDate: string
  loading?: boolean
  error?: string
  onSelect: (date: string) => void
  onClear: () => void
}

const dayKey = (date: Date) => {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const parseDate = (value: string) => new Date(`${value}T00:00:00`)

export function ResearchActivityHeatmap({ activity, selectedDate, loading, error, onSelect, onClear }: Props) {
  const { t, language } = useUi()
  const [preview, setPreview] = useState<ActivityPreviewTarget | null>(null)
  const previewId = useId()
  const hideTimer = useRef<ReturnType<typeof setTimeout>>()
  const hoveredDay = useRef<ActivityPreviewTarget | null>(null)
  const focusedDay = useRef<ActivityPreviewTarget | null>(null)
  const previewHovered = useRef(false)
  const keepPreview = useCallback(() => { clearTimeout(hideTimer.current) }, [])
  const hidePreview = useCallback(() => {
    keepPreview()
    hoveredDay.current = null
    focusedDay.current = null
    previewHovered.current = false
    setPreview(null)
  }, [keepPreview])
  const showPreview = (date: string, element: HTMLButtonElement) => { keepPreview(); setPreview({ date, element }) }
  const leavePreview = () => {
    keepPreview()
    hideTimer.current = setTimeout(() => {
      if (!previewHovered.current) setPreview(hoveredDay.current ?? focusedDay.current)
    }, 140)
  }
  useEffect(() => {
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') hidePreview() }
    document.addEventListener('keydown', escape)
    return () => { keepPreview(); document.removeEventListener('keydown', escape) }
  }, [hidePreview, keepPreview])
  const days = activity?.days ?? []
  const readingCount = days.reduce((sum, day) => sum + day.reading, 0)
  const byDate = useMemo(() => new Map(days.map(day => [day.date, day])), [days])
  const grid = useMemo(() => {
    const last = days.length ? parseDate(days[days.length - 1].date) : new Date()
    const end = new Date(last)
    end.setDate(end.getDate() + (6 - end.getDay()))
    const start = new Date(end)
    start.setDate(start.getDate() - 52 * 7 - 6)
    return Array.from({ length: 53 }, (_, week) => Array.from({ length: 7 }, (_, weekday) => {
      const date = new Date(start)
      date.setDate(start.getDate() + week * 7 + weekday)
      return dayKey(date)
    }))
  }, [days])
  const monthFormatter = useMemo(() => new Intl.DateTimeFormat(language === 'en-US' ? 'en-US' : 'zh-CN', { month: 'short' }), [language])
  const dateFormatter = useMemo(() => new Intl.DateTimeFormat(language === 'en-US' ? 'en-US' : 'zh-CN', { year: 'numeric', month: 'short', day: 'numeric' }), [language])
  const detail = (date: string) => {
    const day = byDate.get(date)
    const total = day?.total ?? 0
    const parts = [
      `${t('activityReading')}: ${day?.reading ?? 0}`,
      `${t('activityNotes')}: ${day?.notes ?? 0}`,
      `${t('activityLanguage')}: ${day?.language ?? 0}`,
      `${t('activitySearch')}: ${day?.search ?? 0}`,
      `${t('activityImports')}: ${day?.imports ?? 0}`,
    ]
    return `${dateFormatter.format(parseDate(date))} · ${t('activityTotal')}: ${total}\n${parts.join(' · ')}`
  }
  const monthLabels = grid.map((week, index) => {
    const first = parseDate(week[0])
    const previous = index ? parseDate(grid[index - 1][0]) : null
    return !previous || first.getMonth() !== previous.getMonth() ? { index, label: monthFormatter.format(first) } : null
  }).filter(Boolean) as { index:number; label:string }[]

  return <section className="research-activity" aria-label={t('activityTitle')}>
    <div className="research-activity-head">
      <div><div className="eyebrow"><Activity size={12}/>{t('activityEyebrow')}</div><h2>{t('activityTitle')}</h2><p>{t('activitySubtitle')}</p></div>
      {selectedDate && <button className="text-btn activity-clear" onClick={onClear}><X size={13}/>{t('activityClear')}</button>}
    </div>
    {loading ? <div className="research-activity-loading" role="status">{t('activityLoading')}</div> : error ? <div className="research-activity-unavailable" role="status">{t('activityUnavailable')}</div> : <>
      <div className="research-activity-body">
        <div className="research-activity-stats"><div><strong>{activity?.streak ?? 0}</strong><span>{t('activityStreak')}</span></div><div><strong>{activity?.active_days_30 ?? 0}</strong><span>{t('activityActiveDays')}</span></div><div><strong>{readingCount}</strong><span>{t('activityReadingTotal')}</span></div></div>
        <div className="research-activity-scroll"><div className="research-activity-months" aria-hidden="true">{monthLabels.map(month => <span key={`${month.index}-${month.label}`} style={{ gridColumn: month.index + 1 }}>{month.label}</span>)}</div><div className="research-activity-grid" role="grid" aria-label={t('activityGridLabel')}>{grid.map((week, weekIndex) => <div className="research-activity-week" role="row" key={weekIndex}>{week.map(date => { const day = byDate.get(date); const level = researchActivityLevel(day); return <button key={date} type="button" role="gridcell" data-testid="research-activity-day" className={`research-activity-day activity-level-${level} ${selectedDate === date ? 'is-selected' : ''}`} aria-label={detail(date)} aria-pressed={selectedDate === date} aria-describedby={preview?.date === date ? previewId : undefined}
          onMouseEnter={event => { hoveredDay.current = { date, element: event.currentTarget }; showPreview(date, event.currentTarget) }}
          onMouseLeave={() => { hoveredDay.current = null; leavePreview() }}
          onFocus={event => { focusedDay.current = { date, element: event.currentTarget }; showPreview(date, event.currentTarget) }}
          onBlur={() => { focusedDay.current = null; leavePreview() }}
          onClick={() => { hidePreview(); onSelect(date) }}><span className="sr-only">{detail(date)}</span></button> })}</div>)}</div><div className="research-activity-legend"><span>{t('activityLess')}</span>{[0,1,2,3,4].map(level=><i key={level} className={`research-activity-day activity-level-${level}`} aria-hidden="true"/>)}<span>{t('activityMore')}</span></div></div>
      </div>
      {selectedDate && <p className="research-activity-selection" role="status">{t('activitySelected')}: <strong>{dateFormatter.format(parseDate(selectedDate))}</strong>{(byDate.get(selectedDate)?.paper_ids.length ?? 0) > 0 && ` · ${byDate.get(selectedDate)!.paper_ids.length} ${t('activityPapers')}`}</p>}
    </>}
    {preview && !loading && !error && <ActivityDayPreview id={previewId} target={preview} day={byDate.get(preview.date)}
      onEnter={() => { previewHovered.current = true; keepPreview() }}
      onLeave={() => { previewHovered.current = false; leavePreview() }} onDismiss={hidePreview}/>}
  </section>
}
