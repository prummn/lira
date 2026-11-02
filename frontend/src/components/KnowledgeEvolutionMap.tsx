import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { ArrowUpRight, CircleAlert, GitBranch, Search, X } from 'lucide-react'
import type { Graph, KnowledgeAudit, KnowledgeCandidate, KnowledgeRelation, Paper } from '../types'
import { useUi, type LocaleKey } from '../lib/i18n'
import { isCoreContribution, methodNetwork, neighborhoodLayout, settled, type MethodEdge, type PositionedNode, type MethodNode } from '../lib/knowledgeMap'
import './knowledge-evolution.css'

type MapProps = {
  candidates: KnowledgeCandidate[]; relations: KnowledgeRelation[]; audits?: KnowledgeAudit[]; graph:Graph; papers?:Paper[]
  onSelectEntity: (entityId:string, name:string) => void
  onSelectPending: (relation:KnowledgeRelation) => void
  onOpenEvidence: (paperId:string, page:number|null, chunkId?:string, quote?:string) => void
}
const layers:Record<string,LocaleKey>={primary:'evolutionCoreMethod',baseline:'evolutionComparison',ablation:'evolutionAblation',component:'evolutionDependency',evaluation:'evolutionEvaluation',pending:'evolutionPending'}
const relationLabels:Record<string,LocaleKey>={builds_on:'mapBuildsOn',extends:'mapExtends',replaces:'mapReplaces',inspired_by:'mapInspiredBy',requires_concept:'mapUses',compares_with:'mapCompares',contrasts_with:'mapContrasts',evaluated_on:'mapEvaluates',uses_dataset:'mapDataset'}

export function KnowledgeEvolutionMap({ candidates, relations, audits=[], graph, papers=[], onSelectEntity, onSelectPending, onOpenEvidence }:MapProps) {
  const {t}=useUi()
  const marker=useId().replace(/:/g,'')
  const network=useMemo(()=>methodNetwork(candidates,relations,papers),[candidates,relations,papers])
  const [focusKey,setFocusKey]=useState('')
  const [selection,setSelection]=useState('')
  const inspector=useRef<HTMLElement>(null)
  const [show,setShow]=useState({component:true,evaluation:false,ablation:false})
  const focus=network.core.find(n=>n.key===focusKey)??network.core[0]
  const layout=focus?neighborhoodLayout(focus,network.edges,show,papers):null
  const points=new Map(layout?.points.map(p=>[p.node.key,p])??[])
  const selected=layout?.edges.find(e=>e.key===selection)
  useEffect(()=>{
    if(selected) inspector.current?.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})
  },[selected?.key])
  const pending=layout?.edges.flatMap(e=>e.relations.filter(r=>!settled(r.status)))??[]
  const focusPapers=new Set(focus?.candidates.filter(c=>isCoreContribution(c,papers)).map(c=>c.paper_id)??[])
  const coveredPapers=new Set(network.core.flatMap(node=>node.candidates.filter(c=>isCoreContribution(c,papers)).map(c=>c.paper_id)))
  const incomplete=papers.filter(p=>!coveredPapers.has(p.id))
  const contributionLabel=(node:MethodNode)=>t(node.candidates.some(c=>isCoreContribution(c,papers)&&c.entity_type==='benchmark')?'mapBenchmarkContribution':node.candidates.some(c=>isCoreContribution(c,papers)&&c.entity_type==='dataset')?'mapDatasetContribution':'mapMethodContribution')
  const citations=graph.edges.filter(e=>e.relation==='cites'&&e.relation_source!=='demo'&&e.evidence?.length&&(focusPapers.has(e.source)||focusPapers.has(e.target)))
  const auditItems=audits.filter(a=>focusPapers.has(a.paper_id)).flatMap(a=>Object.values(a.coverage).flatMap(g=>Object.values(g)))
  const choose=(key:string)=>{setFocusKey(key);setSelection('')}
  const title=(id:string)=>graph.nodes.find(n=>n.id===id)?.label??id
  const label=(r:KnowledgeRelation)=>t(relationLabels[r.relation]??'dossierRelations')
  return <section className="knowledge-evolution-map" aria-label={t('evolutionMapLabel')}>
    <header className="knowledge-map-topline"><div><span className="eyebrow">CONTRIBUTION ATLAS</span><h2>{t('evolution')}</h2><p>{t('mapFocusIntro')}</p></div></header>
    {papers.length>0&&<section className="knowledge-map-coverage" aria-label={t('mapCoverage')}><header><strong>{t('mapCoverage')}</strong><span>{coveredPapers.size} / {papers.length} {t('mapPapersRepresented')}</span></header>{incomplete.length>0&&<details open><summary>{incomplete.length} {t('mapIncompletePapers')}</summary>{incomplete.map(p=><article key={p.id}><div><strong>{p.title}</strong><small>{p.analysis_status==='failed'||p.intelligence_status==='failed'?t('comparisonAnalysisFailed'):candidates.some(c=>c.paper_id===p.id&&c.status!=='rejected')?t('mapCoreMissing'):t('mapKnowledgeMissing')}</small></div><button className="text-btn" onClick={()=>onOpenEvidence(p.id,null)}>{t('knowledgeOpenPaper')}<ArrowUpRight size={13}/></button></article>)}</details>}</section>}
    {!focus||!layout?<div className="knowledge-map-empty knowledge-map-empty-canvas"><svg className="knowledge-map-svg" viewBox="0 0 850 260" role="img" aria-label={t('evolutionMapLabel')}><text className="map-empty-label" x="425" y="130" textAnchor="middle">{t('knowledgeEvolutionEmpty')}</text></svg></div>:<>
      <nav className="knowledge-map-methods" aria-label={t('mapChooseMethod')}>{network.core.map(node=><button key={node.key} className={node===focus?'active':''} aria-label={node.name} aria-pressed={node===focus} onClick={()=>choose(node.key)}>{node.name}<span className="map-contribution-type">{contributionLabel(node)}</span><small>{node.candidates.filter(c=>isCoreContribution(c,papers)).map(c=>graph.nodes.find(p=>p.id===c.paper_id)?.year).filter(Boolean).filter((y,i,all)=>all.indexOf(y)===i).join(' / ')}</small></button>)}</nav>
      <div className="knowledge-map-controls"><span>{t('mapShow')}</span>{(['component','evaluation','ablation'] as const).map(group=>{
        const count=[...layout.groups.values()].filter(g=>g===group).length
        return <button key={group} aria-pressed={show[group]} disabled={!count} onClick={()=>setShow(s=>({...s,[group]:!s[group]}))}>{t(layers[group])}<small>{count}</small></button>
      })}<span className="map-direction">{t('mapDirection')}</span></div>
      <div className="knowledge-map-canvas">
        <div className="knowledge-map-scroll" role="region" aria-label={t('evolutionMapLabel')} tabIndex={0}>
          <svg className="knowledge-map-svg" viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label={t('evolutionMapLabel')}>
            <defs><marker id={marker} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>
            <text className="map-column-label" x="40" y="34">{t('mapRelatedMethods')}</text><text className="map-column-label" x="500" y="34" textAnchor="middle">{t('mapCurrentMethod')}</text><text className="map-column-label" x="714" y="34">{t('mapComponentsEvaluation')}</text>
            {layout.edges.map(edge=><MapEdge key={edge.key} edge={edge} source={points.get(edge.source.key)!} target={points.get(edge.target.key)!} marker={marker} active={selected===edge} label={edge.relations.map(label).filter((x,i,a)=>a.indexOf(x)===i).join(' · ')} onSelect={()=>setSelection(edge.key)}/>)}
            {layout.edges.map(edge=><MapEdge key={'control-'+edge.key} edge={edge} source={points.get(edge.source.key)!} target={points.get(edge.target.key)!} marker={marker} active={selected===edge} label={edge.relations.map(label).filter((x,i,a)=>a.indexOf(x)===i).join(' · ')} onSelect={()=>setSelection(edge.key)} handleOnly/>)}
            {layout.points.map(point=>{
              const node=point.node
              const action=node.pending?()=>onSelectPending(node.pending!):node.entityId?()=>onSelectEntity(node.entityId!,node.name):undefined
              const meanings=layout.edges.filter(e=>e.source===node||e.target===node).flatMap(e=>e.relations.map(label)).filter((x,i,a)=>a.indexOf(x)===i)
              return <MapNode key={node.key} point={point} caption={point.group==='primary'?contributionLabel(node):meanings.join(' · ')||t(layers[point.group]??'dossierRelations')} onClick={action}/>
            })}
            {!layout.edges.length&&<text className="map-empty-label" x="500" y={layout.height/2+80} textAnchor="middle">{t('mapNoVisibleRelations')}</text>}
          </svg>
        </div>
        <footer className="knowledge-map-footer"><span><GitBranch size={14}/>{layout.edges.reduce((n,e)=>n+e.relations.length,0)} {t('knowledgeRelations')}</span><span><Search size={14}/>{t('mapClickEvidence')}</span>{pending.length>0&&<span className="knowledge-map-pending-count"><CircleAlert size={14}/>{pending.length} {t('evolutionPending')}</span>}{auditItems.some(a=>a.state==='missing')&&<span>{auditItems.filter(a=>a.state==='missing').length} {t('auditMissing')}</span>}</footer>
      </div>
      {selected&&<section ref={inspector} className="knowledge-map-inspector" aria-label={t('evolutionSource')}><header><div><span className="eyebrow">{t('evolutionSource')}</span><h3>{selected.source.name}<span>{selected.reciprocal?'↔':'→'}</span>{selected.target.name}</h3></div><button className="icon-btn" aria-label={t('close')} onClick={()=>setSelection('')}><X size={16}/></button></header>{selected.relations.map(relation=><article key={relation.id}><div className="map-relation-heading"><strong>{label(relation)}</strong><span className="map-relation-direction">{relation.source_name} → {relation.target_name}</span>{!settled(relation.status)&&<button className="text-btn" onClick={()=>onSelectPending(relation)}>{t('evolutionPending')}<ArrowUpRight size={13}/></button>}</div><p>{relation.description}</p>{relation.evidence.map((e,i)=><div className="map-evidence" key={`${e.chunk_id}-${i}`}><blockquote>{e.quote}</blockquote><button onClick={()=>onOpenEvidence(relation.paper_id,e.page,e.chunk_id,e.quote)}><span>{title(relation.paper_id)}</span><small>{t('page')} {e.page??'—'}<ArrowUpRight size={13}/></small></button></div>)}</article>)}</section>}
      {citations.length>0&&<section className="knowledge-map-citations"><h3>{t('mapPaperCitations')}</h3><p>{t('mapCitationHint')}</p>{citations.map(edge=><details key={edge.id}><summary><span><strong>{title(edge.source)}</strong><span className="map-cites-label">{t('mapCites')}{edge.reference_label&&` [${edge.reference_label}]`}</span><strong>{title(edge.target)}</strong></span></summary><blockquote>{edge.description}</blockquote>{edge.evidence?.map((e,i)=><button key={`${e.chunk_id}-${i}`} className="text-btn" onClick={()=>onOpenEvidence(edge.source,e.page,e.chunk_id,e.quote)}>{t('evolutionSource')} · {t('page')} {e.page??'—'}<ArrowUpRight size={13}/></button>)}</details>)}</section>}
    </>}
  </section>
}

function MapEdge({edge,source,target,marker,active,label,onSelect,handleOnly=false}:{edge:MethodEdge;source:PositionedNode;target:PositionedNode;marker:string;active:boolean;label:string;onSelect:()=>void;handleOnly?:boolean}) {
  const sign=target.x>source.x?1:-1
  const sx=source.x+sign*source.width/2,tx=target.x-sign*target.width/2
  const mid=(sx+tx)/2
  const path=`M ${sx} ${source.y} C ${mid} ${source.y}, ${mid} ${target.y}, ${tx} ${target.y}`
  const pending=edge.relations.some(r=>!settled(r.status))
  const direction=edge.reciprocal?'↔':'→'
  const name=`${edge.source.name} ${direction} ${edge.target.name} · ${label}`
  // Paint every pointer handle after every path, so crossing paths cannot cover it.
  if(handleOnly)return <g className={`knowledge-map-edge-control ${active?'active':''}`} role="button" tabIndex={0} aria-label={name} aria-pressed={active} onClick={onSelect} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect()}}}><title>{name}</title><circle className="map-edge-target" cx={mid} cy={(source.y+target.y)/2} r="12"/><circle className="map-edge-handle" cx={mid} cy={(source.y+target.y)/2} r="4"/></g>
  return <g className={`knowledge-map-edge ${pending?'edge-pending':''} ${active?'active':''}`} aria-hidden="true" onClick={onSelect}><path d={path} className="knowledge-map-edge-hit"/><path d={path} className="knowledge-map-edge-line" markerEnd={`url(#${marker})`} markerStart={edge.reciprocal?`url(#${marker})`:undefined}/></g>
}

function MapNode({point,caption,onClick}:{point:PositionedNode;caption:string;onClick?:()=>void}) {
  const {node,x,y,width,group}=point
  const lines=node.name.length>29?[node.name.slice(0,29),node.name.slice(29,57)+(node.name.length>57?'…':'')]:[node.name]
  return <g className={`knowledge-map-node node-${group} ${group==='primary'?'node-core':''} ${node.pending?'knowledge-map-pending':''}`} data-layer={group} transform={`translate(${x},${y})`} role={onClick?'button':'group'} tabIndex={onClick?0:undefined} aria-label={node.name} onClick={onClick} onKeyDown={e=>{if(onClick&&(e.key==='Enter'||e.key===' ')){e.preventDefault();onClick()}}}>
    <title>{node.name} · {caption}</title><rect x={-width/2} y="-29" width={width} height="58" rx="7"/>
    <circle className="node-dot" cx={-width/2+15} cy="0" r="3"/>
    {lines.map((line,i)=><text className="node-label" key={i} x={-width/2+27} y={lines.length===1?0:-8+i*15}>{line}</text>)}
    <text className="node-layer-label" textAnchor="middle" x="0" y="43">{caption}</text>
  </g>
}
