import { useMemo } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'

/** Only explicit math delimiters are interpreted. All surrounding text remains text. */
export function ScientificText({ text, className = '' }: { text:string;className?:string }) {
  const content = useMemo(() => {
    const math = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|(?<![\\$])\$([^$\n]+?)\$(?!\$)/g
    const parts = []
    let offset = 0
    for (const match of text.matchAll(math)) {
      const start = match.index!
      if (start > offset) parts.push(text.slice(offset, start))
      const expression = match[1] ?? match[2] ?? match[3] ?? match[4]
      const display = match[1] !== undefined || match[2] !== undefined
      try {
        if (expression.length > 6000) throw new Error('Math too long')
        const html = katex.renderToString(expression, { displayMode:display, throwOnError:true,
          trust:false, strict:'ignore', maxExpand:500, maxSize:12, output:'htmlAndMathml' })
        parts.push(<span key={start} className={display?'scientific-display-math':'scientific-inline-math'} dangerouslySetInnerHTML={{__html:html}} />)
      } catch {
        parts.push(<code key={start} className="scientific-math-fallback">{match[0]}</code>)
      }
      offset = start + match[0].length
    }
    if (offset < text.length) parts.push(text.slice(offset))
    return parts
  }, [text])
  return <div className={`scientific-text ${className}`}>{content}</div>
}
