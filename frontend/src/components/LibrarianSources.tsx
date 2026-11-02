import { ArrowUpRight, ChevronDown } from 'lucide-react'
import type { LibraryAnswer, LibraryCitation } from '../types'
import { useUi } from '../lib/i18n'

/** List the works actually cited, without treating retrieved candidates as references. */
export function LibrarianSources({ answer, onCitation }: { answer: LibraryAnswer; onCitation: (citation: LibraryCitation) => void }) {
  const { t } = useUi()
  const groups = new Map<string, { title: string; citations: LibraryCitation[]; numbers: Set<number> }>()
  const numbers = new Map<string, number>()
  for (const citation of answer.items?.length ? answer.items.flatMap(item => item.citations) : answer.citations ?? []) {
    const key = citation.source_type === 'paper' && citation.page != null ? `${citation.paper_id}:page:${citation.page}` : `${citation.source_type}:${citation.id}`
    if (!numbers.has(key)) numbers.set(key, numbers.size + 1)
    const group = groups.get(citation.paper_id) ?? { title: citation.title, citations: [], numbers: new Set<number>() }
    if (!group.citations.some(source => source.id === citation.id)) group.citations.push(citation)
    group.numbers.add(numbers.get(key)!)
    groups.set(citation.paper_id, group)
  }
  if (!groups.size) return null
  return <details className="librarian-sources"><summary>{t('librarianReferences')} <span>{groups.size}</span><ChevronDown size={13}/></summary>
    <ol>{[...groups].map(([id, group]) => {
      const original = group.citations.find(source => source.source_type === 'paper') ?? group.citations[0]
      const pages = [...new Set(group.citations.flatMap(source => source.page == null ? [] : [source.page]))].sort((a,b) => a-b)
      const types = [...new Set(group.citations.map(source=>t(source.source_type==='paper'?'original':source.source_type==='user'?'claimUser':source.source_type==='ai'?'librarianAiSource':'claimMetadata')))]
      return <li className="librarian-source-paper" key={id}><span className="librarian-source-numbers">{[...group.numbers].map(number => `[${number}]`).join(' ')}</span>
        <button type="button" onClick={() => onCitation(original)}><strong>{group.title}</strong>
          <small>{types.join(' / ')}{pages.length>0&&` · ${t('page')} ${pages.join(', ')}`}</small><ArrowUpRight size={14}/></button></li>
    })}</ol>
  </details>
}

export function LibrarianCoverageNote({ answer }: { answer: LibraryAnswer }) {
  const { t } = useUi()
  const gaps=[]
  if (answer.coverage?.catalog_truncated === true) gaps.push(t('librarianCatalogPartial')
    .replace('{covered}', String(answer.coverage.catalog_papers ?? '—')).replace('{total}', String(answer.coverage.scope_papers ?? '—')))
  if (answer.coverage?.comparison_complete === false) gaps.push(t('librarianComparisonPartial'))
  return gaps.length ? <p className="librarian-coverage-note">{gaps.join(' ')}</p> : null
}
