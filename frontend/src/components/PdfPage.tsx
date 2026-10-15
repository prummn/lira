import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Languages, LoaderCircle, MessageSquare, RotateCcw } from 'lucide-react'
import { TextLayer } from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'
import { useUi } from '../lib/i18n'
import type { ReadingParagraph } from '../types'
import type { PdfLocator } from './PdfViewer'
import { quoteRectangles } from '../lib/pdfAnnotations'
import type { PdfAnnotation } from '../lib/pdfAnnotations'

export type Viewport = ReturnType<PDFPageProxy['getViewport']>
export interface PageGeometry { page: number; viewport: Viewport; canonical: Viewport }
export interface Rectangle { left: number; top: number; width: number; height: number }
export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))
export const normalizeText = (value: string) => value.normalize('NFKC').replace(/\s+/g, ' ').trim().toLowerCase()
const cancelled = (error: unknown) => error instanceof Error && /^(RenderingCancelledException|AbortException)$/.test(error.name)

function rectangleFromPoints(points: number[][]): Rectangle {
  const xs = points.map(point => point[0]), ys = points.map(point => point[1])
  const left = Math.min(...xs), top = Math.min(...ys)
  return { left, top, width: Math.max(...xs) - left, height: Math.max(...ys) - top }
}

/** Parser coordinates are unrotated, CropBox-relative, top-left page points. */
export function evidenceRectangle(locator: PdfLocator, geometry: PageGeometry): Rectangle | null {
  const bbox = locator.bbox
  if (!bbox || bbox.length !== 4 || !bbox.every(Number.isFinite)) return null
  const { canonical, viewport } = geometry
  const width = locator.page_width && locator.page_width > 0 ? locator.page_width : canonical.width
  const height = locator.page_height && locator.page_height > 0 ? locator.page_height : canonical.height
  const [x0, y0, x1, y1] = bbox
  if (x1 <= x0 || y1 <= y0) return null
  const transform = (x: number, y: number) => {
    const [pdfX, pdfY] = canonical.convertToPdfPoint(clamp(x / width, 0, 1) * canonical.width, clamp(y / height, 0, 1) * canonical.height)
    return viewport.convertToViewportPoint(pdfX, pdfY)
  }
  const rectangle = rectangleFromPoints([transform(x0, y0), transform(x1, y0), transform(x0, y1), transform(x1, y1)])
  return rectangle.width > 0 && rectangle.height > 0 ? rectangle : null
}

/** Match across PDF.js spans as well as inside an individual span. */
export function sourceTextRectangle(source: string, container: HTMLElement, mark = false): Rectangle | null {
  const needle = normalizeText(source)
  let combined = ''
  const spans: { element: HTMLElement; start: number; end: number }[] = []
  for (const element of container.querySelectorAll<HTMLElement>('span[role="presentation"]')) {
    if (mark) element.classList.remove('pdfv-search-match')
    const text = normalizeText(element.textContent ?? '')
    if (!text) continue
    if (combined) combined += ' '
    const start = combined.length
    combined += text
    spans.push({ element, start, end: combined.length })
  }
  if (needle.length < (mark ? 1 : 3)) return null
  const position = combined.indexOf(needle)
  if (position === -1) return null
  const matched = spans.filter(span => span.end > position && span.start < position + needle.length)
  if (!matched.length) return null
  if (mark) {
    let at = position
    while (at !== -1) {
      for (const span of spans) if (span.end > at && span.start < at + needle.length) span.element.classList.add('pdfv-search-match')
      at = combined.indexOf(needle, at + needle.length)
    }
  }
  const origin = container.getBoundingClientRect()
  return rectangleFromPoints(matched.flatMap(({ element }) => {
    const rect = element.getBoundingClientRect()
    return [[rect.left - origin.left, rect.top - origin.top], [rect.right - origin.left, rect.bottom - origin.top]]
  }))
}

interface PdfPageProps {
  document: PDFDocumentProxy
  geometry: PageGeometry
  active: boolean
  maxPixels: number
  locator?: PdfLocator | null
  query: string
  paragraphs: ReadingParagraph[]
  activeParagraphId?: string | null
  translatedParagraphIds: string[]
  onTranslateParagraph?: (paragraph: ReadingParagraph) => void
  annotations:PdfAnnotation[]
  activeNoteId?:string|null
  onOpenAnnotation?:(annotation:PdfAnnotation)=>void
  onText: (page: number, text: string) => void
  onReady: (page: number, container: HTMLElement, hasText: boolean) => void
}

/** Only this component owns page resources; shells retain their measured size. */
export function PdfPage({ document, geometry, active, maxPixels, locator, query, paragraphs, activeParagraphId, translatedParagraphIds, onTranslateParagraph, annotations, activeNoteId, onOpenAnnotation, onText, onReady }: PdfPageProps) {
  const { t } = useUi()
  const hostRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLDivElement | null>(null)
  const callbacks = useRef({ onText, onReady })
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [source, setSource] = useState<Rectangle | null>(null)
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)
  const [hoveredNote,setHoveredNote]=useState<string|null>(null)
  callbacks.current = { onText, onReady }
  const { page, viewport } = geometry
  const locatorKey = locator ? JSON.stringify(locator) : ''

  useEffect(() => {
    const host = hostRef.current
    if (!active || !host) return
    let disposed = false
    let pdfPage: PDFPageProxy | undefined
    let renderTask: ReturnType<PDFPageProxy['render']> | undefined
    let textLayer: TextLayer | undefined
    let canvas: HTMLCanvasElement | undefined
    setReady(false); setError(''); setSource(null)
    void (async () => {
      pdfPage = await document.getPage(page)
      if (disposed) return
      canvas = window.document.createElement('canvas')
      const context = canvas.getContext('2d', { alpha: false })
      if (!context) throw new Error('Canvas is unavailable')
      const outputScale = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(maxPixels / (viewport.width * viewport.height)))
      canvas.width = Math.ceil(viewport.width * outputScale)
      canvas.height = Math.ceil(viewport.height * outputScale)
      context.fillStyle = '#fff'
      context.fillRect(0, 0, canvas.width, canvas.height)
      canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`
      canvas.className = 'pdfv-canvas'
      canvas.dataset.pageNumber = String(page)
      canvas.setAttribute('aria-hidden', 'true')
      const container = window.document.createElement('div')
      container.className = 'pdfv-text-layer'
      container.dataset.pageNumber = String(page)
      container.style.setProperty('--scale-factor', String(viewport.scale))
      container.style.width = `${viewport.width}px`; container.style.height = `${viewport.height}px`
      host.replaceChildren(canvas, container)
      renderTask = pdfPage.render({ canvasContext: context, viewport, transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0] })
      const canvasPromise = renderTask.promise.catch(error => { if (!disposed && !cancelled(error)) throw error })
      const textPromise = (async () => {
        const content = await pdfPage!.getTextContent()
        if (disposed) return
        const text = content.items.map(item => 'str' in item ? item.str : '').join(' ')
        callbacks.current.onText(page, text)
        textLayer = new TextLayer({ textContentSource: content, container, viewport })
        await textLayer.render()
        if (disposed) return
        textRef.current = container
        return Boolean(text.trim())
      })()
      const outcomes = await Promise.allSettled([canvasPromise, textPromise])
      if (disposed) return
      const failed = outcomes.find(result => result.status === 'rejected')
      if (failed?.status === 'rejected') throw failed.reason
      setReady(true)
      callbacks.current.onReady(page, container, outcomes[1].status === 'fulfilled' && Boolean(outcomes[1].value))
    })().catch(error => {
      if (!disposed && !cancelled(error)) setError(error instanceof Error ? error.message : String(error))
    }).finally(() => { if (disposed) pdfPage?.cleanup() })
    return () => {
      disposed = true
      renderTask?.cancel(); textLayer?.cancel()
      textRef.current = null
      host.replaceChildren()
      if (canvas) { canvas.width = 0; canvas.height = 0 }
      pdfPage?.cleanup()
    }
  }, [document, page, viewport, active, maxPixels, retry])

  useEffect(() => {
    setSource(ready && locator?.source_text && !locator.bbox && textRef.current ? sourceTextRectangle(locator.source_text, textRef.current) : null)
  }, [locatorKey, ready, viewport])
  useEffect(() => {
    if (ready && textRef.current) sourceTextRectangle(query, textRef.current, true)
  }, [query, ready, viewport])

  const highlighted = locator?.page === page ? evidenceRectangle(locator, geometry) ?? source : null
  const regions = useMemo(() => !active || !ready ? [] : paragraphs.flatMap(paragraph => paragraph.anchors.filter(anchor => anchor.page === page).flatMap((anchor, index) => {
    const rect = evidenceRectangle(anchor, geometry)
    return rect ? [{ paragraph, rect, key: `${paragraph.id}-${page}-${index}` }] : []
  })), [paragraphs, geometry, active, ready, page])
  const hovered = regions.find(region => region.key === hoveredKey)
  const noteRegions=useMemo(()=>!active||!ready?[]:annotations.flatMap(annotation=>annotation.anchors.filter(anchor=>anchor.page===page).flatMap(anchor=>{
    const box=evidenceRectangle(anchor,geometry)
    const legacy=!anchor.rects.length&&annotation.notes[0].source_text&&textRef.current?quoteRectangles(annotation.notes[0].source_text,textRef.current,box):[]
    const rects=anchor.rects.length?anchor.rects.map(bbox=>evidenceRectangle({...anchor,bbox},geometry)).filter((rect):rect is Rectangle=>!!rect):legacy.length?legacy:box?[box]:[]
    return rects.length?[{annotation,rects}]:[]
  })),[active,ready,annotations,geometry,page])
  const noteAt=(x:number,y:number)=>noteRegions.filter(region=>region.rects.some(rect=>x>=rect.left&&x<=rect.left+rect.width&&y>=rect.top&&y<=rect.top+rect.height))
    .sort((a,b)=>a.rects.reduce((sum,rect)=>sum+rect.width*rect.height,0)-b.rects.reduce((sum,rect)=>sum+rect.width*rect.height,0))[0]
  const inspect: React.PointerEventHandler<HTMLDivElement> = event => {
    if ((event.target as HTMLElement).closest('.pdfv-paragraph-actions')) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = event.clientX - bounds.left, y = event.clientY - bounds.top
    setHoveredNote(noteAt(x,y)?.annotation.id??null)
    const found = regions.filter(({ rect }) => x >= rect.left && x <= rect.left + rect.width && y >= rect.top && y <= rect.top + rect.height).sort((a, b) => a.rect.width * a.rect.height - b.rect.width * b.rect.height)[0]
    if (found) setHoveredKey(found.key)
    else if (!hovered || x < hovered.rect.left - 8 || x > hovered.rect.left + hovered.rect.width + 8 || y < hovered.rect.top - 40 || y > hovered.rect.top + hovered.rect.height + 8) setHoveredKey(null)
  }
  return <div className={`pdfv-page-shell pdfv-paper ${hoveredNote?'pdfv-over-note':''}`} data-page-number={page} data-rendered={active && ready ? 'true' : 'false'} style={{ width: viewport.width, height: viewport.height }} onPointerMove={inspect} onPointerDown={inspect} onPointerLeave={() => {setHoveredKey(null);setHoveredNote(null)}} onClick={event=>{
    if(!(event.target as HTMLElement).closest('.pdfv-layers')||!window.getSelection()?.isCollapsed)return
    const origin=event.currentTarget.getBoundingClientRect(),region=noteAt(event.clientX-origin.left,event.clientY-origin.top)
    if(region)onOpenAnnotation?.(region.annotation)
  }}>
    <div ref={hostRef} className="pdfv-layers" />
    {noteRegions.map(({annotation,rects})=><div className={`pdfv-note-group ${annotation.notes.some(note=>note.id===activeNoteId)?'is-active':''} ${hoveredNote===annotation.id?'is-hovered':''}`} key={annotation.id}>
      {rects.map((rect,index)=><div key={index} className="pdfv-note-highlight" data-note-id={annotation.id} style={rect} aria-hidden="true"/>)}
      <button type="button" className="pdfv-note-marker" aria-label={t('openLinkedNotes')} title={annotation.notes.map(note=>note.kind==='highlight'?t('annotationAddThought'):note.content).join('\n').slice(0,180)} aria-pressed={annotation.notes.some(note=>note.id===activeNoteId)} style={{left:Math.max(3,rects[0].left-25),top:Math.max(3,rects[0].top-4)}} onClick={()=>onOpenAnnotation?.(annotation)}><MessageSquare size={13}/>{annotation.notes.length>1&&<span>{annotation.notes.length}</span>}</button>
    </div>)}
    {active && ready && highlighted && <div className="pdfv-evidence-overlay" style={highlighted} aria-label={`${t('pdfvEvidenceRegion')} · ${page} ${t('page')}`} />}
    {regions.map(({ paragraph, rect, key }) => <div key={key} className={`pdfv-paragraph-marker ${key === hoveredKey ? 'hovered' : ''} ${paragraph.id === activeParagraphId ? 'selected' : ''}`} style={rect} aria-hidden="true" />)}
    {hovered && <div className="pdfv-paragraph-actions" style={{ top: Math.max(4, hovered.rect.top - 36), left: Math.max(4, Math.min(hovered.rect.left + hovered.rect.width - 124, viewport.width - 132)) }}><button type="button" onClick={() => onTranslateParagraph?.(hovered.paragraph)}><Languages size={14} />{t(translatedParagraphIds.includes(hovered.paragraph.id) ? 'expandTranslation' : 'translate')}</button></div>}
    {active && !ready && !error && <div className="pdfv-page-placeholder" role="status"><LoaderCircle size={18} className="pdfv-spin" />{t('pdfvRendering')} · {page}</div>}
    {active && error && <div className="pdfv-state pdfv-page-error" role="alert"><AlertCircle size={23} /><p>{t('pdfvPageRenderError')} · {page}: {error}</p><button className="pdfv-retry" type="button" onClick={() => setRetry(value => value + 1)}><RotateCcw size={14} />{t('pdfvRerender')}</button></div>}
  </div>
}
