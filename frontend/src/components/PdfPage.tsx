import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, ChartNoAxesCombined, LoaderCircle, MessageSquare, RotateCcw, Table2 } from 'lucide-react'
import { TextLayer } from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'
import { useUi } from '../lib/i18n'
import type { ReadingParagraph, TranslationQueueEntry } from '../types'
import type { PdfLocator, PdfRegionSelection } from './PdfViewer'
import type { PdfVisualRegion } from '../types'
import { quoteRectangles } from '../lib/pdfAnnotations'
import type { PdfAnnotation } from '../lib/pdfAnnotations'
import { queueItemLabel } from './TranslationQueueProgress'
import { isActiveTranslationQueueItem } from '../lib/useTranslationQueue'
import { PdfParagraphAction } from './PdfParagraphAction'

export type Viewport = ReturnType<PDFPageProxy['getViewport']>
export interface PageGeometry { page: number; viewport: Viewport; canonical: Viewport }
export interface Rectangle { left: number; top: number; width: number; height: number }
export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))
export const normalizeText = (value: string) => value.normalize('NFKC').replace(/\s+/g, ' ').trim().toLowerCase()
const cancelled = (error: unknown) => error instanceof Error && /^(RenderingCancelledException|AbortException)$/.test(error.name)

// Keep the note affordance in the paper margin whenever there is room. When
// an annotation touches both margins, put a compact marker in the page-area
// gutter instead of clamping it over the first line of the selection.
const NOTE_MARKER_WIDTH = 30
const NOTE_MARKER_EDGE_WIDTH = 18
const NOTE_MARKER_GAP = 6
type NoteMarkerPlacement = { left: number; top: number; side: 'left' | 'right' | 'edge-left' | 'edge-right' }

export function noteMarkerPlacement(rect: Rectangle, pageWidth: number, pageHeight: number): NoteMarkerPlacement {
  const leftRoom = Math.max(0, rect.left)
  const rightRoom = Math.max(0, pageWidth - (rect.left + rect.width))
  let side: NoteMarkerPlacement['side']
  let left: number
  if (leftRoom >= NOTE_MARKER_WIDTH + NOTE_MARKER_GAP) {
    side = 'left'
    left = rect.left - NOTE_MARKER_WIDTH - NOTE_MARKER_GAP
  } else if (rightRoom >= NOTE_MARKER_WIDTH + NOTE_MARKER_GAP) {
    side = 'right'
    left = rect.left + rect.width + NOTE_MARKER_GAP
  } else if (leftRoom >= rightRoom) {
    side = 'edge-left'
    left = -NOTE_MARKER_EDGE_WIDTH
  } else {
    side = 'edge-right'
    left = pageWidth
  }
  const markerHeight = side.startsWith('edge-') ? 22 : 28
  return { left, top: clamp(rect.top - 1, 4, Math.max(4, pageHeight - markerHeight - 4)), side }
}

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
  visualRegions: PdfVisualRegion[]
  onAskVisualRegion?: (selection: PdfRegionSelection) => void
  activeParagraphId?: string | null
  translatedParagraphIds: string[]
  paragraphQueueItems?: Record<string,TranslationQueueEntry>
  onTranslateParagraph?: (paragraph: ReadingParagraph) => void
  annotations:PdfAnnotation[]
  activeNoteId?:string|null
  onOpenAnnotation?:(annotation:PdfAnnotation)=>void
  onText: (page: number, text: string) => void
  onReady: (page: number, container: HTMLElement, hasText: boolean) => void
}

/** Only this component owns page resources; shells retain their measured size. */
export function PdfPage({ document, geometry, active, maxPixels, locator, query, paragraphs, visualRegions, onAskVisualRegion, activeParagraphId, translatedParagraphIds, paragraphQueueItems={}, onTranslateParagraph, annotations, activeNoteId, onOpenAnnotation, onText, onReady }: PdfPageProps) {
  const { t } = useUi()
  const hostRef = useRef<HTMLDivElement>(null)
  const pageRef = useRef<HTMLDivElement>(null)
  const actionRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLDivElement | null>(null)
  const callbacks = useRef({ onText, onReady })
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [source, setSource] = useState<Rectangle | null>(null)
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)
  const [hoveredNote,setHoveredNote]=useState<string|null>(null)
  const [hoveredVisualId,setHoveredVisualId]=useState<string|null>(null)
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
  const visualCandidates=useMemo(()=>!active||!ready?[]:visualRegions.filter(region=>region.page===page).flatMap(region=>{
    const rect=evidenceRectangle({page:region.page,bbox:region.bbox,page_width:region.page_width,page_height:region.page_height},geometry)
    return rect?[{region,rect}]:[]
  }),[active,ready,visualRegions,geometry,page])
  const hoveredVisual=visualCandidates.find(candidate=>candidate.region.id===hoveredVisualId)
  const hoveredQueueItem=hovered?paragraphQueueItems[hovered.paragraph.id]:undefined
  const hoveredCached=!!hovered&&translatedParagraphIds.includes(hovered.paragraph.id)
  const paragraphActionLabel=hoveredCached?t('expandTranslation'):isActiveTranslationQueueItem(hoveredQueueItem)?`${queueItemLabel(hoveredQueueItem,t)} · ${t('queuePromote')}`:hoveredQueueItem?.job_status==='paused'?`${t('queuePaused')} · ${t('translate')}`:hoveredQueueItem?.status==='failed'?`${t('batchFailed')} · ${t('retry')}`:t('translate')
  const noteRegions=useMemo(()=>!active||!ready?[]:annotations.flatMap(annotation=>annotation.anchors.filter(anchor=>anchor.page===page).flatMap(anchor=>{
    const box=evidenceRectangle(anchor,geometry)
    const legacy=!anchor.rects.length&&annotation.notes[0].source_text&&textRef.current?quoteRectangles(annotation.notes[0].source_text,textRef.current,box):[]
    const rects=anchor.rects.length?anchor.rects.map(bbox=>evidenceRectangle({...anchor,bbox},geometry)).filter((rect):rect is Rectangle=>!!rect):legacy.length?legacy:box?[box]:[]
    return rects.length?[{annotation,rects}]:[]
  })),[active,ready,annotations,geometry,page])
  const noteAt=(x:number,y:number)=>noteRegions.filter(region=>region.annotation.notes.some(note=>note.kind!=='highlight'))
    .filter(region=>region.rects.some(rect=>x>=rect.left&&x<=rect.left+rect.width&&y>=rect.top&&y<=rect.top+rect.height))
    .sort((a,b)=>a.rects.reduce((sum,rect)=>sum+rect.width*rect.height,0)-b.rects.reduce((sum,rect)=>sum+rect.width*rect.height,0))[0]
  const askVisualRegion=(region:PdfVisualRegion)=>{
    if(!onAskVisualRegion)return
    const rectangle=evidenceRectangle({page:region.page,bbox:region.bbox,page_width:region.page_width,page_height:region.page_height},geometry)
    const canvas=hostRef.current?.querySelector<HTMLCanvasElement>('.pdfv-canvas')
    if(!canvas||!rectangle||rectangle.width<12||rectangle.height<12)return
    const scaleX=canvas.width/viewport.width,scaleY=canvas.height/viewport.height
    // Detected tables already include a PDF-space safety margin. Adding a
    // second screen-space margin can pull in the next table's caption.
    const padX=region.kind==='table'?0:Math.min(14,rectangle.width*.04),padY=region.kind==='table'?0:Math.min(14,rectangle.height*.05)
    const left=clamp(rectangle.left-padX,0,viewport.width),top=clamp(rectangle.top-padY,0,viewport.height)
    const right=clamp(rectangle.left+rectangle.width+padX,0,viewport.width),bottom=clamp(rectangle.top+rectangle.height+padY,0,viewport.height)
    const sx=clamp(Math.round(left*scaleX),0,Math.max(0,canvas.width-1))
    const sy=clamp(Math.round(top*scaleY),0,Math.max(0,canvas.height-1))
    const sw=clamp(Math.round((right-left)*scaleX),1,canvas.width-sx)
    const sh=clamp(Math.round((bottom-top)*scaleY),1,canvas.height-sy)
    const maxWidth=1800,scale=Math.min(1,maxWidth/sw)
    const output=window.document.createElement('canvas')
    output.width=Math.max(1,Math.round(sw*scale)); output.height=Math.max(1,Math.round(sh*scale))
    const context=output.getContext('2d'); if(!context)return
    context.fillStyle='#fff'; context.fillRect(0,0,output.width,output.height)
    context.drawImage(canvas,sx,sy,sw,sh,0,0,output.width,output.height)
    const host=hostRef.current,origin=host?.getBoundingClientRect()
    const cropText=host&&origin?Array.from(host.querySelectorAll<HTMLElement>('.pdfv-text-layer span[role="presentation"]')).map(element=>{
      const box=element.getBoundingClientRect(),x0=box.left-origin.left,y0=box.top-origin.top
      const overlap=Math.max(0,Math.min(x0+box.width,rectangle.left+rectangle.width)-Math.max(x0,rectangle.left))
        *Math.max(0,Math.min(y0+box.height,rectangle.top+rectangle.height)-Math.max(y0,rectangle.top))
      return {text:element.textContent?.replace(/\s+/g,' ').trim()??'',top:y0,left:x0,overlap}
    }).filter(item=>item.text&&item.overlap>0).sort((a,b)=>Math.abs(a.top-b.top)<4?a.left-b.left:a.top-b.top).map(item=>item.text).join(' '):''
    const selectedText=[region.caption,cropText].filter(Boolean).join('\n').replace(/\s+/g,' ').trim().slice(0,12000)
    onAskVisualRegion({page,kind:region.kind,label:region.label,imageDataUrl:output.toDataURL('image/jpeg',.88),selectedText,bbox:region.bbox})
  }
  const inspect: React.PointerEventHandler<HTMLDivElement> = event => {
    if ((event.target as HTMLElement).closest('.pdfv-paragraph-actions')) return
    // Keep the source stable while the pointer crosses the gap to its action.
    if(hovered&&actionRef.current){
      const action=actionRef.current.getBoundingClientRect(),paper=event.currentTarget.getBoundingClientRect()
      const left=paper.left+hovered.rect.left,right=left+hovered.rect.width,top=paper.top+hovered.rect.top
      const x=event.clientX,y=event.clientY,pad=8
      const bridge=action.right<=left?x>=action.left-pad&&x<=left+pad&&y>=action.top-pad&&y<=action.bottom+pad
        :action.left>=right?x>=right-pad&&x<=action.right+pad&&y>=action.top-pad&&y<=action.bottom+pad
        :action.bottom<=top?x>=action.left-pad&&x<=action.right+pad&&y>=action.top-pad&&y<=top+pad:false
      if(bridge)return
    }
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = event.clientX - bounds.left, y = event.clientY - bounds.top
    setHoveredNote(noteAt(x,y)?.annotation.id??null)
    const visual=visualCandidates.filter(({rect})=>x>=rect.left&&x<=rect.left+rect.width&&y>=rect.top&&y<=rect.top+rect.height).sort((a,b)=>a.rect.width*a.rect.height-b.rect.width*b.rect.height)[0]
    if(visual)setHoveredVisualId(visual.region.id)
    else if(!hoveredVisual||x<hoveredVisual.rect.left-12||x>hoveredVisual.rect.left+hoveredVisual.rect.width+12||y<hoveredVisual.rect.top-38||y>hoveredVisual.rect.top+hoveredVisual.rect.height+12)setHoveredVisualId(null)
    const found = regions.filter(({ rect }) => x >= rect.left && x <= rect.left + rect.width && y >= rect.top && y <= rect.top + rect.height).sort((a, b) => a.rect.width * a.rect.height - b.rect.width * b.rect.height)[0]
    if (found) setHoveredKey(found.key)
    else if (!hovered || x < hovered.rect.left - 8 || x > viewport.width + 25 || y < hovered.rect.top - 40 || y > hovered.rect.top + hovered.rect.height + 8) setHoveredKey(null)
  }
  return <div ref={pageRef} className={`pdfv-page-shell pdfv-paper ${hoveredNote?'pdfv-over-note':''}`} data-page-number={page} data-rendered={active && ready ? 'true' : 'false'} style={{ width: viewport.width, height: viewport.height }} onPointerMove={inspect} onPointerLeave={() => {setHoveredKey(null);setHoveredNote(null);setHoveredVisualId(null)}} onClick={event=>{
    if(!(event.target as HTMLElement).closest('.pdfv-layers')||!window.getSelection()?.isCollapsed)return
    const origin=event.currentTarget.getBoundingClientRect(),region=noteAt(event.clientX-origin.left,event.clientY-origin.top)
    if(region)onOpenAnnotation?.(region.annotation)
  }}>
    <div ref={hostRef} className="pdfv-layers" />
    {noteRegions.map(({annotation,rects})=>{
      const marker = noteMarkerPlacement(rects[0], viewport.width, viewport.height)
      const semanticNotes = annotation.notes.filter(note => note.kind !== 'highlight')
      const markerKinds = [...new Set(annotation.notes.map(note => note.kind))]
      // If a highlight and a semantic note share an anchor, use the semantic
      // note's accent. Pure highlights remain amber; the data attribute keeps
      // all linked kinds inspectable for accessible styling and tests.
      const markerKind = annotation.notes.find(note => note.kind !== 'highlight')?.kind ?? 'highlight'
      return <div className={`pdfv-note-group pdfv-note-group-kind-${markerKind} ${annotation.notes.some(note=>note.id===activeNoteId)?'is-active':''} ${hoveredNote===annotation.id?'is-hovered':''}`} key={annotation.id}>
      {rects.map((rect,index)=><div key={index} className="pdfv-note-highlight" data-note-id={annotation.id} style={rect} aria-hidden="true"/>)}
        {semanticNotes.length>0&&<button type="button" className={`pdfv-note-marker pdfv-note-marker-${marker.side} pdfv-note-marker-kind-${markerKind}`} data-marker-placement={marker.side} data-note-kinds={markerKinds.join(' ')} aria-label={t('openLinkedNotes')} title={annotation.notes.map(note=>note.kind==='highlight'?t('annotationAddThought'):note.content).join('\n').slice(0,180)} aria-pressed={annotation.notes.some(note=>note.id===activeNoteId)} style={{left:marker.left,top:marker.top}} onClick={()=>onOpenAnnotation?.(annotation)}><MessageSquare size={13}/>{annotation.notes.length>1&&<span>{annotation.notes.length}</span>}</button>}
      </div>
    })}
    {active && ready && highlighted && <div className="pdfv-evidence-overlay" style={highlighted} aria-label={`${t('pdfvEvidenceRegion')} · ${page} ${t('page')}`} />}
    {visualCandidates.map(({region,rect})=><div key={region.id} data-visual-id={region.id} data-visual-kind={region.kind} className={`pdfv-visual-region ${hoveredVisualId===region.id?'is-hovered':''}`} style={rect} aria-hidden="true"/>)}
    {hoveredVisual&&onAskVisualRegion&&<button type="button" className={`pdfv-visual-region-action ${hoveredVisual.region.kind}`} style={{left:clamp(hoveredVisual.rect.left,4,Math.max(4,viewport.width-150)),top:Math.max(4,hoveredVisual.rect.top-32)}} aria-label={`${t('pdfvAskVisual')} ${hoveredVisual.region.label}`} title={hoveredVisual.region.caption} onClick={()=>askVisualRegion(hoveredVisual.region)}>{hoveredVisual.region.kind==='table'?<Table2 size={14}/>:<ChartNoAxesCombined size={14}/>}<span>{t('pdfvAskVisual')} {hoveredVisual.region.label}</span></button>}
    {regions.map(({ paragraph, rect, key }) => <div key={key} className={`pdfv-paragraph-marker ${key === hoveredKey ? 'hovered' : ''} ${paragraph.id === activeParagraphId ? 'selected' : ''}`} style={rect} aria-hidden="true" />)}
    {hovered && <PdfParagraphAction pageRef={pageRef} actionRef={actionRef} rect={hovered.rect} label={paragraphActionLabel} activate={()=>onTranslateParagraph?.(hovered.paragraph)}/>}
    {active && !ready && !error && <div className="pdfv-page-placeholder" role="status"><LoaderCircle size={18} className="pdfv-spin" />{t('pdfvRendering')} · {page}</div>}
    {active && error && <div className="pdfv-state pdfv-page-error" role="alert"><AlertCircle size={23} /><p>{t('pdfvPageRenderError')} · {page}: {error}</p><button className="pdfv-retry" type="button" onClick={() => setRetry(value => value + 1)}><RotateCcw size={14} />{t('pdfvRerender')}</button></div>}
  </div>
}
