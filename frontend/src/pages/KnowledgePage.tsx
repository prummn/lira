import { useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, Clock3, Download, GitBranch, Link2, Network, SlidersHorizontal } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import { useUi } from '../lib/i18n'
import type { Workspace } from '../lib/useWorkspace'
import type { Graph, PaperDetail } from '../types'
import { Empty, ErrorBanner, exportJson, Loading, PaperLink } from '../components/Shared'

type FieldTab = 'timeline'|'graph'|'compare'|'concepts'
const tabs = [{id:'timeline',icon:Clock3},{id:'graph',icon:GitBranch},{id:'compare',icon:SlidersHorizontal},{id:'concepts',icon:Network}] as const
export function KnowledgePage({workspace,collectionId,setCollectionId,openPaper}:{workspace:Workspace;collectionId:string;setCollectionId:(id:string)=>void;openPaper:(id:string)=>void}) {
  const {t} = useUi()
  const effectiveId = collectionId || workspace.collections[0]?.id || ''
  const papers = workspace.papers.filter(p=>p.collection_ids.includes(effectiveId))
  const idKey = papers.map(p=>p.id).join(',')
  const [tab,setTab] = useState<FieldTab>('timeline')
  const [details,setDetails] = useState<PaperDetail[]>([])
  const [graph,setGraph] = useState<Graph>({nodes:[],edges:[]})
  const [loading,setLoading] = useState(true)
  const [error,setError] = useState('')
  const [selection,setSelection] = useState<string[]>([])
  const [revision,setRevision] = useState(0)
  useEffect(()=>{
    let active=true;setLoading(true);setError('');setDetails([]);setGraph({nodes:[],edges:[]});setSelection(idKey.split(',').filter(Boolean).slice(0,3))
    Promise.all([api.graph(effectiveId),Promise.all(idKey.split(',').filter(Boolean).map(id=>api.paper(id)))]).then(([g,d])=>{if(active){setGraph(g);setDetails(d)}}).catch(e=>{if(active)setError(errorMessage(e))}).finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[effectiveId,idKey,revision])
  const collection = workspace.collections.find(c=>c.id===effectiveId)
  const grouped = useMemo(()=>[...details].sort((a,b)=>(a.year??0)-(b.year??0)),[details])
  const concepts = useMemo(()=>[...new Set(details.flatMap(p=>p.analysis?.concepts??[]))].sort(),[details])
  const selected=details.filter(p=>selection.includes(p.id))
  const verifiedEdges=graph.edges.filter(e=>e.relation_source==='explicit'||e.relation_source==='metadata')
  return <div className="knowledge-page"><section className="page-heading"><div><div className="eyebrow">FIELD KNOWLEDGE</div><h1>{collection?.name??t('knowledge')}</h1><p>{t('fieldSubtitle')}</p></div><select className="collection-picker" aria-label={t('selectCollection')} value={effectiveId} onChange={e=>setCollectionId(e.target.value)}>{workspace.collections.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></section>
    <div className="field-toolbar"><div className="field-tabs">{tabs.map(item=><button className={tab===item.id?'active':''} key={item.id} onClick={()=>setTab(item.id)}><item.icon size={15}/>{t(item.id)}</button>)}</div><button className="btn secondary" disabled={loading||!details.length} onClick={()=>exportJson('collection-'+effectiveId+'.json',{collection,papers:details,graph})}><Download size={14}/>{t('export')}</button></div>
    {error&&<ErrorBanner error={error} retry={()=>setRevision(x=>x+1)}/>}
    {loading?<Loading text={t('comparisonLoading')}/>:!details.length?<Empty title={t('fieldEmpty')} text={t('fieldEmptyHint')}/>:<>
      {tab==='timeline'&&<section className="timeline-view"><p className="capability-notice">{verifiedEdges.length?t('relationExplicit')+' · '+verifiedEdges.length:t('noEvolution')}</p>{[...new Set(grouped.map(p=>p.year))].map(year=><div className="timeline-year" key={year??'unknown'}><div className="year-label">{year??t('unknown')}</div><div className="timeline-papers">{grouped.filter(p=>p.year===year).map(p=><article className="timeline-item" key={p.id}><span className="timeline-node"/><div className="timeline-card"><div className="timeline-meta"><span>{p.venue??t('unknown')}</span>{p.is_demo&&<span className="demo-badge">{t('demo')}</span>}</div><PaperLink title={p.title} onClick={()=>openPaper(p.id)}/><small>{t('techChange')} · {p.analysis?.mode==='extractive'?t('extractive'):p.analysis?.provider}</small><p>{p.analysis?.method||p.abstract||t('unreported')}</p><div className="timeline-relations">{graph.edges.filter(e=>e.source===p.id).map(edge=><span key={edge.id} className="relation-chip">{edge.relation_source==='demo'?t('relationDemo'):edge.relation_source==='llm_inferred'?t('relationInferred'):t('relationExplicit')} · {edge.relation} → {papers.find(x=>x.id===edge.target)?.title.slice(0,45)}</span>)}</div><footer>{p.authors.slice(0,3).join(' · ')}<button className="text-btn" onClick={()=>openPaper(p.id)}><Link2 size={12}/>{t('viewSource')}</button></footer></div></article>)}</div></div>)}</section>}
      {tab==='graph'&&<section className="graph-view"><div className="graph-caption"><h2>{t('graph')}</h2><span>{graph.nodes.length} {t('paperCount')} · {graph.edges.length} edges</span></div>{!graph.edges.length&&<p className="capability-notice">{t('noEdges')} · {t('noEdgesHint')}</p>}<CitationGraph graph={graph} openPaper={openPaper}/><div className="graph-relations">{graph.edges.map(edge=><div key={edge.id}><span className={'source-badge source-'+edge.relation_source}>{t(edge.relation_source==='demo'?'relationDemo':edge.relation_source==='llm_inferred'?'relationInferred':'relationExplicit')}</span><strong>{edge.relation}</strong><small>{papers.find(p=>p.id===edge.source)?.title} → {papers.find(p=>p.id===edge.target)?.title}</small></div>)}</div></section>}
      {tab==='compare'&&<section className="comparison-view"><p className="capability-notice">{t('compareHint')}</p><div className="comparison-selector">{details.map(p=><label key={p.id}><input type="checkbox" checked={selection.includes(p.id)} disabled={!selection.includes(p.id)&&selection.length>=4} onChange={e=>setSelection(e.target.checked?[...selection,p.id]:selection.filter(id=>id!==p.id))}/>{p.title}</label>)}</div>{selected.length>=2&&<div className="comparison-scroll"><table className="comparison-table"><thead><tr><th>{t('dimension')}</th>{selected.map(p=><th key={p.id}><button onClick={()=>openPaper(p.id)}>{p.title}<ArrowUpRight size={12}/></button></th>)}</tr></thead><tbody>{(['problem','method','findings','limitations'] as const).map(key=><tr key={key}><th>{t(key==='findings'?'results':key)}</th>{selected.map(p=><td key={p.id}><p>{p.analysis?.[key]||t('unreported')}</p>{p.analysis?.[key]&&<button className="text-btn" onClick={()=>openPaper(p.id)}><Link2 size={11}/>{t('viewSource')}</button>}</td>)}</tr>)}</tbody></table></div>}</section>}
      {tab==='concepts'&&<section className="concept-view"><p className="capability-notice">{t('conceptHint')}</p><div className="concept-index">{concepts.map(concept=><article key={concept}><h3>{concept}</h3>{details.filter(p=>p.analysis?.concepts.includes(concept)).map(p=><PaperLink key={p.id} title={p.title} onClick={()=>openPaper(p.id)}/>)}</article>)}</div>{!concepts.length&&<Empty title={t('unreported')}/>}</section>}
    </>}
  </div>
}
function CitationGraph({graph,openPaper}:{graph:Graph;openPaper:(id:string)=>void}) {
  const count=graph.nodes.length
  const positions=new Map(graph.nodes.map((node,index)=>{const angle=index*2*Math.PI/Math.max(count,1)-Math.PI/2;return[node.id,{x:440+Math.cos(angle)*280,y:260+Math.sin(angle)*190}]}))
  return <svg className="citation-svg" viewBox="0 0 880 520" role="img" aria-label="Citation graph"><defs><marker id="edge-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>{graph.edges.map(edge=>{const a=positions.get(edge.source);const b=positions.get(edge.target);if(!a||!b)return null;const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1;return <line key={edge.id} x1={a.x+dx/len*24} y1={a.y+dy/len*24} x2={b.x-dx/len*24} y2={b.y-dy/len*24} className={'citation-edge '+(edge.relation_source==='llm_inferred'||edge.relation_source==='demo'?'inferred':'')} markerEnd="url(#edge-arrow)"><title>{edge.relation} · {edge.relation_source}</title></line>})}{graph.nodes.map(node=>{const p=positions.get(node.id)!;return <g key={node.id} transform={'translate('+p.x+','+p.y+')'} className="citation-node" tabIndex={0} role="button" onClick={()=>openPaper(node.id)} onKeyDown={e=>{if(e.key==='Enter')openPaper(node.id)}} aria-label={node.label}><title>{node.label}</title><circle r={23}/><text textAnchor="middle" y={4} className="node-year">{node.year??'—'}</text><text textAnchor="middle" y={41} className="node-label">{node.label.slice(0,26)}{node.label.length>26?'…':''}</text></g>})}</svg>
}
