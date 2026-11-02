/// <reference types="vite/client" />

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, ChevronDown, ChevronLeft, ChevronRight, Download, FileText, List, LoaderCircle, Maximize, RotateCcw, Search, X, ZoomIn, ZoomOut } from 'lucide-react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { useUi } from '../lib/i18n'
import type { NoteAnchor, PdfVisualRegion, ReadingParagraph, TranslationQueueEntry } from '../types'
import { capturePdfSelection } from '../lib/pdfAnnotations'
import type { PdfAnnotation } from '../lib/pdfAnnotations'
import { PdfPage, clamp, evidenceRectangle, normalizeText, sourceTextRectangle } from './PdfPage'
import type { PageGeometry, Rectangle, Viewport } from './PdfPage'
import './pdf-viewer.css'

GlobalWorkerOptions.workerSrc = pdfWorkerUrl

/** Unrotated, CropBox-relative top-left page points, including source dimensions. */
export interface PdfLocator {
  page: number
  bbox?: number[] | null
  page_width?: number | null
  page_height?: number | null
  source_text?: string
  kind?: 'translation'
  /** Increment to revisit an already selected piece of evidence. */
  nonce?: number
}
export interface PdfSelection {
  page: number
  text: string
  bbox: number[]
  anchors?: NoteAnchor[]
  /** Text selected in the bilingual margin, with the original kept as evidence. */
  origin?: 'pdf' | 'translation'
  sourceText?: string
  visualKind?: 'figure'|'table'
  visualLabel?: string
  /** Selection bounds in viewport coordinates, used to place the action bar. */
  selectionRect?: { left: number; top: number; width: number; height: number }
}
export interface PdfRegionSelection {
  page: number
  imageDataUrl: string
  selectedText: string
  bbox: number[]
  kind: 'figure'|'table'
  label: string
}
export interface PdfViewerProps {
  url: string
  initialPage?: number
  locator?: PdfLocator | null
  onSelection?: (selection: PdfSelection) => void
  visualRegions?: PdfVisualRegion[]
  onAskVisualRegion?: (selection: PdfRegionSelection) => void
  onPageChange?: (page: number) => void
  paragraphs?: ReadingParagraph[]
  activeParagraphId?: string | null
  translatedParagraphIds?: string[]
  paragraphQueueItems?: Record<string,TranslationQueueEntry>
  onTranslateParagraph?: (paragraph: ReadingParagraph) => void
  annotations?:PdfAnnotation[]
  activeNoteId?:string|null
  onOpenAnnotation?:(annotation:PdfAnnotation)=>void
}
type Destination = string | unknown[] | null
interface OutlineEntry { title: string; destination: Destination; depth: number; id: string }
interface PageMeasure { page: number; natural: Viewport; canonical: Viewport }
interface LayoutPage { geometry: PageGeometry; top: number }
interface ReadingAnchor { page: number; fraction: number; horizontal: number }
interface PendingTarget { page: number; source: string; locator?:PdfLocator }
const PAGE_GAP = 20, READING_LINE = 100
const EMPTY_PARAGRAPHS: ReadingParagraph[] = [], EMPTY_IDS: string[] = []
const EMPTY_ANNOTATIONS:PdfAnnotation[]=[]
const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error)

function readableError(error: unknown, t: ReturnType<typeof useUi>['t']): string {
  const message = errorMessage(error)
  if (/password/i.test(message)) return t('pdfvPassword')
  if (/invalid pdf|invalidpdf/i.test(message)) return t('pdfvInvalid')
  if (/404|missing pdf/i.test(message)) return t('pdfvMissing')
  if (/fetch|network|failed to load|unexpected server response/i.test(message)) return t('pdfvNetwork')
  return `${t('pdfvOpenError')}: ${message}`
}
function flattenOutline(entries: Awaited<ReturnType<PDFDocumentProxy['getOutline']>>, depth = 0, prefix = ''): OutlineEntry[] {
  return (entries ?? []).flatMap((entry, index) => {
    const id = `${prefix}${index}`
    return [{ title: entry.title, destination: entry.dest, depth, id }, ...flattenOutline(entry.items, depth + 1, `${id}.`)]
  })
}

export function PdfViewer({ url, initialPage = 1, locator, onSelection, visualRegions = [], onAskVisualRegion, onPageChange, paragraphs = EMPTY_PARAGRAPHS, activeParagraphId, translatedParagraphIds = EMPTY_IDS, paragraphQueueItems, onTranslateParagraph, annotations=EMPTY_ANNOTATIONS,activeNoteId,onOpenAnnotation }: PdfViewerProps) {
  const { t } = useUi()
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [measures, setMeasures] = useState<PageMeasure[]>([])
  const [page, setPage] = useState(1)
  const [pageInput, setPageInput] = useState('1')
  const [loading, setLoading] = useState(true)
  const [progress, setProgress] = useState<number | null>(null)
  const [loadError, setLoadError] = useState('')
  const [retry, setRetry] = useState(0)
  const [containerWidth, setContainerWidth] = useState(600)
  const [zoom, setZoom] = useState<number | 'fit'>('fit')
  const [activePages, setActivePages] = useState<number[]>([])
  const [pageText, setPageText] = useState<Record<number, boolean>>({})
  const [outline, setOutline] = useState<OutlineEntry[]>([])
  const [outlineOpen, setOutlineOpen] = useState(false)
  const [outlineError, setOutlineError] = useState('')
  const [navigationError, setNavigationError] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [results, setResults] = useState<{ page: number }[]>([])
  const [resultIndex, setResultIndex] = useState(0)
  const [searchProgress, setSearchProgress] = useState(0)
  const [downloadError, setDownloadError] = useState('')
  const [downloading, setDownloading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const layoutRef = useRef<LayoutPage[]>([])
  const anchorRef = useRef<ReadingAnchor | null>(null)
  const initializedRef = useRef(false)
  const pendingRef = useRef<PendingTarget | null>(null)
  const readyTextRef = useRef(new Map<number, HTMLElement>())
  const textCacheRef = useRef(new Map<number, string>())
  const documentGenerationRef = useRef(0)
  const pageCountRef = useRef(0)
  const searchGenerationRef = useRef(0)
  const outlineRequestRef = useRef(0)
  const frameRef = useRef(0)
  const locatorRef = useRef(locator)
  const initialPageRef = useRef(initialPage)
  const callbacksRef = useRef({ onSelection, onPageChange })
  const tRef = useRef(t)
  locatorRef.current = locator; initialPageRef.current = initialPage
  callbacksRef.current = { onSelection, onPageChange }; tRef.current = t
  const captureSelection=()=>{
    const selection=window.getSelection(),scroller=scrollRef.current
    if(!selection||selection.isCollapsed||!selection.rangeCount||!scroller)return
    if(!selection.anchorNode?.parentElement?.closest('.pdfv-text-layer')||!selection.focusNode?.parentElement?.closest('.pdfv-text-layer')||!scroller.contains(selection.anchorNode)||!scroller.contains(selection.focusNode))return
    const pages=layoutRef.current.flatMap(({geometry})=>{
      const container=readyTextRef.current.get(geometry.page)
      return container?.isConnected?[{geometry,container}]:[]
    })
    const range = selection.getRangeAt(0)
    const selected=capturePdfSelection(range,pages)
    if(selected?.text) {
      // A DOM range spanning several lines can include off-screen pages. Use
      // the visible line rectangles for the action bar anchor so the controls
      // remain reachable while zooming or reading a long selection.
      const visible = Array.from(range.getClientRects()).filter(rect => rect.width > 1 && rect.height > 1
        && rect.bottom >= 0 && rect.top <= window.innerHeight)
      const rects = visible.length ? visible : Array.from(range.getClientRects()).filter(rect => rect.width > 1 && rect.height > 1)
      if (rects.length) {
        const left = Math.min(...rects.map(rect => rect.left))
        const top = Math.min(...rects.map(rect => rect.top))
        const right = Math.max(...rects.map(rect => rect.right))
        const bottom = Math.max(...rects.map(rect => rect.bottom))
        selected.selectionRect = { left, top, width: right - left, height: bottom - top }
      }
      callbacksRef.current.onSelection?.(selected)
    }
  }
  const locatorKey = locator ? JSON.stringify([locator.page, locator.bbox, locator.page_width, locator.page_height, locator.source_text, locator.nonce, locator.kind]) : ''

  const layout = useMemo(() => {
    let top = PAGE_GAP
    return measures.map(({ page, natural, canonical }) => {
      const scale = zoom === 'fit' ? clamp((containerWidth - PAGE_GAP * 2) / natural.width, .15, 4) : zoom
      const viewport = natural.clone({ scale })
      const entry = { geometry: { page, viewport, canonical }, top }
      top += viewport.height + PAGE_GAP
      return entry
    })
  }, [measures, zoom, containerWidth])

  // Scroll position owns current-page state; saving it through onPageChange
  // never creates a second navigation command through initialPage.
  const inspectScroll = useCallback(() => {
    const scroller = scrollRef.current, pages = layoutRef.current
    if (!scroller || !pages.length) return
    const line = Math.min(READING_LINE, scroller.clientHeight / 3), readingY = scroller.scrollTop + line
    const current = pages.find(entry => entry.top + entry.geometry.viewport.height > readingY) ?? pages[pages.length - 1]
    anchorRef.current = { page: current.geometry.page, fraction: (readingY - current.top) / current.geometry.viewport.height, horizontal: (scroller.scrollLeft + scroller.clientWidth / 2) / Math.max(scroller.clientWidth, scroller.scrollWidth) }
    setPage(current.geometry.page)
    const visible = pages.filter(entry => entry.top < scroller.scrollTop + scroller.clientHeight && entry.top + entry.geometry.viewport.height > scroller.scrollTop)
    const first = (visible[0] ?? current).geometry.page, last = (visible[visible.length - 1] ?? current).geometry.page
    const next = pages.filter(entry => entry.geometry.page >= first - 1 && entry.geometry.page <= last + 1).map(entry => entry.geometry.page)
    setActivePages(previous => previous.length === next.length && previous.every((value, index) => value === next[index]) ? previous : next)
    for (const [number, container] of readyTextRef.current) if (!next.includes(number) || !container.isConnected) readyTextRef.current.delete(number)
  }, [])
  const captureAnchor = useCallback(() => { if (initializedRef.current) inspectScroll() }, [inspectScroll])

  const scrollToTarget = useCallback((number: number, rectangle?: Rectangle | null) => {
    const scroller = scrollRef.current, entry = layoutRef.current[number - 1]
    if (!scroller || !entry) return
    scroller.scrollTo({ top: Math.max(0, entry.top + (rectangle ? rectangle.top - Math.min(READING_LINE, scroller.clientHeight / 3) : 0)), left: rectangle ? Math.max(0, (scroller.scrollWidth - entry.geometry.viewport.width) / 2 + rectangle.left - 25) : scroller.scrollLeft, behavior: 'auto' })
    inspectScroll()
  }, [inspectScroll])
  const goToPage = useCallback((value: number, source = '') => {
    if (!Number.isFinite(value)) return
    const number = clamp(Math.round(value), 1, pageCountRef.current || layoutRef.current.length || 1)
    setNavigationError('')
    pendingRef.current = { page: number, source }
    if (!layoutRef.current[number - 1]) return
    const text = readyTextRef.current.get(number)
    const rectangle = source && text?.isConnected ? sourceTextRectangle(source, text) : null
    if (!source || text?.isConnected) pendingRef.current = null
    scrollToTarget(number, rectangle)
  }, [scrollToTarget])

  useEffect(() => {
    let disposed = false
    const generation = ++documentGenerationRef.current
    searchGenerationRef.current += 1; outlineRequestRef.current += 1
    initializedRef.current = false; anchorRef.current = null; pendingRef.current = null; pageCountRef.current = 0
    layoutRef.current = []; readyTextRef.current.clear(); textCacheRef.current.clear()
    setDocument(null); setMeasures([]); setActivePages([]); setPageText({}); setLoading(true)
    setLoadError(''); setProgress(null); setOutline([]); setOutlineError(''); setNavigationError('')
    setResults([]); setSearchError(''); setQuery(''); setSearching(false); setDownloadError(''); setDownloading(false)
    if (!url) { setLoading(false); setLoadError(tRef.current('pdfvNoUrl')); return }
    const task = getDocument({ url, isEvalSupported: false })
    task.onProgress = ({ loaded, total }: { loaded: number; total: number }) => { if (!disposed && total > 0) setProgress(Math.round(loaded / total * 100)) }
    void task.promise.then(async loaded => {
      // Publish page one immediately. Remaining exact dimensions arrive in
      // the background; only the measured contiguous prefix is laid out, so
      // no page ever receives guessed geometry.
      const first = await loaded.getPage(1)
      if (disposed) { first.cleanup(); return }
      const firstMeasure = { page: 1, natural: first.getViewport({ scale: 1 }), canonical: first.getViewport({ scale: 1, rotation: 0 }) }
      first.cleanup()
      const measured:Array<PageMeasure|undefined>=new Array(loaded.numPages)
      measured[0]=firstMeasure
      let published=1
      const publishMeasuredPrefix=()=>{
        let next=published
        while(next<measured.length&&measured[next])next++
        if(next===published||disposed)return
        published=next
        setMeasures(measured.slice(0,published) as PageMeasure[])
      }
      pageCountRef.current=loaded.numPages
      setPage(1); setDocument(loaded); setMeasures([firstMeasure]); setLoading(false)
      let index = 1
      void Promise.all(Array.from({ length: Math.min(4, loaded.numPages - 1) }, async () => {
        while (!disposed) {
          const current = index++
          if (current >= loaded.numPages) return
          try {
            const pdfPage = await loaded.getPage(current + 1)
            if (disposed) { pdfPage.cleanup(); return }
            const next = { page: current + 1, natural: pdfPage.getViewport({ scale: 1 }), canonical: pdfPage.getViewport({ scale: 1, rotation: 0 }) }
            pdfPage.cleanup()
            measured[current]=next
            publishMeasuredPrefix()
          } catch (error) {
            if (!disposed) console.warn(`Could not measure PDF page ${current + 1}`, error)
          }
        }
      }))
      try {
        const items = await loaded.getOutline()
        if (!disposed && generation === documentGenerationRef.current) setOutline(flattenOutline(items))
      } catch (error) { if (!disposed) setOutlineError(`${tRef.current('pdfvOutlineReadError')}: ${errorMessage(error)}`) }
    }).catch(error => { if (!disposed) { setLoadError(readableError(error, tRef.current)); setLoading(false) } })
    return () => {
      disposed = true; searchGenerationRef.current += 1; outlineRequestRef.current += 1
      cancelAnimationFrame(frameRef.current)
      void task.destroy().catch(error => console.warn('PDF loading task cleanup failed', error))
    }
  }, [url, retry])

  useLayoutEffect(() => {
    layoutRef.current = layout
    const scroller = scrollRef.current
    if (!scroller || !layout.length) return
    if (!initializedRef.current) {
      initializedRef.current = true
      const raw=locatorRef.current?.page??initialPageRef.current
      const wanted=clamp(Number.isFinite(raw)?Math.round(raw):1,1,pageCountRef.current||layout.length)
      if(wanted>layout.length)pendingRef.current={page:wanted,source:locatorRef.current?.source_text??'',locator:locatorRef.current??undefined}
      scrollToTarget(wanted<=layout.length?wanted:1)
    } else {
      const pending=pendingRef.current
      if(pending&&pending.page<=layout.length) {
        const rectangle=pending.locator?evidenceRectangle(pending.locator,layout[pending.page-1].geometry):null
        if(rectangle||!pending.source)pendingRef.current=null
        scrollToTarget(pending.page,rectangle)
      } else {
        const anchor = anchorRef.current, entry = anchor && layout[anchor.page - 1]
        if (entry && anchor) {
          const line = Math.min(READING_LINE, scroller.clientHeight / 3)
          scroller.scrollTo({ top: Math.max(0, entry.top + anchor.fraction * entry.geometry.viewport.height - line), left: Math.max(0, anchor.horizontal * scroller.scrollWidth - scroller.clientWidth / 2), behavior: 'auto' })
        }
        inspectScroll()
      }
    }
    readyTextRef.current.clear()
  }, [layout, scrollToTarget, inspectScroll])

  useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    const observer = new ResizeObserver(() => { captureAnchor(); setContainerWidth(container.clientWidth); inspectScroll() })
    observer.observe(container); setContainerWidth(container.clientWidth)
    // Passive observation lets manual input cancel a still-loading locator.
    // Native wheel, touch and keyboard scrolling are never replaced or prevented.
    const cancelTarget = () => { pendingRef.current = null }
    container.addEventListener('wheel', cancelTarget, { passive: true })
    container.addEventListener('pointerdown', cancelTarget, { passive: true })
    container.addEventListener('touchstart', cancelTarget, { passive: true })
    container.addEventListener('keydown', cancelTarget)
    return () => {
      observer.disconnect()
      container.removeEventListener('wheel', cancelTarget); container.removeEventListener('pointerdown', cancelTarget)
      container.removeEventListener('touchstart', cancelTarget); container.removeEventListener('keydown', cancelTarget)
    }
  }, [captureAnchor, inspectScroll])
  useEffect(() => {
    if (!document || !layoutRef.current.length || !locatorRef.current) return
    const target = locatorRef.current, number = clamp(Math.round(target.page), 1, pageCountRef.current||layoutRef.current.length)
    const entry=layoutRef.current[number-1]
    if(!entry){pendingRef.current={page:number,source:target.source_text??'',locator:target};return}
    const rectangle = evidenceRectangle(target, entry.geometry)
    if (rectangle) { pendingRef.current = null; scrollToTarget(number, rectangle) }
    else goToPage(number, target.source_text ?? '')
    // A locator is a command only when its identity changes, never on repaint.
  }, [locatorKey, document, goToPage, scrollToTarget])
  useEffect(() => { setPageInput(String(page)); if (document) callbacksRef.current.onPageChange?.(page) }, [page, document])

  const onText = useCallback((number: number, text: string) => { textCacheRef.current.set(number, text) }, [])
  const onReady = useCallback((number: number, container: HTMLElement, hasText: boolean) => {
    readyTextRef.current.set(number, container)
    setPageText(previous => previous[number] === hasText ? previous : { ...previous, [number]: hasText })
    const target = pendingRef.current
    if (!target || target.page !== number) return
    pendingRef.current = null
    scrollToTarget(number, sourceTextRectangle(target.source, container))
  }, [scrollToTarget])
  useEffect(() => {
    const generation = ++searchGenerationRef.current, needle = normalizeText(query)
    setResults([]); setResultIndex(0); setSearchError(''); setSearchProgress(0)
    if (!searchOpen || !document || !needle) { setSearching(false); return }
    setSearching(true)
    const timer = window.setTimeout(() => {
      void (async () => {
        const found: { page: number }[] = []
        for (let number = 1; number <= document.numPages; number++) {
          if (generation !== searchGenerationRef.current) return
          let raw = textCacheRef.current.get(number)
          if (raw === undefined) {
            const pdfPage = await document.getPage(number), content = await pdfPage.getTextContent()
            if (generation !== searchGenerationRef.current) return
            raw = content.items.map(item => 'str' in item ? item.str : '').join(' ')
            textCacheRef.current.set(number, raw)
          }
          if (normalizeText(raw).includes(needle)) found.push({ page: number })
          setSearchProgress(number)
        }
        if (generation !== searchGenerationRef.current) return
        setResults(found); setSearching(false)
        if (found[0]) goToPage(found[0].page, query)
      })().catch(error => { if (generation === searchGenerationRef.current) { setSearching(false); setSearchError(`${tRef.current('pdfvSearchError')}: ${errorMessage(error)}`) } })
    }, 280)
    return () => { window.clearTimeout(timer); if (generation === searchGenerationRef.current) searchGenerationRef.current += 1 }
  }, [query, searchOpen, document, goToPage])
  useEffect(() => { if (searchOpen) searchInputRef.current?.focus() }, [searchOpen])

  const jumpToOutline = async (entry: OutlineEntry) => {
    if (!document || !entry.destination) return
    const request = ++outlineRequestRef.current, generation = documentGenerationRef.current
    try {
      const destination = typeof entry.destination === 'string' ? await document.getDestination(entry.destination) : entry.destination
      if (!destination?.length) throw new Error(tRef.current('pdfvDestinationMissing'))
      const reference = destination[0]
      let index: number
      if (typeof reference === 'number') index = reference
      else if (reference && typeof reference === 'object' && 'num' in reference && 'gen' in reference) index = await document.getPageIndex(reference as { num: number; gen: number })
      else throw new Error(tRef.current('pdfvDestinationUnsupported'))
      if (request === outlineRequestRef.current && generation === documentGenerationRef.current) goToPage(index + 1)
    } catch (error) { if (request === outlineRequestRef.current && generation === documentGenerationRef.current) setNavigationError(`${tRef.current('pdfvOutlineJumpError')}: ${errorMessage(error)}`) }
  }
  const download = async () => {
    if (!document || downloading) return
    setDownloading(true); setDownloadError('')
    const generation = documentGenerationRef.current
    try {
      const bytes = await document.getData()
      if (generation !== documentGenerationRef.current) return
      const objectUrl = URL.createObjectURL(new Blob([new Uint8Array(bytes)], { type: 'application/pdf' }))
      const anchor = window.document.createElement('a'), filename = url.split('?')[0].split('/').pop() || 'paper.pdf'
      anchor.href = objectUrl; anchor.download = /\.pdf$/i.test(filename) ? filename : 'paper.pdf'; anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    } catch (error) { if (generation === documentGenerationRef.current) setDownloadError(`${tRef.current('pdfvDownloadError')}: ${errorMessage(error)}`) }
    finally { if (generation === documentGenerationRef.current) setDownloading(false) }
  }
  const stepSearch = (direction: number) => {
    if (!results.length) return
    const index = (resultIndex + direction + results.length) % results.length
    setResultIndex(index); goToPage(results[index].page, query)
  }
  const currentScale = layout[page - 1]?.geometry.viewport.scale ?? 1
  const changeZoom = (value: number | 'fit') => { captureAnchor(); setZoom(value) }
  const stepZoom = (direction: number) => changeZoom(clamp(Math.round((currentScale + direction * .2) * 100) / 100, .25, 4))
  const submitPage = () => {
    if (!pageInput.trim() || !Number.isFinite(Number(pageInput))) setPageInput(String(page))
    else { goToPage(Number(pageInput)); setPageInput(String(clamp(Math.round(Number(pageInput)), 1, document?.numPages ?? 1))) }
  }
  const selectedEvidenceOnPage = locator?.page === page
  const hasEvidenceBox = Boolean(locator?.bbox || locator?.source_text)
  // Aggregate canvas budget: 24 MP (about 96 MB RGBA), at most 8 MP per page.
  const maxPixels = Math.min(8_000_000, Math.floor(24_000_000 / Math.max(1, activePages.length)))

  return (
    <section className="pdfv-viewer" aria-label={t('pdfvViewer')}>
      <div className="pdfv-toolbar">
        <div className="pdfv-toolbar-group">
          <button className={`pdfv-icon-button ${outlineOpen ? 'pdfv-active' : ''}`} type="button" title={t('pdfvOutline')} aria-label={t('pdfvToggleOutline')} aria-expanded={outlineOpen} onClick={() => { captureAnchor(); setOutlineOpen(!outlineOpen) }}><List size={16} /></button>
          <span className="pdfv-divider" />
          <button className="pdfv-icon-button" type="button" aria-label={t('pdfvPrevPage')} title={t('pdfvPrevPage')} disabled={!document || page <= 1} onClick={() => goToPage(page - 1)}><ChevronLeft size={16} /></button>
          <input className="pdfv-page-input" type="text" inputMode="numeric" aria-label={t('pdfvPageNumber')} value={pageInput} disabled={!document} onChange={event => setPageInput(event.target.value)} onBlur={submitPage} onKeyDown={event => { if (event.key === 'Enter') { submitPage(); event.currentTarget.blur() } }} />
          <span className="pdfv-page-count">/ {document?.numPages ?? '—'}</span>
          <button className="pdfv-icon-button" type="button" aria-label={t('pdfvNextPage')} title={t('pdfvNextPage')} disabled={!document || page >= document.numPages} onClick={() => goToPage(page + 1)}><ChevronRight size={16} /></button>
        </div>
        <div className="pdfv-toolbar-group pdfv-zoom-group">
          <button className="pdfv-icon-button" type="button" aria-label={t('pdfvZoomOut')} title={t('pdfvZoomOut')} disabled={!document || currentScale <= .25} onClick={() => stepZoom(-1)}><ZoomOut size={15} /></button>
          <span className="pdfv-scale">{Math.round(currentScale * 100)}%</span>
          <button className="pdfv-icon-button" type="button" aria-label={t('pdfvZoomIn')} title={t('pdfvZoomIn')} disabled={!document || currentScale >= 4} onClick={() => stepZoom(1)}><ZoomIn size={15} /></button>
          <button className={`pdfv-icon-button ${zoom === 'fit' ? 'pdfv-active' : ''}`} type="button" title={t('pdfvFitWidth')} aria-label={t('pdfvFitWidth')} disabled={!document} onClick={() => changeZoom('fit')}><Maximize size={15} /></button>
        </div>
        <div className="pdfv-toolbar-group">
          <button className={`pdfv-icon-button ${searchOpen ? 'pdfv-active' : ''}`} type="button" title={t('pdfvSearch')} aria-label={t('pdfvSearch')} aria-expanded={searchOpen} disabled={!document} onClick={() => { captureAnchor(); setSearchOpen(!searchOpen) }}><Search size={15} /></button>
          <button className="pdfv-icon-button" type="button" title={t('pdfvDownload')} aria-label={t('pdfvDownload')} disabled={!document || downloading} onClick={() => void download()}>{downloading ? <LoaderCircle size={15} className="pdfv-spin" /> : <Download size={15} />}</button>
        </div>
      </div>

      {searchOpen && <div className="pdfv-searchbar">
        <Search size={14} />
        <input ref={searchInputRef} value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') stepSearch(event.shiftKey ? -1 : 1); if (event.key === 'Escape') setSearchOpen(false) }} placeholder={t('pdfvSearchPlaceholder')} aria-label={t('pdfvSearch')} />
        <span className="pdfv-search-count" role="status">{searching ? `${searchProgress}/${document?.numPages ?? 0} ${t('page')}` : query.trim() ? results.length ? `${resultIndex + 1}/${results.length} ${t('pdfvMatchedPages')}` : t('pdfvNoMatch') : ''}</span>
        <button className="pdfv-icon-button" type="button" aria-label={t('pdfvPrevMatch')} disabled={!results.length || searching} onClick={() => stepSearch(-1)}><ChevronLeft size={14} /></button>
        <button className="pdfv-icon-button" type="button" aria-label={t('pdfvNextMatch')} disabled={!results.length || searching} onClick={() => stepSearch(1)}><ChevronRight size={14} /></button>
        <button className="pdfv-icon-button" type="button" aria-label={t('pdfvCloseSearch')} onClick={() => setSearchOpen(false)}><X size={14} /></button>
      </div>}

      {(searchError || navigationError || downloadError) && <div className="pdfv-notice pdfv-notice-error" role="alert"><AlertCircle size={14} /><span>{searchError || navigationError || downloadError}</span></div>}
      {document && pageText[page] === false && <div className="pdfv-notice" role="status"><FileText size={14} /><span>{t('pdfvScanned')}</span></div>}
      <div className="pdfv-body">
        {outlineOpen && <aside className="pdfv-outline" aria-label={t('pdfvOutline')}>
          <div className="pdfv-outline-heading"><strong>{t('pdfvOutline')}</strong><button className="pdfv-icon-button" type="button" aria-label={t('pdfvCloseOutline')} onClick={() => { captureAnchor(); setOutlineOpen(false) }}><X size={14} /></button></div>
          {outlineError ? <p className="pdfv-outline-message" role="alert">{outlineError}</p> : !outline.length ? <p className="pdfv-outline-message">{loading ? t('pdfvOutlineLoading') : t('pdfvNoOutline')}</p> : outline.map(entry => <button type="button" key={entry.id} className="pdfv-outline-entry" style={{ paddingLeft: `${12 + Math.min(entry.depth, 5) * 12}px` }} disabled={!entry.destination} onClick={() => void jumpToOutline(entry)} title={entry.title}><ChevronDown size={11} /><span>{entry.title || t('pdfvUnnamed')}</span></button>)}
        </aside>}
        <div ref={scrollRef} className="pdfv-scroll" tabIndex={0} aria-busy={loading} onMouseUp={captureSelection} onKeyUp={event=>{if(event.key.startsWith('Arrow'))captureSelection()}} onScroll={() => { cancelAnimationFrame(frameRef.current); frameRef.current = requestAnimationFrame(inspectScroll) }}>
          {loading && <div className="pdfv-state" role="status"><LoaderCircle size={24} className="pdfv-spin" /><strong>{t('pdfvLoading')}</strong><span>{progress === null ? t('pdfvLoadingHint') : `${t('pdfvLoaded')} ${progress}%`}</span></div>}
          {!loading && loadError && <div className="pdfv-state pdfv-error-state" role="alert"><AlertCircle size={26} /><strong>{t('pdfvUnavailable')}</strong><p>{loadError}</p><button className="pdfv-retry" type="button" onClick={() => setRetry(value => value + 1)}><RotateCcw size={14} />{t('retry')}</button></div>}
          <div className={`pdfv-page-area ${!document ? 'pdfv-hidden' : ''}`}>
            {document && layout.map(({ geometry }) => <PdfPage key={geometry.page} document={document} geometry={geometry} active={activePages.includes(geometry.page)} maxPixels={maxPixels} locator={locator?.page === geometry.page ? locator : null} query={searchOpen ? query : ''} paragraphs={paragraphs} visualRegions={visualRegions} onAskVisualRegion={onAskVisualRegion} activeParagraphId={activeParagraphId} translatedParagraphIds={translatedParagraphIds} paragraphQueueItems={paragraphQueueItems} onTranslateParagraph={onTranslateParagraph} annotations={annotations} activeNoteId={activeNoteId} onOpenAnnotation={onOpenAnnotation} onText={onText} onReady={onReady} />)}
          </div>
        </div>
      </div>
      <div className="pdfv-footer"><span>{selectedEvidenceOnPage ? <><span className="pdfv-evidence-dot" />{t(locator?.kind === 'translation' ? 'translationSource' : 'pdfvEvidenceLocation')} · {page} {t('page')}{hasEvidenceBox ? '' : ` · ${t('pdfvWholePage')}`}</> : t('pdfvSelectHint')}</span><span>{document ? `${document.numPages} ${t('page')} · ${t('pdfvOriginal')}` : t('pdfvLocal')}</span></div>
    </section>
  )
}
