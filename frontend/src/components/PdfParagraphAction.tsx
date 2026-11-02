import { useLayoutEffect, type RefObject } from 'react'
import { Languages } from 'lucide-react'
import type { Rectangle } from './PdfPage'

interface Props {
  pageRef: RefObject<HTMLDivElement>
  actionRef: RefObject<HTMLDivElement>
  rect: Rectangle
  label: string
  activate: () => void
}

/** Keep the action beside its source and inside the visible PDF reading area. */
export function PdfParagraphAction({pageRef,actionRef,rect,label,activate}:Props) {
  useLayoutEffect(()=>{
    const page=pageRef.current,action=actionRef.current
    const scroller=page?.closest<HTMLElement>('.pdfv-scroll')
    if(!page||!action||!scroller)return
    let frame=0
    const place=()=>{
      const paper=page.getBoundingClientRect(),clip=scroller.getBoundingClientRect()
      const inset=6,gap=8
      const left=Math.max(0,paper.left,clip.left+scroller.clientLeft)+inset
      const right=Math.min(window.innerWidth,paper.right,clip.left+scroller.clientLeft+scroller.clientWidth)-inset
      const top=Math.max(0,paper.top,clip.top+scroller.clientTop)+inset
      const bottom=Math.min(window.innerHeight,paper.bottom,clip.top+scroller.clientTop+scroller.clientHeight)-inset
      const source={left:paper.left+rect.left,right:paper.left+rect.left+rect.width,top:paper.top+rect.top,bottom:paper.top+rect.top+rect.height}
      if(right-left<32||bottom-top<32||source.right<left||source.left>right||source.bottom<top||source.top>bottom){action.style.visibility='hidden';return}
      action.style.maxWidth=`${right-left}px`
      action.dataset.compact='false'
      let width=action.offsetWidth,height=action.offsetHeight
      let x:number,y:number
      if(right-source.right>=width+gap){x=source.right+gap;y=source.top}
      else if(source.left-left>=width+gap){x=source.left-width-gap;y=source.top}
      else {
        x=source.right-width;y=source.top-height-gap
        // A clipped paragraph needs its action next to the lines still visible.
        if(y<top){
          action.dataset.compact='true'
          width=action.offsetWidth;height=action.offsetHeight
          x=right-source.right>=width+gap?source.right+gap:source.left-left>=width+gap?source.left-width-gap:source.right-width
          y=Math.max(top,source.top)
        }
      }
      action.style.left=`${Math.max(left,Math.min(right-width,x))-paper.left}px`
      action.style.top=`${Math.max(top,Math.min(bottom-height,y))-paper.top}px`
      action.style.visibility='visible'
    }
    const schedule=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(place)}
    place()
    const observer=new ResizeObserver(schedule)
    observer.observe(page);observer.observe(scroller)
    document.addEventListener('scroll',schedule,true)
    window.addEventListener('resize',schedule)
    return()=>{cancelAnimationFrame(frame);observer.disconnect();document.removeEventListener('scroll',schedule,true);window.removeEventListener('resize',schedule)}
  },[pageRef,actionRef,rect,label])
  return <div ref={actionRef} className="pdfv-paragraph-actions" style={{visibility:'hidden'}}><button type="button" onClick={activate} aria-label={label} title={label}><Languages size={14}/><span className="pdfv-paragraph-action-label">{label}</span></button></div>
}
