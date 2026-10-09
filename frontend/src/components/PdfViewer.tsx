/// <reference types="vite/client" />

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle, ChevronDown, ChevronLeft, ChevronRight, Download, FileText,
  Languages, List, LoaderCircle, Maximize, RotateCcw, Search, X, ZoomIn, ZoomOut,
} from 'lucide-react'
import { getDocument, GlobalWorkerOptions, TextLayer } from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { useUi } from '../lib/i18n'
import type { ReadingParagraph } from '../types'
import './pdf-viewer.css'

GlobalWorkerOptions.workerSrc = pdfWorkerUrl

/**
 * Coordinates are unrotated, CropBox-relative top-left page points:
 * [x0, y0, x1, y1]. Source dimensions must also describe the unrotated
 * cropped page. PDF.js applies CropBox offsets and page rotation once.
 */
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
  /** Unrotated CropBox-relative points, suitable for saving and revisiting. */
  bbox: number[]
}

export interface PdfViewerProps {
  url: string
  initialPage?: number
  locator?: PdfLocator | null
  onSelection?: (selection: PdfSelection) => void
  onPageChange?: (page: number) => void
  paragraphs?: ReadingParagraph[]
  activeParagraphId?: string | null
  translatedParagraphIds?: string[]
  onTranslateParagraph?: (paragraph:ReadingParagraph) => void
}

type Viewport = ReturnType<PDFPageProxy['getViewport']>
type Destination = string | unknown[] | null
interface OutlineEntry { title: string; destination: Destination; depth: number; id: string }
interface SearchResult { page: number; count: number; excerpt: string }
interface PageGeometry { page: number; viewport: Viewport; canonical: Viewport }
interface Rectangle { left: number; top: number; width: number; height: number }

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))
const normalizeText = (value: string) => value.normalize('NFKC').replace(/\s+/g, ' ').trim().toLowerCase()
const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error)
const isCancelled = (error: unknown) => error instanceof Error && (
  error.name === 'RenderingCancelledException' || error.name === 'AbortException'
)

function readableError(error: unknown, t: ReturnType<typeof useUi>['t']): string {
  const message = errorMessage(error)
  if (/password/i.test(message)) return t('pdfvPassword')
  if (/invalid pdf|invalidpdf/i.test(message)) return t('pdfvInvalid')
  if (/404|missing pdf/i.test(message)) return t('pdfvMissing')
  if (/fetch|network|failed to load|unexpected server response/i.test(message)) {
    return t('pdfvNetwork')
  }
  return `${t('pdfvOpenError')}: ${message}`
}

function flattenOutline(
  entries: Awaited<ReturnType<PDFDocumentProxy['getOutline']>>,
  depth = 0,
  prefix = '',
): OutlineEntry[] {
  return (entries ?? []).flatMap((entry, index) => {
    const id = `${prefix}${index}`
    return [
      { title: entry.title, destination: entry.dest, depth, id },
      ...flattenOutline(entry.items, depth + 1, `${id}.`),
    ]
  })
}

function rectangleFromPoints(points: number[][]): Rectangle {
  const xs = points.map(point => point[0])
  const ys = points.map(point => point[1])
  const left = Math.min(...xs)
  const top = Math.min(...ys)
  return { left, top, width: Math.max(...xs) - left, height: Math.max(...ys) - top }
}

/** Map the parser's top-left coordinates through PDF.js, including page rotation. */
function evidenceRectangle(locator: PdfLocator, geometry: PageGeometry): Rectangle | null {
  const bbox = locator.bbox
  if (!bbox || bbox.length !== 4 || !bbox.every(Number.isFinite)) return null
  const { canonical, viewport } = geometry
  const sourceWidth = locator.page_width && locator.page_width > 0 ? locator.page_width : canonical.width
  const sourceHeight = locator.page_height && locator.page_height > 0 ? locator.page_height : canonical.height
  const [x0, y0, x1, y1] = bbox
  if (x1 <= x0 || y1 <= y0) return null
  const transform = (x: number, y: number) => {
    const [pdfX, pdfY] = canonical.convertToPdfPoint(
      clamp(x / sourceWidth, 0, 1) * canonical.width,
      clamp(y / sourceHeight, 0, 1) * canonical.height,
    )
    return viewport.convertToViewportPoint(pdfX, pdfY)
  }
  const rectangle = rectangleFromPoints([
    transform(x0, y0), transform(x1, y0), transform(x0, y1), transform(x1, y1),
  ])
  return rectangle.width > 0 && rectangle.height > 0 ? rectangle : null
}

/** Use exact normalized source text as a fallback when no parser bbox exists. */
function sourceTextRectangle(source: string, textContainer: HTMLElement): Rectangle | null {
  const needle = normalizeText(source)
  if (needle.length < 3) return null
  let combined = ''
  const spans: { element: HTMLElement; start: number; end: number }[] = []
  for (const element of textContainer.querySelectorAll<HTMLElement>('span[role="presentation"]')) {
    const text = normalizeText(element.textContent ?? '')
    if (!text) continue
    if (combined) combined += ' '
    const start = combined.length
    combined += text
    spans.push({ element, start, end: combined.length })
  }
  const position = combined.indexOf(needle)
  if (position === -1) return null
  const matched = spans.filter(span => span.end > position && span.start < position + needle.length)
  if (!matched.length) return null
  const origin = textContainer.getBoundingClientRect()
  const rects = matched.map(span => span.element.getBoundingClientRect())
  return rectangleFromPoints(rects.flatMap(rect => [
    [rect.left - origin.left, rect.top - origin.top],
    [rect.right - origin.left, rect.bottom - origin.top],
  ]))
}

export function PdfViewer({ url, initialPage = 1, locator, onSelection, onPageChange, paragraphs = [], activeParagraphId, translatedParagraphIds = [], onTranslateParagraph }: PdfViewerProps) {
  const { t } = useUi()
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [page, setPage] = useState(1)
  const [pageInput, setPageInput] = useState('1')
  const [loading, setLoading] = useState(true)
  const [progress, setProgress] = useState<number | null>(null)
  const [loadError, setLoadError] = useState('')
  const [retry, setRetry] = useState(0)
  const [renderRetry, setRenderRetry] = useState(0)
  const [rendering, setRendering] = useState(false)
  const [renderError, setRenderError] = useState('')
  const [pageHasText, setPageHasText] = useState(true)
  const [geometry, setGeometry] = useState<PageGeometry | null>(null)
  const [containerWidth, setContainerWidth] = useState(600)
  const [zoom, setZoom] = useState<number | 'fit'>('fit')
  const [outline, setOutline] = useState<OutlineEntry[]>([])
  const [outlineOpen, setOutlineOpen] = useState(false)
  const [outlineError, setOutlineError] = useState('')
  const [navigationError, setNavigationError] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [resultIndex, setResultIndex] = useState(0)
  const [searchProgress, setSearchProgress] = useState(0)
  const [sourceRectangle, setSourceRectangle] = useState<Rectangle | null>(null)
  const [downloadError, setDownloadError] = useState('')
  const [downloading, setDownloading] = useState(false)
  const [hoveredRegionKey, setHoveredRegionKey] = useState<string|null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)
  const layersRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLDivElement | null>(null)
  const evidenceRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const geometryRef = useRef<PageGeometry | null>(null)
  const pageRef = useRef(page)
  const initialPageRef = useRef(initialPage)
  const locatorRef = useRef(locator)
  const callbacksRef = useRef({ onSelection, onPageChange })
  const tRef = useRef(t)
  const textCacheRef = useRef(new Map<number, string>())
  const documentGenerationRef = useRef(0)
  const searchGenerationRef = useRef(0)
  const outlineRequestRef = useRef(0)
  initialPageRef.current = initialPage
  locatorRef.current = locator
  callbacksRef.current = { onSelection, onPageChange }
  tRef.current = t
  pageRef.current = page
  geometryRef.current = geometry

  const locatorKey = locator ? JSON.stringify([
    locator.page, locator.bbox, locator.page_width, locator.page_height, locator.source_text, locator.nonce, locator.kind,
  ]) : ''

  const goToPage = useCallback((value: number) => {
    if (!document || !Number.isFinite(value)) return
    setNavigationError('')
    setPage(clamp(Math.round(value), 1, document.numPages))
  }, [document])

  useEffect(() => {
    let disposed = false
    const generation = ++documentGenerationRef.current
    searchGenerationRef.current += 1
    outlineRequestRef.current += 1
    setDocument(null)
    setLoading(true)
    setLoadError('')
    setProgress(null)
    setGeometry(null)
    setRenderError('')
    setOutline([])
    setOutlineError('')
    setNavigationError('')
    setResults([])
    setSearchError('')
    setQuery('')
    setSearching(false)
    setDownloadError('')
    setDownloading(false)
    setSourceRectangle(null)
    textCacheRef.current.clear()
    textRef.current = null
    layersRef.current?.replaceChildren()
    if (!url) {
      setLoading(false)
      setLoadError(tRef.current('pdfvNoUrl'))
      return
    }
    const task = getDocument({ url, isEvalSupported: false })
    task.onProgress = ({ loaded, total }: { loaded: number; total: number }) => {
      if (!disposed && total > 0) setProgress(Math.round(loaded / total * 100))
    }
    void task.promise.then(async loadedDocument => {
      if (disposed) return
      const wanted = locatorRef.current?.page ?? initialPageRef.current
      setPage(clamp(Number.isFinite(wanted) ? Math.round(wanted) : 1, 1, loadedDocument.numPages))
      setDocument(loadedDocument)
      setLoading(false)
      try {
        const items = await loadedDocument.getOutline()
        if (!disposed && generation === documentGenerationRef.current) setOutline(flattenOutline(items))
      } catch (error) {
        if (!disposed) setOutlineError(`${tRef.current('pdfvOutlineReadError')}: ${errorMessage(error)}`)
      }
    }).catch(error => {
      if (!disposed) {
        setLoadError(readableError(error, tRef.current))
        setLoading(false)
      }
    })
    return () => {
      disposed = true
      void task.destroy().catch(error => console.warn('PDF loading task cleanup failed', error))
    }
  }, [url, retry])

  useEffect(() => {
    setPageInput(String(page))
    if (document) callbacksRef.current.onPageChange?.(page)
  }, [page, document])

  useEffect(() => {
    if (document && locatorRef.current) goToPage(locatorRef.current.page)
  }, [locatorKey, document, goToPage])

  useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    const observer = new ResizeObserver(([entry]) => setContainerWidth(entry.contentRect.width))
    observer.observe(container)
    setContainerWidth(container.clientWidth)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const host = layersRef.current
    if (!document || !host) return
    let disposed = false
    let renderTask: ReturnType<PDFPageProxy['render']> | undefined
    let textLayer: TextLayer | undefined
    setRendering(true)
    setRenderError('')
    setGeometry(null)
    setSourceRectangle(null)
    textRef.current = null
    host.replaceChildren()
    scrollRef.current?.scrollTo({ top: 0, left: 0 })

    void (async () => {
      const pdfPage = await document.getPage(page)
      if (disposed) return
      const natural = pdfPage.getViewport({ scale: 1 })
      const scale = zoom === 'fit' ? clamp((containerWidth - 40) / natural.width, .15, 4) : zoom
      const viewport = pdfPage.getViewport({ scale })
      const canonical = pdfPage.getViewport({ scale: 1, rotation: 0 })
      const pageGeometry = { page, viewport, canonical }
      setGeometry(pageGeometry)
      // New canvas per render avoids concurrent-render reuse after rapid navigation.
      const canvas = window.document.createElement('canvas')
      const context = canvas.getContext('2d', { alpha: false })
      if (!context) throw new Error(tRef.current('pdfvCanvasError'))
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
      const outputScale = Math.min(pixelRatio, Math.sqrt(20_000_000 / (viewport.width * viewport.height)))
      canvas.width = Math.ceil(viewport.width * outputScale)
      canvas.height = Math.ceil(viewport.height * outputScale)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`
      canvas.className = 'pdfv-canvas'
      canvas.setAttribute('aria-hidden', 'true')
      const container = window.document.createElement('div')
      container.className = 'pdfv-text-layer'
      container.style.setProperty('--scale-factor', String(scale))
      container.style.width = `${viewport.width}px`
      container.style.height = `${viewport.height}px`
      host.replaceChildren(canvas, container)
      renderTask = pdfPage.render({
        canvasContext: context,
        viewport,
        transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
      })
      const canvasPromise = renderTask.promise
      // Start a handler immediately, even while text extraction is pending.
      const observedCanvas = canvasPromise.catch(error => { if (!disposed && !isCancelled(error)) throw error })
      const textPromise = (async () => {
        const content = await pdfPage.getTextContent()
        if (disposed) return
        setPageHasText(content.items.some(item => 'str' in item && item.str.trim().length > 0))
        textCacheRef.current.set(page, content.items.map(item => 'str' in item ? item.str : '').join(' '))
        textLayer = new TextLayer({ textContentSource: content, container, viewport })
        await textLayer.render()
        if (disposed) return
        textRef.current = container
      })()
      const outcomes = await Promise.allSettled([observedCanvas, textPromise])
      if (disposed) return
      const failed = outcomes.find(result => result.status === 'rejected')
      if (failed?.status === 'rejected') throw failed.reason
      setRendering(false)
      const activeLocator = locatorRef.current
      if (activeLocator?.page === page && activeLocator.source_text && !activeLocator.bbox) {
        setSourceRectangle(sourceTextRectangle(activeLocator.source_text, container))
      }
    })().catch(error => {
      if (!disposed && !isCancelled(error)) {
        setRenderError(`${tRef.current('pdfvPageRenderError')} · ${page}: ${errorMessage(error)}`)
        setRendering(false)
      }
    })
    return () => {
      disposed = true
      renderTask?.cancel()
      textLayer?.cancel()
    }
  }, [document, page, zoom, containerWidth, renderRetry])

  // Update source-text fallback on repeated evidence selection without repainting the page.
  useEffect(() => {
    const activeLocator = locatorRef.current
    if (!rendering && geometry?.page === page && activeLocator?.page === page && !activeLocator.bbox && activeLocator.source_text && textRef.current) {
      setSourceRectangle(sourceTextRectangle(activeLocator.source_text, textRef.current))
    } else {
      setSourceRectangle(null)
    }
  }, [locatorKey, geometry, rendering, page])

  const highlightedRectangle = useMemo(() => {
    if (!locator || locator.page !== page || geometry?.page !== page) return null
    return evidenceRectangle(locator, geometry) ?? sourceRectangle
  }, [locatorKey, page, geometry, sourceRectangle])

  useEffect(() => {
    if (!rendering && highlightedRectangle) {
      const frame = requestAnimationFrame(() => {
        const scroller = scrollRef.current
        const target = evidenceRef.current
        if (!scroller || !target) return
        const scrollBounds = scroller.getBoundingClientRect()
        const targetBounds = target.getBoundingClientRect()
        scroller.scrollTo({
          top: Math.max(0, scroller.scrollTop + targetBounds.top - scrollBounds.top - scrollBounds.height * .3),
          left: Math.max(0, scroller.scrollLeft + targetBounds.left - scrollBounds.left - 25),
          behavior: 'smooth',
        })
      })
      return () => cancelAnimationFrame(frame)
    }
  }, [locatorKey, highlightedRectangle, rendering])

  useEffect(() => {
    const generation = ++searchGenerationRef.current
    const needle = normalizeText(query)
    setResults([])
    setResultIndex(0)
    setSearchError('')
    setSearchProgress(0)
    if (!searchOpen || !document || !needle) {
      setSearching(false)
      return
    }
    setSearching(true)
    const timer = window.setTimeout(() => {
      void (async () => {
        const found: SearchResult[] = []
        for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
          if (generation !== searchGenerationRef.current) return
          let rawText = textCacheRef.current.get(pageNumber)
          if (rawText === undefined) {
            const searchPage = await document.getPage(pageNumber)
            const content = await searchPage.getTextContent()
            if (generation !== searchGenerationRef.current) return
            rawText = content.items.map(item => 'str' in item ? item.str : '').join(' ')
            textCacheRef.current.set(pageNumber, rawText)
          }
          const haystack = normalizeText(rawText)
          let count = 0
          let position = haystack.indexOf(needle)
          const first = position
          while (position !== -1) {
            count += 1
            position = haystack.indexOf(needle, position + needle.length)
          }
          if (count) found.push({ page: pageNumber, count, excerpt: haystack.slice(Math.max(0, first - 30), first + needle.length + 65) })
          setSearchProgress(pageNumber)
        }
        if (generation !== searchGenerationRef.current) return
        setResults(found)
        setSearching(false)
        if (found[0]) goToPage(found[0].page)
      })().catch(error => {
        if (generation === searchGenerationRef.current) {
          setSearching(false)
          setSearchError(`${tRef.current('pdfvSearchError')}: ${errorMessage(error)}`)
        }
      })
    }, 280)
    return () => {
      window.clearTimeout(timer)
      if (generation === searchGenerationRef.current) searchGenerationRef.current += 1
    }
  }, [query, searchOpen, document, goToPage])

  useEffect(() => {
    if (rendering || !textRef.current) return
    const needle = normalizeText(query)
    for (const element of textRef.current.querySelectorAll<HTMLElement>('span[role="presentation"]')) {
      element.classList.toggle('pdfv-search-match', searchOpen && Boolean(needle) && normalizeText(element.textContent ?? '').includes(needle))
    }
  }, [query, searchOpen, rendering, geometry])

  useEffect(() => {
    if (searchOpen) searchInputRef.current?.focus()
  }, [searchOpen])

  const captureSelection = () => {
    const selection = window.getSelection()
    const currentGeometry = geometryRef.current
    const textContainer = textRef.current
    if (!selection || selection.isCollapsed || !selection.rangeCount || !currentGeometry || !textContainer) return
    if (currentGeometry.page !== pageRef.current || !textContainer.contains(selection.anchorNode) || !textContainer.contains(selection.focusNode)) return
    const text = selection.toString().trim()
    if (!text) return
    const range = selection.getRangeAt(0)
    const origin = textContainer.getBoundingClientRect()
    const rects = Array.from(range.getClientRects()).filter(rect => rect.width > 0 && rect.height > 0)
    if (!rects.length) return
    const { viewport, canonical } = currentGeometry
    const points = rects.flatMap(rect => [
      [rect.left - origin.left, rect.top - origin.top],
      [rect.right - origin.left, rect.top - origin.top],
      [rect.left - origin.left, rect.bottom - origin.top],
      [rect.right - origin.left, rect.bottom - origin.top],
    ]).map(([x, y]) => {
      const [pdfX, pdfY] = viewport.convertToPdfPoint(x * viewport.width / origin.width, y * viewport.height / origin.height)
      return canonical.convertToViewportPoint(pdfX, pdfY)
    })
    const rect = rectangleFromPoints(points)
    const bbox = [
      clamp(rect.left, 0, canonical.width), clamp(rect.top, 0, canonical.height),
      clamp(rect.left + rect.width, 0, canonical.width), clamp(rect.top + rect.height, 0, canonical.height),
    ].map(value => Math.round(value * 100) / 100)
    callbacksRef.current.onSelection?.({ page: currentGeometry.page, text, bbox })
  }

  const jumpToOutline = async (entry: OutlineEntry) => {
    if (!document || !entry.destination) return
    const request = ++outlineRequestRef.current
    const documentGeneration = documentGenerationRef.current
    try {
      const destination = typeof entry.destination === 'string'
        ? await document.getDestination(entry.destination)
        : entry.destination
      if (!destination?.length) throw new Error(tRef.current('pdfvDestinationMissing'))
      const reference = destination[0]
      let index: number
      if (typeof reference === 'number') index = reference
      else if (reference && typeof reference === 'object' && 'num' in reference && 'gen' in reference) {
        index = await document.getPageIndex(reference as { num: number; gen: number })
      } else throw new Error(tRef.current('pdfvDestinationUnsupported'))
      if (request !== outlineRequestRef.current || documentGeneration !== documentGenerationRef.current) return
      goToPage(index + 1)
    } catch (error) {
      if (request === outlineRequestRef.current && documentGeneration === documentGenerationRef.current) {
        setNavigationError(`${tRef.current('pdfvOutlineJumpError')}: ${errorMessage(error)}`)
      }
    }
  }

  const download = async () => {
    if (!document || downloading) return
    setDownloading(true)
    setDownloadError('')
    const generation = documentGenerationRef.current
    try {
      const bytes = await document.getData()
      if (generation !== documentGenerationRef.current) return
      const blob = new Blob([new Uint8Array(bytes)], { type: 'application/pdf' })
      const objectUrl = URL.createObjectURL(blob)
      const anchor = window.document.createElement('a')
      const filename = url.split('?')[0].split('/').pop() || 'paper.pdf'
      anchor.href = objectUrl
      anchor.download = /\.pdf$/i.test(filename) ? filename : 'paper.pdf'
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    } catch (error) {
      if (generation === documentGenerationRef.current) setDownloadError(`${tRef.current('pdfvDownloadError')}: ${errorMessage(error)}`)
    } finally {
      if (generation === documentGenerationRef.current) setDownloading(false)
    }
  }

  const stepSearch = (direction: number) => {
    if (!results.length) return
    const index = (resultIndex + direction + results.length) % results.length
    setResultIndex(index)
    goToPage(results[index].page)
  }
  const currentScale = geometry?.viewport.scale ?? 1
  const stepZoom = (direction: number) => setZoom(clamp(Math.round((currentScale + direction * .2) * 100) / 100, .25, 4))
  const submitPage = () => {
    if (!pageInput.trim() || !Number.isFinite(Number(pageInput))) setPageInput(String(page))
    else { goToPage(Number(pageInput)); setPageInput(String(clamp(Math.round(Number(pageInput)), 1, document?.numPages ?? 1))) }
  }
  const selectedEvidenceOnPage = locator?.page === page
  const paragraphRegions = useMemo(() => !geometry || rendering ? [] : paragraphs.flatMap(paragraph =>
    paragraph.anchors.filter(anchor => anchor.page === page).flatMap((anchor, index) => {
      const rect = evidenceRectangle(anchor, geometry)
      return rect ? [{ paragraph, rect, key:`${paragraph.id}-${page}-${index}` }] : []
    })), [paragraphs, geometry, rendering, page])
  const hoveredRegion = paragraphRegions.find(region => region.key === hoveredRegionKey)
  const inspectParagraph: React.PointerEventHandler<HTMLDivElement> = event => {
    if ((event.target as HTMLElement).closest('.pdfv-paragraph-actions')) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = event.clientX - bounds.left, y = event.clientY - bounds.top
    const candidates = paragraphRegions.filter(({rect}) => x >= rect.left && x <= rect.left + rect.width && y >= rect.top && y <= rect.top + rect.height)
    const region = candidates.sort((a,b) => a.rect.width*a.rect.height - b.rect.width*b.rect.height)[0]
    if (region) setHoveredRegionKey(region.key)
    else if (!hoveredRegion || x < hoveredRegion.rect.left - 8 || x > hoveredRegion.rect.left + hoveredRegion.rect.width + 8 || y < hoveredRegion.rect.top - 40 || y > hoveredRegion.rect.top + hoveredRegion.rect.height + 8) setHoveredRegionKey(null)
  }

  return (
    <section className="pdfv-viewer" aria-label={t('pdfvViewer')}>
      <div className="pdfv-toolbar">
        <div className="pdfv-toolbar-group">
          <button className={`pdfv-icon-button ${outlineOpen ? 'pdfv-active' : ''}`} type="button" title={t('pdfvOutline')} aria-label={t('pdfvToggleOutline')} aria-expanded={outlineOpen} onClick={() => setOutlineOpen(!outlineOpen)}><List size={16} /></button>
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
          <button className={`pdfv-icon-button ${zoom === 'fit' ? 'pdfv-active' : ''}`} type="button" title={t('pdfvFitWidth')} aria-label={t('pdfvFitWidth')} disabled={!document} onClick={() => setZoom('fit')}><Maximize size={15} /></button>
        </div>
        <div className="pdfv-toolbar-group">
          <button className={`pdfv-icon-button ${searchOpen ? 'pdfv-active' : ''}`} type="button" title={t('pdfvSearch')} aria-label={t('pdfvSearch')} aria-expanded={searchOpen} disabled={!document} onClick={() => setSearchOpen(!searchOpen)}><Search size={15} /></button>
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
      {document && !rendering && !pageHasText && <div className="pdfv-notice" role="status"><FileText size={14} /><span>{t('pdfvScanned')}</span></div>}

      <div className="pdfv-body">
        {outlineOpen && <aside className="pdfv-outline" aria-label={t('pdfvOutline')}>
          <div className="pdfv-outline-heading"><strong>{t('pdfvOutline')}</strong><button className="pdfv-icon-button" type="button" aria-label={t('pdfvCloseOutline')} onClick={() => setOutlineOpen(false)}><X size={14} /></button></div>
          {outlineError ? <p className="pdfv-outline-message" role="alert">{outlineError}</p> : !outline.length ? <p className="pdfv-outline-message">{loading ? t('pdfvOutlineLoading') : t('pdfvNoOutline')}</p> : outline.map(entry => <button type="button" key={entry.id} className="pdfv-outline-entry" style={{ paddingLeft: `${12 + Math.min(entry.depth, 5) * 12}px` }} disabled={!entry.destination} onClick={() => void jumpToOutline(entry)} title={entry.title}><ChevronDown size={11} /><span>{entry.title || t('pdfvUnnamed')}</span></button>)}
        </aside>}
        <div ref={scrollRef} className="pdfv-scroll" aria-busy={loading || rendering}>
          {loading && <div className="pdfv-state" role="status"><LoaderCircle size={24} className="pdfv-spin" /><strong>{t('pdfvLoading')}</strong><span>{progress === null ? t('pdfvLoadingHint') : `${t('pdfvLoaded')} ${progress}%`}</span></div>}
          {!loading && loadError && <div className="pdfv-state pdfv-error-state" role="alert"><AlertCircle size={26} /><strong>{t('pdfvUnavailable')}</strong><p>{loadError}</p><button className="pdfv-retry" type="button" onClick={() => setRetry(value => value + 1)}><RotateCcw size={14} />{t('retry')}</button></div>}
          <div className={`pdfv-page-area ${!document ? 'pdfv-hidden' : ''}`}>
            <div className="pdfv-paper" onPointerMove={inspectParagraph} onPointerDown={inspectParagraph} onPointerLeave={() => setHoveredRegionKey(null)} style={{ width: geometry?.viewport.width ?? 0, height: geometry?.viewport.height ?? 0 }}>
              <div ref={layersRef} className="pdfv-layers" onMouseUp={captureSelection} onKeyUp={event => { if (event.key.startsWith('Arrow')) captureSelection() }} />
              {highlightedRectangle && !rendering && <div ref={evidenceRef} className="pdfv-evidence-overlay" style={highlightedRectangle} aria-label={`${t('pdfvEvidenceRegion')} · ${page} ${t('page')}`} />}
              {paragraphRegions.map(({paragraph,rect,key}) => <div key={key} className={`pdfv-paragraph-marker ${key===hoveredRegionKey?'hovered':''} ${paragraph.id===activeParagraphId?'selected':''}`} style={rect} aria-hidden="true" />)}
              {hoveredRegion && <div className="pdfv-paragraph-actions" style={{top:Math.max(4,hoveredRegion.rect.top-36),left:Math.max(4,Math.min(hoveredRegion.rect.left+hoveredRegion.rect.width-124,(geometry?.viewport.width??200)-132))}}>
                <button type="button" onClick={() => onTranslateParagraph?.(hoveredRegion.paragraph)}><Languages size={14}/>{t(translatedParagraphIds.includes(hoveredRegion.paragraph.id)?'expandTranslation':'translate')}</button>
              </div>}
            </div>
            {rendering && <div className="pdfv-page-loading" role="status"><LoaderCircle size={18} className="pdfv-spin" />{t('pdfvRendering')} · {page}</div>}
            {renderError && <div className="pdfv-state pdfv-render-error" role="alert"><AlertCircle size={23} /><p>{renderError}</p><button className="pdfv-retry" type="button" onClick={() => setRenderRetry(value => value + 1)}><RotateCcw size={14} />{t('pdfvRerender')}</button></div>}
          </div>
        </div>
      </div>
      <div className="pdfv-footer"><span>{selectedEvidenceOnPage ? <><span className="pdfv-evidence-dot" />{t(locator?.kind==='translation'?'translationSource':'pdfvEvidenceLocation')} · {page} {t('page')}{highlightedRectangle ? '' : ` · ${t('pdfvWholePage')}`}</> : t('pdfvSelectHint')}</span><span>{document ? `${document.numPages} ${t('page')} · ${t('pdfvOriginal')}` : t('pdfvLocal')}</span></div>
    </section>
  )
}
