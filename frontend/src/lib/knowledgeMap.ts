import type { KnowledgeCandidate, KnowledgeRelation, Paper } from '../types'

export const isContextual = (candidate:KnowledgeCandidate) => ['incidental','incorrect'].includes(String((candidate.conflict._steward_context as {verdict?:string}|undefined)?.verdict))
export const isCoreMethod = (candidate:KnowledgeCandidate) => !isContextual(candidate) && candidate.entity_type==='method' && candidate.layer==='primary' && candidate.role==='proposed'
export const settled = (status: string) => ['confirmed', 'known', 'alias'].includes(status)
const usable = (status: string) => status !== 'rejected'
const norm = (value: string) => value.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '')
type MapPaper = Pick<Paper, 'id'|'title'>

export function isCoreContribution(candidate:KnowledgeCandidate, papers:MapPaper[] = []) {
  if (!usable(candidate.status) || isContextual(candidate)) return false
  if (isCoreMethod(candidate)) return true
  if (!['benchmark','dataset'].includes(candidate.entity_type) || candidate.importance !== 'core') return false
  if (candidate.role === 'proposed') return true
  // Older extraction used `used` even for a paper's own benchmark. Only an
  // exact title identity can recover that contribution; evaluated datasets in
  // another paper must remain supporting objects.
  const ownTitle = papers.find(p => p.id === candidate.paper_id)?.title.split(/[:：]/)[0]
  return !!ownTitle && [candidate.name,candidate.normalized_name,...candidate.aliases].some(name => norm(name) === norm(ownTitle))
}

export type MethodNode = {
  key: string; name: string; candidates: KnowledgeCandidate[]; layer: string
  entityId?: string; pending?: KnowledgeRelation
}
export type MethodEdge = { key: string; source: MethodNode; target: MethodNode; relations: KnowledgeRelation[]; reciprocal?:boolean }

export function methodNetwork(candidates: KnowledgeCandidate[], relations: KnowledgeRelation[], papers:MapPaper[] = []) {
  const nodes = new Map<string, MethodNode>()
  const byId = new Map<string, MethodNode>()
  const byName = new Map<string, Set<MethodNode>>()
  const addName = (name: string, node: MethodNode) => {
    const key = norm(name)
    if (!byName.has(key)) byName.set(key, new Set())
    byName.get(key)!.add(node)
  }
  const priority: Record<string, number> = {primary:6, baseline:5, ablation:4, component:3, evaluation:2}
  for (const candidate of candidates.filter(c => usable(c.status) && !isContextual(c))) {
    // Candidate IDs resolve paper-local roles; canonical IDs merge real aliases.
    // Unconfirmed homonyms in different papers must not collapse accidentally.
    const key = candidate.entity_id ?? `${candidate.paper_id}:${candidate.entity_type}:${norm(candidate.name)}`
    let node = nodes.get(key)
    if (!node) {
      node = {key, name:candidate.name, candidates:[], layer:candidate.layer ?? 'component', entityId:candidate.entity_id ?? undefined}
      nodes.set(key, node)
    }
    node.candidates.push(candidate)
    if ((priority[candidate.layer ?? ''] ?? 0) > (priority[node.layer] ?? 0)) {
      node.layer = candidate.layer!; node.name = candidate.name
    }
    byId.set(candidate.id, node)
    for (const name of [candidate.name, candidate.normalized_name, ...candidate.aliases]) addName(name, node)
  }
  const endpoint = (id: string | null, name: string, paperId: string) => {
    if (id) return byId.get(id) // A rejected or out-of-scope endpoint stays excluded.
    const matches = [...(byName.get(norm(name)) ?? [])]
    const local = matches.filter(n => n.candidates.some(c => c.paper_id === paperId))
    return local.length === 1 ? local[0] : matches.length === 1 ? matches[0] : undefined
  }
  const edges = new Map<string, MethodEdge>()
  for (const relation of relations.filter(r => usable(r.status))) {
    const source = endpoint(relation.source_candidate_id, relation.source_normalized_name, relation.paper_id)
    let target = endpoint(relation.target_candidate_id, relation.target_normalized_name, relation.paper_id)
    if (!target && !relation.target_candidate_id && !settled(relation.status)) {
      const key = `pending:${relation.paper_id}:${norm(relation.target_name)}`
      target = nodes.get(key)
      if (!target) {
        target = {key, name:relation.target_name, candidates:[], layer:'pending', pending:relation}
        nodes.set(key, target)
      }
    }
    if (!source || !target || source === target) continue
    if (!target.entityId && !settled(relation.status)) target.pending ??= relation
    const key = [source.key,target.key].sort().join('↔')
    if (!edges.has(key)) edges.set(key, {key, source, target, relations:[]})
    const edge=edges.get(key)!
    edge.reciprocal ||= edge.source !== source
    edge.relations.push(relation)
  }
  const core = [...nodes.values()].filter(n => n.candidates.some(c => isCoreContribution(c,papers)))
  core.sort((a,b) => {
    const count = (n:MethodNode) => [...edges.values()].filter(e => e.source === n || e.target === n).length
    return count(b)-count(a) || a.name.localeCompare(b.name)
  })
  return {nodes:[...nodes.values()], edges:[...edges.values()], core}
}

export type PositionedNode = {node:MethodNode; x:number; y:number; width:number; group:string}
export function neighborhoodLayout(focus:MethodNode, edges:MethodEdge[], show:{component:boolean;evaluation:boolean;ablation:boolean}, papers:MapPaper[] = []) {
  const connected = edges.filter(e => e.source === focus || e.target === focus)
  const groups = new Map<string,string>()
  const focusPapers=new Set(focus.candidates.filter(c=>isCoreContribution(c,papers)).map(c=>c.paper_id))
  const left:MethodNode[] = [], right:MethodNode[] = []
  for (const edge of connected) {
    const node = edge.source === focus ? edge.target : edge.source
    if (groups.has(node.key)) continue
    const local=node.candidates.filter(c=>focusPapers.has(c.paper_id))
    const localLayer=local.find(c=>c.layer==='baseline')?.layer??local[0]?.layer??node.layer
    const group = localLayer === 'primary' ? 'baseline' : localLayer
    groups.set(node.key,group)
    if ((group === 'component' || group === 'evaluation' || group === 'ablation') && !show[group]) continue
    ;(['component','evaluation'].includes(group) ? right : left).push(node)
  }
  const order:Record<string,number>={baseline:0,pending:1,ablation:2,component:3,evaluation:4}
  const sort = (a:MethodNode,b:MethodNode) => (order[groups.get(a.key)!]??0)-(order[groups.get(b.key)!]??0)||a.name.localeCompare(b.name)
  left.sort(sort); right.sort(sort)
  const height = Math.max(420, 124 + Math.max(left.length,right.length)*76)
  const positioned:PositionedNode[]=[{node:focus,x:500,y:height/2,width:226,group:'primary'}]
  for(const [side,x] of [[left,163],[right,837]] as const) {
    const start = (height-(side.length-1)*76)/2
    side.forEach((node,index)=>positioned.push({node,x,y:start+index*76,width:246,group:groups.get(node.key)!}))
  }
  const visible = new Set(positioned.map(p=>p.node.key))
  return {width:1000,height,points:positioned,edges:connected.filter(e=>visible.has(e.source.key)&&visible.has(e.target.key)),groups}
}
