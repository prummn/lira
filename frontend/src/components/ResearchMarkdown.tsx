import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { findingReferences } from '../lib/findingReferences'
import 'katex/dist/katex.min.css'
import './research-markdown.css'

/** Model text is Markdown, never executable HTML or remote image markup. */
export function ResearchMarkdown({ text, className = '', onSource, sourceLabels }: { text: string; className?: string; onSource?:(id:string)=>void; sourceLabels?:Record<string,string> }) {
  return <div className={`research-markdown ${className}`}><Markdown
    skipHtml
    remarkPlugins={[remarkGfm, remarkMath, ...(sourceLabels?[findingReferences(sourceLabels)]:[])]}
    rehypePlugins={[[rehypeKatex, { trust: false, strict: 'ignore', maxExpand: 500, maxSize: 12 }]]}
    components={{
      a: ({ children, href }) => onSource && href?.startsWith('#source-')
        ? <button className="essay-citation" data-source-id={href.slice(8)} aria-label={`查看原文 ${String(children)}`} onClick={()=>onSource(href.slice(8))}>{children}</button>
        : <a href={href} target="_blank" rel="noreferrer">{children}</a>,
      img: ({ alt }) => <span>{alt}</span>,
      table: ({ children }) => <div className="research-table-scroll"><table>{children}</table></div>,
    }}
  >{text}</Markdown></div>
}
