import { ArrowDownToLine, BookOpen, ChevronLeft, ChevronRight, Columns2, Languages, LoaderCircle, X } from 'lucide-react'
import type { ReadingParagraph, ReadingTranslation } from '../types'
import { useUi } from '../lib/i18n'
import { ScientificText } from './ScientificText'

export function TranslationPanel({paragraphs, selected, translation, pending, error, available, page, layout, sideAvailable, setLayout, choose, translate, close, loading, retry}:{
  paragraphs:ReadingParagraph[];selected:ReadingParagraph|null;translation?:ReadingTranslation;
  pending:boolean;error:string;available:boolean;page:number;layout:'side'|'bottom';sideAvailable:boolean;
  setLayout:(layout:'side'|'bottom')=>void;choose:(paragraph:ReadingParagraph)=>void;
  translate:()=>void;close:()=>void;loading:boolean;retry:()=>void;
}) {
  const { t } = useUi()
  const index = selected ? paragraphs.findIndex(paragraph=>paragraph.id===selected.id) : -1
  const onPage = paragraphs.filter(paragraph=>paragraph.anchors.some(anchor=>anchor.page===page))
  return <aside className="translation-panel" aria-label={t('translationMargin')}>
    <header className="translation-panel-head">
      <div><BookOpen size={16}/><h2>{t('translationMargin')}</h2></div>
      <div className="translation-layout-toggle" role="group" aria-label={t('readMode')}>
        <button type="button" title={t(sideAvailable?'translationBeside':'translationNarrowHint')} aria-label={t('translationBeside')} disabled={!sideAvailable} aria-pressed={layout==='side'} onClick={()=>setLayout('side')}><Columns2 size={15}/></button>
        <button type="button" title={t('translationBelow')} aria-label={t('translationBelow')} aria-pressed={layout==='bottom'} onClick={()=>setLayout('bottom')}><ArrowDownToLine size={15}/></button>
      </div>
    </header>
    <div className="translation-panel-scroll" key={selected?.id??page}>
      {selected ? <>
        <div className="translation-context"><span>{selected.section || t('paragraphView')} · {t('page')} {selected.anchors.map(a=>a.page).filter((v,i,a)=>a.indexOf(v)===i).join('–')}</span><button className="icon-btn" aria-label={t('collapseTranslation')} title={t('collapseTranslation')} onClick={close}><X size={15}/></button></div>
        {pending ? <div className="translation-loading" role="status"><LoaderCircle size={18} className="spin"/><p>{t('translationWorking')}</p></div>
          : translation ? <><ScientificText text={translation.text} className="translated-text"/><p className="translation-footnote">{t('translationCached')}{translation.model && <span> · {translation.model}</span>}</p></>
          : <div className="translation-preview"><ScientificText text={selected.text} className="translation-source"/><button className="translation-start" disabled={!available} onClick={translate}><Languages size={15}/>{t('translate')}</button>{!available&&<p className="translation-model-hint">{t('translationNeedsModel')}</p>}</div>}
        {error && <div className="translation-error" role="alert"><p>{error}</p><button className="text-btn" disabled={!available||pending} onClick={translate}>{t('retry')}</button></div>}
        {translation && <details className="translation-original"><summary>{t('translationSource')}</summary><ScientificText text={selected.text} className="translation-source"/></details>}
      </> : <>
        <div className="translation-intro"><span className="translation-intro-glyph">译</span><h3>{t('translationHoverHint')}</h3><p>{t('translationReadingHint')}</p></div>
        {loading ? <p className="translation-loading" role="status"><LoaderCircle size={16} className="spin"/>{t('loading')}</p> : error ? <div className="translation-error" role="alert"><p>{error}</p><button className="text-btn" onClick={retry}>{t('retry')}</button></div> : <div className="translation-paragraph-list"><h3>{t('translationCurrentPage')} <span>{String(page).padStart(2,'0')}</span></h3>{onPage.map((paragraph,i)=><button key={paragraph.id} onClick={()=>choose(paragraph)}><span className="paragraph-number">{String(i+1).padStart(2,'0')}</span><span>{paragraph.text}</span></button>)}{!onPage.length&&<p className="translation-model-hint">{t('translationNoParagraphs')}</p>}</div>}
        {!available&&<p className="translation-model-hint">{t('translationNeedsModel')}</p>}
      </>}
    </div>
    {selected && <footer className="translation-nav"><button aria-label={t('translationPrevious')} disabled={index<=0} onClick={()=>choose(paragraphs[index-1])}><ChevronLeft size={14}/>{t('translationPrevious')}</button><span>{index+1} / {paragraphs.length}</span><button aria-label={t('translationNext')} disabled={index<0||index>=paragraphs.length-1} onClick={()=>choose(paragraphs[index+1])}>{t('translationNext')}<ChevronRight size={14}/></button></footer>}
  </aside>
}
