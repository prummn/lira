import { useRef } from 'react'
import { ArrowDownToLine, BookOpen, CheckCircle2, ChevronLeft, ChevronRight, Columns2, Languages, LoaderCircle, ScanText, X } from 'lucide-react'
import type { ReadingParagraph, ReadingTranslation, TranslationQueueEntry } from '../types'
import { useUi } from '../lib/i18n'
import { ScientificText } from './ScientificText'
import type { PdfSelection } from './PdfViewer'
import { queueItemLabel } from './TranslationQueueProgress'
import { isActiveTranslationQueueItem } from '../lib/useTranslationQueue'

export function TranslationPanel({paragraphs, selected, translation, pending, checking, review, retrySelected, regenerate, error, available, page, layout, sideAvailable, setLayout, choose, translate, close, loading, retry, batchMode, batchScope, batchSelectedIds, translatedParagraphIds, batchRunning, queueItem, queueItems, onToggleBatchMode, onBatchScopeChange, onToggleBatchParagraph, onStartBatch, onStartFull, onSelection}:{
  paragraphs:ReadingParagraph[];selected:ReadingParagraph|null;translation?:ReadingTranslation;
  pending:boolean;error:string;available:boolean;page:number;layout:'side'|'bottom';sideAvailable:boolean;
  checking:boolean;review:()=>void;retrySelected:()=>void;regenerate:()=>void;
  setLayout:(layout:'side'|'bottom')=>void;choose:(paragraph:ReadingParagraph)=>void;
  translate:()=>void;close:()=>void;loading:boolean;retry:()=>void;
  batchMode:boolean;batchScope:'page'|'paper';batchSelectedIds:string[];translatedParagraphIds:string[];batchRunning:boolean;
  queueItem?:TranslationQueueEntry;queueItems:Record<string,TranslationQueueEntry>;
  onToggleBatchMode:()=>void;onBatchScopeChange:(scope:'page'|'paper')=>void;
  onToggleBatchParagraph:(id:string,checked:boolean)=>void;onStartBatch:()=>void;onStartFull:()=>void;
  onSelection?:(selection:PdfSelection)=>void;
}) {
  const { t } = useUi()
  const translatedRef = useRef<HTMLDivElement>(null)
  const queueActive = isActiveTranslationQueueItem(queueItem)
  const queuePaused = queueItem?.job_status==='paused'&&!translation
  const index = selected ? paragraphs.findIndex(paragraph=>paragraph.id===selected.id) : -1
  const onPage = paragraphs.filter(paragraph=>paragraph.anchors.some(anchor=>anchor.page===page))
  const batchParagraphs = (batchScope==='page' ? onPage : paragraphs).filter(paragraph=>paragraph.kind==='prose')
  const selectedCount = batchSelectedIds.length
  const selectedAllCached = selectedCount>0&&batchSelectedIds.every(id=>translatedParagraphIds.includes(id))
  const captureTranslatedSelection = () => {
    if (!selected || !translation || !translatedRef.current) return
    const native = window.getSelection()
    if (!native || native.isCollapsed || !native.rangeCount || !translatedRef.current.contains(native.anchorNode) || !translatedRef.current.contains(native.focusNode)) return
    const text = native.toString().replace(/\s+/g, ' ').trim()
    if (!text) return
    const rects = Array.from(native.getRangeAt(0).getClientRects()).filter(rect => rect.width > 1 && rect.height > 1 && rect.bottom >= 0 && rect.top <= window.innerHeight)
    if (!rects.length) return
    const left = Math.min(...rects.map(rect => rect.left)), top = Math.min(...rects.map(rect => rect.top))
    const right = Math.max(...rects.map(rect => rect.right)), bottom = Math.max(...rects.map(rect => rect.bottom))
    const anchor = selected.anchors[0]
    onSelection?.({
      page: anchor?.page ?? page,
      text,
      sourceText: selected.source_text,
      origin: 'translation',
      bbox: anchor?.bbox ?? [0, 0, 1, 1],
      selectionRect: { left, top, width: right - left, height: bottom - top },
    })
  }
  const batchContent = <div className="batch-translation" data-testid="batch-translation-list">
    <div className="batch-translation-heading">
      <div><span className="batch-kicker">{t('batchTranslate')}</span><p>{t('queueSelectedHint')}</p></div>
      <button type="button" className="icon-btn" aria-label={t('batchClose')} title={t('batchClose')} onClick={onToggleBatchMode}><X size={15}/></button>
    </div>
    <div className="batch-translation-toolbar" role="group" aria-label={t('batchScope')}>
      <button type="button" className={batchScope==='page'?'active':''} aria-pressed={batchScope==='page'} onClick={()=>onBatchScopeChange('page')}>{t('batchCurrentPage')} <span>{String(page).padStart(2,'0')}</span></button>
      <button type="button" className={batchScope==='paper'?'active':''} aria-pressed={batchScope==='paper'} onClick={()=>onBatchScopeChange('paper')}>{t('batchFullPaper')}</button>
    </div>
    <div className="batch-translation-selection">
      <span>{t('batchSelected')} {selectedCount} {t('batchParagraphUnit')}</span>
      <button type="button" className="text-btn" disabled={!batchParagraphs.length} onClick={()=>batchParagraphs.forEach(paragraph=>onToggleBatchParagraph(paragraph.id,true))}>{t('batchSelectAll')}</button>
      {selectedCount>0&&<button type="button" className="text-btn"  onClick={()=>batchParagraphs.forEach(paragraph=>onToggleBatchParagraph(paragraph.id,false))}>{t('batchClear')}</button>}
    </div>
    <div className="batch-translation-items">
      {batchParagraphs.map((paragraph,index)=><div className={'batch-translation-item '+(batchSelectedIds.includes(paragraph.id)?'selected':'')} key={paragraph.id}>
        <input data-testid="batch-paragraph-checkbox" type="checkbox" checked={batchSelectedIds.includes(paragraph.id)}  aria-label={`${t('batchSelected')} ${index+1}`} onChange={event=>onToggleBatchParagraph(paragraph.id,event.target.checked)} />
        <span className="batch-item-index">{String(index+1).padStart(2,'0')}</span>
        <button type="button" className="batch-item-copy" onClick={()=>{choose(paragraph);onToggleBatchMode()}}><span>{paragraph.text}</span><small>{paragraph.section||t('paragraphView')} · {paragraph.anchors.map(anchor=>anchor.page).filter((value,i,array)=>array.indexOf(value)===i).join('–')}</small></button>
        <span className="batch-item-state">{translatedParagraphIds.includes(paragraph.id)?<span className="batch-item-done"><CheckCircle2 size={13}/>{t('batchAlreadyTranslated')}</span>:<span className={queueItems[paragraph.id]?.status==='failed'?'batch-item-failed':''}>{queueItemLabel(queueItems[paragraph.id],t)}</span>}</span>
      </div>)}
      {!batchParagraphs.length&&<p className="translation-model-hint">{t('translationNoParagraphs')}</p>}
    </div>
    <div className="batch-translation-footer">
      <span className="batch-translation-status">{t('queuePreservesCache')}</span>
      <button type="button" className="btn primary" disabled={batchRunning||(!available&&!selectedAllCached)||!selectedCount||!batchParagraphs.length} onClick={onStartBatch}><Languages size={14}/>{t('batchStart')}</button>
    </div>
    {!available&&<p className="translation-model-hint">{t('translationNeedsModel')}</p>}
  </div>
  return <aside className="translation-panel" aria-label={t('translationMargin')}>
    <header className="translation-panel-head">
      <div><BookOpen size={16}/><h2>{t('translationMargin')}</h2></div>
      <div className="translation-panel-head-actions">
        <button type="button" className={'batch-translation-trigger '+(batchMode?'active':'')} aria-pressed={batchMode} onClick={onToggleBatchMode}><Languages size={14}/>{batchMode?t('batchClose'):t('batchTranslate')}</button>
        <div className="translation-layout-toggle" role="group" aria-label={t('readMode')}>
          <button type="button" title={t(sideAvailable?'translationBeside':'translationNarrowHint')} aria-label={t('translationBeside')} disabled={!sideAvailable} aria-pressed={layout==='side'} onClick={()=>setLayout('side')}><Columns2 size={15}/></button>
          <button type="button" title={t('translationBelow')} aria-label={t('translationBelow')} aria-pressed={layout==='bottom'} onClick={()=>setLayout('bottom')}><ArrowDownToLine size={15}/></button>
        </div>
      </div>
    </header>
    <div className="translation-full-entry"><button type="button" disabled={batchRunning} title={t('queueFullHint')} onClick={onStartFull}><Languages size={13}/>{t('queueFull')}</button><span>{t('queueFullHint')}</span></div>
    <div className="translation-panel-scroll" key={batchMode?'batch':selected?.id??'translation-empty'}>
      {batchMode ? batchContent : selected ? <>
        <div className="translation-context"><span>{selected.section || t('paragraphView')} · {t('page')} {selected.anchors.map(a=>a.page).filter((v,i,a)=>a.indexOf(v)===i).join('–')}</span><div className="translation-context-actions">{selected.review_available&&<button className="translation-review" disabled={!available||pending||queueActive} onClick={review} title={t('paragraphReviewHint')}><ScanText size={14}/>{t('paragraphReview')}</button>}<button className="icon-btn" aria-label={t('collapseTranslation')} title={t('collapseTranslation')} onClick={close}><X size={15}/></button></div></div>
        {translation ? <><div ref={translatedRef} className="translation-selection-surface" onMouseUp={captureTranslatedSelection}><ScientificText text={translation.text} className="translated-text"/></div><div className="translation-result-footer"><p className="translation-footnote">{t('translationCached')}{translation.model && <span> · {translation.model}</span>}</p><button type="button" className="translation-regenerate" disabled={!available||pending||queueActive} onClick={regenerate}>{pending&&<LoaderCircle size={12} className="spin"/>}{t(pending?'translationRegenerating':'translationRegenerate')}</button></div></>
          : queueActive ? <div className="translation-loading" role="status"><LoaderCircle size={18} className="spin"/><p>{queueItemLabel(queueItem,t)}</p></div>
          : pending ? <div className="translation-loading" role="status"><LoaderCircle size={18} className="spin"/><p>{t(checking?'paragraphReviewWorking':'translationWorking')}</p></div>
          : <div className="translation-preview">{queuePaused&&<p className="translation-queue-reason" role="status">{t('queuePaused')}</p>}<ScientificText text={selected.text} className="translation-source"/><button className="translation-start" disabled={!available||(queuePaused&&batchRunning)} onClick={translate}><Languages size={15}/>{t('translate')}</button>{!available&&<p className="translation-model-hint">{t('translationNeedsModel')}</p>}</div>}
        {error && <div className="translation-error" role="alert"><p>{error}</p><button className="text-btn" disabled={!available||pending} onClick={retrySelected}>{t('retry')}</button></div>}
        {translation && <details className="translation-original"><summary>{t('translationSource')}</summary><ScientificText text={selected.text} className="translation-source"/></details>}
        {selected.review_uncertain&&<p className="translation-model-hint" role="status">{t('paragraphReviewUncertain')}</p>}
      </> : <>
        <div className="translation-intro"><span className="translation-intro-glyph">译</span><h3>{t('translationHoverHint')}</h3><p>{t('translationReadingHint')}</p></div>
        {loading ? <p className="translation-loading" role="status"><LoaderCircle size={16} className="spin"/>{t('loading')}</p> : error ? <div className="translation-error" role="alert"><p>{error}</p><button className="text-btn" onClick={retry}>{t('retry')}</button></div> : <div className="translation-paragraph-list"><h3>{t('translationCurrentPage')} <span>{String(page).padStart(2,'0')}</span></h3>{onPage.map((paragraph,i)=><button key={paragraph.id} onClick={()=>choose(paragraph)}><span className="paragraph-number">{String(i+1).padStart(2,'0')}</span><span className="paragraph-preview">{paragraph.text}</span><small className="paragraph-queue-state">{translatedParagraphIds.includes(paragraph.id)?t('queueDone'):queueItemLabel(queueItems[paragraph.id],t)}</small></button>)}{!onPage.length&&<p className="translation-model-hint">{t('translationNoParagraphs')}</p>}</div>}
        {!available&&<p className="translation-model-hint">{t('translationNeedsModel')}</p>}
      </>}
    </div>
    {selected&&!batchMode && <footer className="translation-nav"><button aria-label={t('translationPrevious')} disabled={index<=0} onClick={()=>choose(paragraphs[index-1])}><ChevronLeft size={14}/>{t('translationPrevious')}</button><span>{index+1} / {paragraphs.length}</span><button aria-label={t('translationNext')} disabled={index<0||index>=paragraphs.length-1} onClick={()=>choose(paragraphs[index+1])}>{t('translationNext')}<ChevronRight size={14}/></button></footer>}
  </aside>
}
