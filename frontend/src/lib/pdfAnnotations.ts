import type { Note, NoteAnchor } from '../types'
import type { PageGeometry, Rectangle } from '../components/PdfPage'
import type { PdfSelection } from '../components/PdfViewer'

export interface PdfAnnotation { id:string; notes:Note[]; anchors:NoteAnchor[] }

export function noteAnchors(note:Note):NoteAnchor[] {
  return note.anchors?.length ? note.anchors : note.page && note.bbox ? [{page:note.page,bbox:note.bbox,rects:[]}] : []
}

export function paperAnnotations(notes:Note[]):PdfAnnotation[] {
  const groups = new Map<string,PdfAnnotation>()
  for (const note of notes) {
    const anchors = noteAnchors(note)
    if (!anchors.length) continue
    const key = JSON.stringify([note.source_text?.normalize('NFKC').replace(/\s/g,'').toLowerCase(),
      anchors.map(anchor=>[anchor.page,anchor.bbox.map(Math.round)])])
    const group = groups.get(key)
    if (group) group.notes.push(note)
    else groups.set(key,{id:note.id,notes:[note],anchors})
  }
  return Array.from(groups.values())
}

/** Restrict ranges to text nodes, excluding the full-page boxes a DOM Range
 * may return when it crosses PDF layers, columns, or page shells. */
export function selectedTextRects(range:Range,container:HTMLElement) {
  const rects:DOMRect[] = [], texts:string[] = []
  for (const span of container.querySelectorAll('span[role="presentation"]')) {
    const walker = document.createTreeWalker(span,NodeFilter.SHOW_TEXT)
    while (walker.nextNode()) {
      const node = walker.currentNode
      if (!range.intersectsNode(node)) continue
      const part = document.createRange()
      part.setStart(node,node===range.startContainer?range.startOffset:0)
      part.setEnd(node,node===range.endContainer?range.endOffset:node.textContent?.length??0)
      const text = part.toString()
      if (!text.trim()) continue
      texts.push(text)
      rects.push(...Array.from(part.getClientRects()).filter(rect=>rect.width>.1&&rect.height>.1))
    }
  }
  return {rects,text:texts.join(' ')}
}

/** Match old notes to exact text positions; a stored box disambiguates repeats. */
export function quoteRectangles(quote:string,container:HTMLElement,near?:Rectangle|null):Rectangle[] {
  const needle = quote.normalize('NFKC').toLowerCase().replace(/\s/g,'')
  if (!needle) return []
  const positions:{node:Node;start:number;end:number}[] = []
  let text = ''
  for (const span of container.querySelectorAll('span[role="presentation"]')) {
    const walker = document.createTreeWalker(span,NodeFilter.SHOW_TEXT)
    while (walker.nextNode()) {
      const node=walker.currentNode, original=node.textContent??''
      let offset=0
      for (const character of original) {
        const normalized=character.normalize('NFKC').toLowerCase().replace(/\s/g,'')
        text+=normalized
        // String search indexes UTF-16 units, including both halves of astral symbols.
        for (let unit=0;unit<normalized.length;unit++) positions.push({node,start:offset,end:offset+character.length})
        offset+=character.length
      }
    }
  }
  const origin=container.getBoundingClientRect()
  let best:Rectangle[]=[], distance=Infinity, at=text.indexOf(needle)
  while(at>=0) {
    const start=positions[at],end=positions[at+needle.length-1]
    const range=document.createRange();range.setStart(start.node,start.start);range.setEnd(end.node,end.end)
    const rects=selectedTextRects(range,container).rects.map(rect=>({left:rect.left-origin.left,top:rect.top-origin.top,width:rect.width,height:rect.height}))
    const first=rects[0]
    const next=first&&near?Math.hypot(first.left-near.left,first.top-near.top):0
    if(first&&next<distance){best=rects;distance=next}
    if(!near)break
    at=text.indexOf(needle,at+Math.max(1,needle.length))
  }
  return best
}

export function capturePdfSelection(range:Range,pages:{geometry:PageGeometry;container:HTMLElement}[]):PdfSelection|null {
  const anchors:NoteAnchor[]=[],texts:string[]=[]
  for(const {geometry,container} of pages) {
    const {rects,text}=selectedTextRects(range,container)
    if(!rects.length)continue
    const origin=container.getBoundingClientRect(),{viewport,canonical,page}=geometry
    const lines:number[][]=[]
    for(const rect of rects) {
      const points=[[rect.left,rect.top],[rect.right,rect.top],[rect.left,rect.bottom],[rect.right,rect.bottom]].map(([x,y])=>{
        const pdf=viewport.convertToPdfPoint((x-origin.left)*viewport.width/origin.width,(y-origin.top)*viewport.height/origin.height)
        return canonical.convertToViewportPoint(pdf[0],pdf[1])
      })
      const xs=points.map(p=>p[0]),ys=points.map(p=>p[1])
      const line=[Math.max(0,Math.min(...xs)),Math.max(0,Math.min(...ys)),Math.min(canonical.width,Math.max(...xs)),Math.min(canonical.height,Math.max(...ys))].map(v=>Math.round(v*100)/100)
      if(line[2]>line[0]&&line[3]>line[1]&&!lines.some(existing=>existing.every((v,i)=>Math.abs(v-line[i])<.05)))lines.push(line)
    }
    if(!lines.length)continue
    const bbox=[Math.min(...lines.map(r=>r[0])),Math.min(...lines.map(r=>r[1])),Math.max(...lines.map(r=>r[2])),Math.max(...lines.map(r=>r[3]))]
    anchors.push({page,bbox,rects:lines,page_width:canonical.width,page_height:canonical.height});texts.push(text)
  }
  if(!anchors.length)return null
  return {page:anchors[0].page,bbox:anchors[0].bbox,text:texts.join(' ').replace(/\s+/g,' ').trim(),anchors}
}
