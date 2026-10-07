import { useMemo, useState } from 'react'
import { Search, UserRound } from 'lucide-react'
import { useUi } from '../lib/i18n'
import type { Workspace } from '../lib/useWorkspace'
import { Empty, PaperLink } from '../components/Shared'

export function ResearchersPage({workspace,openPaper}:{workspace:Workspace;openPaper:(id:string)=>void}) {
  const {t} = useUi()
  const [query,setQuery]=useState('')
  const [selection,setSelection]=useState('')
  const names=useMemo(()=>[...new Set(workspace.papers.flatMap(p=>p.authors))].sort(),[workspace.papers])
  const filtered=names.filter(n=>n.toLowerCase().includes(query.toLowerCase()))
  const selected=names.includes(selection)?selection:filtered[0]
  const papers=workspace.papers.filter(p=>p.authors.includes(selected))
  const collectionIds=[...new Set(papers.flatMap(p=>p.collection_ids))]
  const collaborators=[...new Set(papers.flatMap(p=>p.authors))].filter(n=>n!==selected)
  return <div><section className="page-heading"><div><div className="eyebrow">PEOPLE & RESEARCH</div><h1>{t('authorsTitle')}</h1><p>{t('authorsSubtitle')}</p></div></section><div className="researcher-layout"><section className="researcher-list"><label className="search-field"><Search size={15}/><input aria-label={t('authorsSearch')} placeholder={t('authorsSearch')} value={query} onChange={e=>setQuery(e.target.value)}/></label>{filtered.map(name=><button key={name} className={'researcher-row '+(selected===name?'active':'')} onClick={()=>setSelection(name)}><span className="avatar">{name.split(' ').map(p=>p[0]).slice(0,2).join('')}</span><strong>{name}</strong><small>{workspace.papers.filter(p=>p.authors.includes(name)).length}</small></button>)}{!filtered.length&&<Empty title={t('authorsEmpty')}/>}</section>{selected&&<section className="researcher-detail"><div className="researcher-detail-top"><span className="avatar avatar-lg"><UserRound size={28} strokeWidth={1.3}/></span><div><h2>{selected}</h2><p>{t('institutionUnknown')}</p>{papers.every(p=>p.is_demo)&&<span className="demo-badge">{t('demo')}</span>}</div></div><p className="capability-notice">{t('authorSource')}</p><div className="researcher-stats"><div><strong>{papers.length}</strong><span>{t('paperCount')}</span></div><div><strong>{collectionIds.length}</strong><span>{t('relatedCollections')}</span></div></div><h3>{t('representativePapers')}</h3>{papers.map(p=><PaperLink key={p.id} title={p.title} onClick={()=>openPaper(p.id)}/>)}<h3>{t('collaborators')}</h3><div className="collaborator-list">{collaborators.map(n=><button key={n} onClick={()=>setSelection(n)}>{n}<small>{papers.filter(p=>p.authors.includes(n)).length}</small></button>)}</div></section>}</div></div>
}
