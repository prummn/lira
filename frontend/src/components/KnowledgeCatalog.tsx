import { Search, SlidersHorizontal } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { KnowledgeEntityIndexItem, KnowledgeEntityType } from '../types'
import { useUi, type LocaleKey } from '../lib/i18n'
import { entityTypes } from '../lib/knowledgeLabels'

type Props = {
  entities: KnowledgeEntityIndexItem[]
  onSelect: (entity: KnowledgeEntityIndexItem) => void
}

const filters: Array<KnowledgeEntityType | 'all'> = ['all', ...entityTypes]

export function KnowledgeCatalog({ entities, onSelect }: Props) {
  const { t } = useUi()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<KnowledgeEntityType | 'all'>('all')
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    return entities.filter(entity => {
      if (filter !== 'all' && entity.entity_type !== filter) return false
      if (!normalized) return true
      return [entity.name, ...entity.aliases, entity.description ?? '', entity.context_summary ?? ''].join(' ').toLocaleLowerCase().includes(normalized)
    })
  }, [entities, filter, query])
  const grouped = useMemo(() => filters.slice(1).reduce<Record<string, KnowledgeEntityIndexItem[]>>((result, type) => {
    result[type] = filtered.filter(entity => entity.entity_type === type)
    return result
  }, {}), [filtered])

  return <section className="knowledge-catalog" aria-label={t('knowledgeCatalogLabel')}>
    <header className="knowledge-catalog-header">
      <div><span className="eyebrow">FIELD INDEX</span><h2>{t('catalog')}</h2><p>{t('knowledgeCatalogHint')}</p></div>
      <span className="knowledge-catalog-count">{filtered.length} {t('knowledgeEntities')}</span>
    </header>
    <div className="knowledge-catalog-tools">
      <label className="knowledge-search"><Search size={15}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder={t('knowledgeCatalogSearch')} aria-label={t('knowledgeCatalogSearch')}/></label>
      <div className="knowledge-filter" role="group" aria-label={t('knowledgeCatalogFilter')}><SlidersHorizontal size={14}/>{filters.map(type => <button key={type} className={filter === type ? 'active' : ''} onClick={() => setFilter(type)}>{type === 'all' ? t('all') : t(`knowledgeGroup_${type}` as LocaleKey)}</button>)}</div>
    </div>
    <div className="knowledge-catalog-index">
      {filters.slice(1).map(type => {
        const items = grouped[type] ?? []
        if (!items.length) return null
        return <section className="knowledge-catalog-group" key={type}><header><span>{t(`knowledgeGroup_${type}` as LocaleKey)}</span><small>{items.length}</small></header><div>{items.map(entity => <button className="knowledge-catalog-row" key={entity.id} aria-label={entity.name} onClick={() => onSelect(entity)}><span className={`knowledge-entity-mark mark-${entity.entity_type}`}/><span className="knowledge-catalog-row-copy"><span className="catalog-name-line"><strong>{entity.name}</strong>{!!entity.contextual_paper_count&&<span className="catalog-context-badge">{t(entity.context_only?'kContextBadge':'kContextIncludes')}</span>}</span>{entity.aliases.length > 0 && <small>{entity.aliases.join(' · ')}</small>}<em className={entity.context_only?'catalog-context-summary':undefined}>{entity.context_only?(entity.context_summary||t('kContextExample')):(entity.description||t('entityNoDescription'))}</em>{entity.paper_count!==undefined&&<small className="catalog-record-counts">{entity.paper_count} {t('dossierPapers')} · {entity.relation_count??0} {t('dossierRelations')}</small>}</span><span className="knowledge-catalog-row-arrow">↗</span></button>)}</div></section>
      })}
      {!filtered.length && <div className="knowledge-catalog-empty"><strong>{t('knowledgeCatalogNoResults')}</strong><p>{t('knowledgeCatalogNoResultsHint')}</p></div>}
    </div>
  </section>
}
