import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUpRight, Clock3, Download, GitBranch, Inbox, Link2, Sparkles, SlidersHorizontal, Table2 } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import { useUi, type LocaleKey } from '../lib/i18n'
import type { Workspace } from '../lib/useWorkspace'
import type { Graph, KnowledgeAudit, KnowledgeCandidate, KnowledgeEntityIndexItem, KnowledgeRelation, PaperDetail } from '../types'
import { Empty, ErrorBanner, exportJson, Loading, PaperLink } from '../components/Shared'
import { KnowledgeCatalog } from '../components/KnowledgeCatalog'
import { KnowledgeEntityDossier } from '../components/KnowledgeEntityDossier'
import { KnowledgeReview } from '../components/KnowledgeReview'
import { KnowledgeEvolutionMap } from '../components/KnowledgeEvolutionMap'
import { KnowledgeMaintenance } from '../components/KnowledgeMaintenance'
import type { PdfLocator } from '../components/PdfViewer'

type FieldTab = 'timeline'|'graph'|'evolution'|'compare'|'concepts'|'catalog'|'inbox'|'maintenance'
const tabs = [{id:'timeline',icon:Clock3},{id:'graph',icon:GitBranch},{id:'evolution',icon:GitBranch},{id:'compare',icon:SlidersHorizontal},{id:'catalog',icon:Table2},{id:'inbox',icon:Inbox},{id:'maintenance',icon:Sparkles}] as const
export function KnowledgePage({workspace,collectionId,setCollectionId,openPaper}:{workspace:Workspace;collectionId:string;setCollectionId:(id:string)=>void;openPaper:(id:string,locator?:PdfLocator)=>void}) {
  const {t} = useUi()
  // The knowledge field defaults to the whole library so cross-paper relations
  // remain visible. A collection is an optional lens, not an implicit scope.
  const effectiveId = collectionId
  const papers = effectiveId ? workspace.papers.filter(p=>p.collection_ids.includes(effectiveId)) : workspace.papers
  const idKey = papers.map(p=>p.id).join(',')
  const [tab,setTab] = useState<FieldTab>('timeline')
  const [details,setDetails] = useState<PaperDetail[]>([])
  const [graph,setGraph] = useState<Graph>({nodes:[],edges:[]})
  const [loading,setLoading] = useState(true)
  const [error,setError] = useState('')
  const [selection,setSelection] = useState<string[]>([])
  const [entities,setEntities] = useState<KnowledgeEntityIndexItem[]>([])
  const [knowledgeRelations,setKnowledgeRelations] = useState<KnowledgeRelation[]>([])
  const [overviewCandidates,setOverviewCandidates] = useState<KnowledgeCandidate[]>([])
  const [audits,setAudits] = useState<KnowledgeAudit[]>([])
  const [selectedEntity,setSelectedEntity] = useState<KnowledgeEntityIndexItem | null>(null)
  const [pendingRelation,setPendingRelation] = useState<KnowledgeRelation | null>(null)
  const [revision,setRevision] = useState(0)
  const refreshGeneration=useRef(0)
  const scopeKey=effectiveId+'|'+idKey
  const activeScope=useRef(scopeKey);activeScope.current=scopeKey
  useEffect(()=>()=>{refreshGeneration.current++},[])
  useEffect(()=>{
    let active=true;setLoading(true);setError('');setDetails([]);setGraph({nodes:[],edges:[]});setSelection(idKey.split(',').filter(Boolean).slice(0,3))
    setSelectedEntity(null);setPendingRelation(null);setOverviewCandidates([]);setAudits([])
    const paperIds=idKey.split(',').filter(Boolean)
    // The map can render as soon as its source records arrive. Auditing is a
    // read-only enrichment and must never hold the field view behind dozens of
    // extra requests.
    Promise.all([api.graph(effectiveId),api.knowledgeEntities(undefined,effectiveId?paperIds:undefined),api.knowledgeOverview(paperIds)]).then(([g,e,o])=>{if(active){setGraph(g);setEntities(e.items);setKnowledgeRelations(o.relations);setOverviewCandidates(o.candidates)}}).catch(e=>{if(active)setError(errorMessage(e))}).finally(()=>{if(active)setLoading(false)})
    const loadScoped=async<T,>(read:(id:string)=>Promise<T>)=>{
      const pending=[...paperIds]
      const loaded=new Map<string,T>()
      await Promise.all(Array.from({length:Math.min(3,pending.length)},async()=>{
        while(active&&pending.length){const id=pending.shift()!;const value=await read(id);if(active)loaded.set(id,value)}
      }))
      return paperIds.flatMap(id=>loaded.has(id)?[loaded.get(id)!]:[])
    }
    void loadScoped(api.paper).then(d=>{if(active)setDetails(d)}).catch(e=>{if(active)setError(errorMessage(e))})
    void loadScoped(api.paperKnowledgeAudit).then(a=>{if(active)setAudits(a)}).catch(()=>{if(active)setAudits([])})
    return()=>{active=false}
  },[effectiveId,idKey,revision])
  const selectEntity=(id:string,name:string)=>{setPendingRelation(null);setSelectedEntity({id,name,entity_type:'concept',normalized_name:name.toLowerCase(),aliases:[],description:null,status:'active'})}
  const refreshKnowledge=async()=>{
    const generation=++refreshGeneration.current
    const scope=scopeKey
    try {
      const [g,e,o]=await Promise.all([api.graph(effectiveId),api.knowledgeEntities(undefined,effectiveId?idKey.split(',').filter(Boolean):undefined),api.knowledgeOverview(idKey.split(',').filter(Boolean))])
      if(generation!==refreshGeneration.current||scope!==activeScope.current)return
      setGraph(g);setEntities(e.items);setKnowledgeRelations(o.relations);setOverviewCandidates(o.candidates)
    } catch(e){if(generation===refreshGeneration.current&&scope===activeScope.current)setError(errorMessage(e))}
  }
  const collection = workspace.collections.find(c=>c.id===effectiveId)
  const grouped = useMemo(()=>[...details].sort((a,b)=>(a.year??0)-(b.year??0)),[details])
  const concepts = useMemo(()=>[...new Set(details.flatMap(p=>p.analysis?.concepts??[]))].sort(),[details])
  const selected=details.filter(p=>selection.includes(p.id))
  const detailsReady=details.length>0
  const mapCandidates=overviewCandidates.length>0?overviewCandidates:details.flatMap(paper=>paper.knowledge_candidates??[])
  const verifiedEdges=graph.edges.filter(e=>e.relation_source==='explicit'||e.relation_source==='metadata')
  return <div className="knowledge-page"><section className="page-heading"><div><div className="eyebrow">FIELD KNOWLEDGE</div><h1>{collection?.name??t('knowledge')}</h1><p>{t('fieldSubtitle')}</p></div><select className="collection-picker" aria-label={t('selectCollection')} value={effectiveId} onChange={e=>setCollectionId(e.target.value)}><option value="">{t('allPapers')}</option>{workspace.collections.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></section>
    <div className="field-toolbar"><div className="field-tabs">{tabs.map(item=><button className={tab===item.id?'active':''} key={item.id} onClick={()=>setTab(item.id)}><item.icon size={15}/>{t(item.id)}</button>)}</div><button className="btn secondary" disabled={loading||!details.length} onClick={()=>exportJson('collection-'+effectiveId+'.json',{collection,papers:details,graph})}><Download size={14}/>{t('export')}</button></div>
    {error&&<ErrorBanner error={error} retry={()=>setRevision(x=>x+1)}/>}
    {loading?<Loading text={t('comparisonLoading')}/>:!papers.length?<Empty title={t('fieldEmpty')} text={t('fieldEmptyHint')}/>:<>
      {tab==='timeline'&&(detailsReady?<section className="timeline-view"><p className="capability-notice">{verifiedEdges.length?t('relationExplicit')+' · '+verifiedEdges.length:t('noEvolution')}</p>{[...new Set(grouped.map(p=>p.year))].map(year=><div className="timeline-year" key={year??'unknown'}><div className="year-label">{year??t('knowledgeYearPending')}</div><div className="timeline-papers">{grouped.filter(p=>p.year===year).map(p=><article className="timeline-item" key={p.id}><span className="timeline-node"/><div className="timeline-card"><div className="timeline-meta"><span>{p.venue?.trim()||(p.arxiv_id||p.source_url?.includes('arxiv.org')?t('knowledgePreprint'):t('knowledgeVenuePending'))}</span>{p.is_demo&&<span className="demo-badge">{t('demo')}</span>}</div><PaperLink title={p.title} onClick={()=>openPaper(p.id)}/><small>{p.analysis?t('techChange')+' · '+(p.analysis.mode==='extractive'?t('extractive'):p.analysis.provider??t('knowledgeAnalysisReady')):t(p.analysis_status==='failed'?'comparisonAnalysisFailed':'comparisonAnalysisPending')}</small><p>{p.analysis?.method||p.abstract||t('unreported')}</p><div className="timeline-relations">{graph.edges.filter(e=>e.source===p.id).map(edge=><span key={edge.id} className="relation-chip">{edge.relation_source==='demo'?t('relationDemo'):edge.relation_source==='llm_inferred'?t('relationInferred'):t('relationExplicit')} · {edge.relation} → {papers.find(x=>x.id===edge.target)?.title.slice(0,45)}</span>)}</div><footer>{p.authors.slice(0,3).join(' · ')}<button className="text-btn" onClick={()=>openPaper(p.id)}><Link2 size={12}/>{t('viewSource')}</button></footer></div></article>)}</div></div>)}</section>:<Loading text={t('comparisonLoading')}/>)}
      {tab==='graph'&&<section className="graph-view"><div className="graph-caption"><h2>{t('graph')}</h2><span>{graph.nodes.length} {t('paperCount')} · {graph.edges.length} edges</span></div>{!graph.edges.length&&<p className="capability-notice">{t('noEdges')} · {t('noEdgesHint')}</p>}<CitationGraph graph={graph} openPaper={openPaper}/><details className="graph-relation-details"><summary>{t('graphRelationDetails')}<span>{graph.edges.length}</span></summary><div className="graph-relations">{graph.edges.map(edge=><div key={edge.id}><span className={'source-badge source-'+edge.relation_source}>{t(edge.relation_source==='demo'?'relationDemo':edge.relation_source==='llm_inferred'?'relationInferred':'relationExplicit')}</span><strong>{edge.relation}</strong><small>{papers.find(p=>p.id===edge.source)?.title} → {papers.find(p=>p.id===edge.target)?.title}</small></div>)}</div></details></section>}
      {tab==='evolution'&&<KnowledgeEvolutionMap papers={papers} candidates={mapCandidates} relations={knowledgeRelations} audits={audits} graph={graph} onOpenEvidence={(paperId,page,_chunkId,quote)=>openPaper(paperId,page?{page,source_text:quote}:undefined)} onSelectEntity={(entityId,name)=>{setPendingRelation(null);setSelectedEntity({id:entityId,entity_type:'concept',name,normalized_name:name.toLocaleLowerCase(),aliases:[],description:null,status:'active'})}} onSelectPending={relation=>{setSelectedEntity(null);setPendingRelation(relation)}}/>}
      {tab==='compare'&&<section className="comparison-view"><p className="capability-notice">{t('compareHint')}</p><div className="comparison-selector">{details.map(p=><label key={p.id}><input type="checkbox" checked={selection.includes(p.id)} disabled={!selection.includes(p.id)&&selection.length>=4} onChange={e=>setSelection(e.target.checked?[...selection,p.id]:selection.filter(id=>id!==p.id))}/>{p.title}</label>)}</div>{selected.length>=2&&<div className="comparison-scroll"><table className="comparison-table" style={{minWidth:140+selected.length*340}}><thead><tr><th>{t('dimension')}</th>{selected.map(p=><th key={p.id}><button onClick={()=>openPaper(p.id)}>{p.title}<ArrowUpRight size={12}/></button></th>)}</tr></thead><tbody>{(['problem','method','findings','limitations'] as const).map(key=><tr key={key}><th>{t(key==='findings'?'results':key)}</th>{selected.map(p=><td key={p.id}><p className={p.analysis?.[key]?'':'comparison-missing'}>{p.analysis?.[key]||t(p.analysis?(p.analysis.mode==='extractive'?'comparisonExtractiveMissing':'comparisonFieldMissing'):p.analysis_status==='failed'||p.intelligence_status==='failed'?'comparisonAnalysisFailed':['running','queued'].includes(p.analysis_status)||['running','queued'].includes(p.intelligence_status??'')?'comparisonAnalysisRunning':'comparisonAnalysisPending')}</p><button className="text-btn" onClick={()=>openPaper(p.id)}><Link2 size={13}/>{t(p.analysis?.[key]?'viewSource':'knowledgeOpenPaper')}</button></td>)}</tr>)}</tbody></table></div>}</section>}
      {tab==='concepts'&&<section className="concept-view"><p className="capability-notice">{t('conceptHint')}</p><div className="concept-index">{concepts.map(concept=><article key={concept}><h3>{concept}</h3>{details.filter(p=>p.analysis?.concepts.includes(concept)).map(p=><PaperLink key={p.id} title={p.title} onClick={()=>openPaper(p.id)}/>)}</article>)}</div>{!concepts.length&&<Empty title={t('unreported')}/>}</section>}
      {tab==='catalog'&&<KnowledgeCatalog entities={entities} onSelect={entity=>{setPendingRelation(null);setSelectedEntity(entity)}}/>}
      {tab==='inbox'&&<KnowledgeReview candidates={mapCandidates} relations={knowledgeRelations} papers={papers} openPaper={openPaper} onChanged={()=>void refreshKnowledge()} onSelectEntity={selectEntity}/>}
      {tab==='maintenance'&&<KnowledgeMaintenance scopeType={effectiveId?'collection':'library'} scopeId={effectiveId||undefined} paperIds={effectiveId?papers.map(p=>p.id):undefined} openPaper={openPaper}/>} 

    </>}
    {(selectedEntity||pendingRelation)&&<KnowledgeEntityDossier entityId={selectedEntity?.id} entityName={selectedEntity?.name} pendingRelation={pendingRelation} openPaper={openPaper} onClose={()=>{setSelectedEntity(null);setPendingRelation(null)}} onSelectEntity={selectEntity} onResolved={relation=>{setKnowledgeRelations(items=>items.map(item=>item.id===relation.id?relation:item));setPendingRelation(current=>current?.id===relation.id?relation:current)}} onChanged={detail=>{if(detail)setSelectedEntity(detail);void refreshKnowledge()}}/>}
  </div>
}

type EvolutionViewProps = {
  details: PaperDetail[]
  relations: KnowledgeRelation[]
  openPaper: (id: string) => void
  t: (key: LocaleKey) => string
}

const evolutionLanes = [
  { id: 'lineage', label: 'evolutionLineage' },
  { id: 'comparison', label: 'evolutionComparison' },
  { id: 'ablation', label: 'evolutionAblation' },
  { id: 'evaluation', label: 'evolutionEvaluation' },
  { id: 'dependency', label: 'evolutionDependency' },
] as const

function EvolutionView({ details, relations, openPaper, t }: EvolutionViewProps) {
  const candidates = details.flatMap(paper => paper.knowledge_candidates ?? [])
  const coreMethods = candidates.filter(candidate => candidate.layer === 'primary' && candidate.importance === 'core')
  const confirmed = relations.filter(relation => relation.status === 'confirmed' || relation.status === 'known' || relation.status === 'alias')
  const pending = relations.filter(relation => !confirmed.includes(relation))
  return <section className="evolution-view">
    <header className="evolution-heading">
      <div>
        <div className="eyebrow">FIELD MAP</div>
        <h2>{t('evolution')}</h2>
        <p>{t('evolutionIntro')}</p>
      </div>
      <div className="evolution-count"><strong>{relations.length}</strong><span>{t('knowledgeRelations')}</span></div>
    </header>
    {coreMethods.length > 0 && <section className="evolution-core" aria-label={t('evolutionCoreMethod')}>
      <span className="evolution-core-label">{t('evolutionCoreMethod')}</span>
      <div>{coreMethods.map(candidate => <button key={candidate.id} className="core-method" onClick={() => openPaper(candidate.paper_id)}>{candidate.name}<ArrowUpRight size={12}/></button>)}</div>
    </section>}
    {relations.length === 0 ? <Empty title={t('noEvolution')} text={t('knowledgeEvolutionEmpty')}/> : <div className="evolution-lanes">
      {evolutionLanes.map(lane => {
        const items = confirmed.filter(relation => (relation.family ?? 'comparison') === lane.id)
        return <section className={`evolution-lane lane-${lane.id}`} key={lane.id}>
          <header><span className="lane-mark"/><div><h3>{t(lane.label as LocaleKey)}</h3><small>{items.length}</small></div></header>
          {items.length === 0 ? <p className="evolution-no-items">{t('evolutionNoItems')}</p> : <div className="evolution-edges">{items.map(relation => <EvolutionEdge key={relation.id} relation={relation} openPaper={openPaper} t={t}/>)}</div>}
        </section>
      })}
      {pending.length > 0 && <section className="evolution-lane lane-pending">
        <header><span className="lane-mark"/><div><h3>{t('evolutionPending')}</h3><small>{pending.length}</small></div></header>
        <div className="evolution-edges">{pending.map(relation => <EvolutionEdge key={relation.id} relation={relation} openPaper={openPaper} t={t}/>)}</div>
      </section>}
    </div>}
  </section>
}

function EvolutionEdge({ relation, openPaper, t }: { relation: KnowledgeRelation; openPaper: (id: string) => void; t: (key: LocaleKey) => string }) {
  const statusLabel = relation.status === 'unresolved' ? t('evolutionPending') : relation.status
  return <article className={`evolution-edge importance-${relation.importance ?? 'supporting'}`}>
    <div className="evolution-edge-path"><strong>{relation.source_name}</strong><span className="evolution-edge-relation">{relation.relation.split('_').join(' ')}</span><strong>{relation.target_name}</strong></div>
    <p>{relation.description || t('unreported')}</p>
    <footer><span className={`knowledge-chip chip-${relation.status}`}>{statusLabel}</span><button className="text-btn" onClick={() => openPaper(relation.paper_id)}><Link2 size={12}/>{t('evolutionSource')}</button></footer>
  </article>
}

function CitationGraph({graph,openPaper}:{graph:Graph;openPaper:(id:string)=>void}) {
  const count=graph.nodes.length
  const positions=new Map(graph.nodes.map((node,index)=>{const angle=index*2*Math.PI/Math.max(count,1)-Math.PI/2;return[node.id,{x:440+Math.cos(angle)*280,y:260+Math.sin(angle)*190}]}))
  return <svg className="citation-svg" viewBox="0 0 880 520" role="img" aria-label="Citation graph"><defs><marker id="edge-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>{graph.edges.map(edge=>{const a=positions.get(edge.source);const b=positions.get(edge.target);if(!a||!b)return null;const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1;return <line key={edge.id} x1={a.x+dx/len*24} y1={a.y+dy/len*24} x2={b.x-dx/len*24} y2={b.y-dy/len*24} className={'citation-edge '+(edge.relation_source==='llm_inferred'||edge.relation_source==='demo'?'inferred':'')} markerEnd="url(#edge-arrow)"><title>{edge.relation} · {edge.relation_source}</title></line>})}{graph.nodes.map(node=>{const p=positions.get(node.id)!;return <g key={node.id} transform={'translate('+p.x+','+p.y+')'} className="citation-node" tabIndex={0} role="button" onClick={()=>openPaper(node.id)} onKeyDown={e=>{if(e.key==='Enter')openPaper(node.id)}} aria-label={node.label}><title>{node.label}</title><circle r={23}/><text textAnchor="middle" y={4} className="node-year">{node.year??'—'}</text><text textAnchor="middle" y={41} className="node-label">{node.label.slice(0,26)}{node.label.length>26?'…':''}</text></g>})}</svg>
}
