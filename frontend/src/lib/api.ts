import type { ActivityDay, ActivityKind, Answer, CodexAccountStatus, Collection, ExplainStyle, Graph, HistoryItem, IntelligenceTask, KnowledgeAudit, KnowledgeCandidate, KnowledgeEntityDetail, KnowledgeEntityIndexItem, KnowledgePaper, KnowledgeRelation, LibraryAnswer, MaintenanceIssue, MaintenanceRun, MaintenanceRunDetail, ModelSettings, ModelProfile, ModelProfiles, ModelProfileInput, ModelRouting, Note, NoteKind, Paper, PaperDetail, PaperMetadataUpdate, PdfVisualRegion, ReadingDocument, ReadingStatus, ReadingTranslation, ResearchActivity, SearchHit } from '../types'
import type { CodexModels, NoteInput, QuickTranslation, ParagraphReview } from '../types'
import type { ChatIdentity, ChatKind, SavedConversation, ConversationRead } from '../types'
import type { KnowledgeEntityInput, KnowledgeEvidence, KnowledgeMergePreview, KnowledgeRelationInput } from '../types'
import type { CollectionResearchState, ResearchSettings, ResearchStatus, ResearchTask, ResearchScope, ResearchFinding, ResearchFindingsState, FindingAction, FindingRevision } from '../types'
import type { TranslationJob, TranslationJobAction } from '../types'

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'ApiError' }
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try { response = await fetch(`/api${path}`, init) }
  catch { throw new ApiError('无法连接本地服务，请运行启动脚本后重试。', 0) }
  const text = await response.text()
  let payload: unknown
  try { payload = text ? JSON.parse(text) : null }
  catch { throw new ApiError('本地服务返回了无法读取的响应。请检查服务是否启动。', response.status) }
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? (payload as { detail: unknown }).detail : null
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg ?? '').join('；') : `请求失败 (${response.status})`
    throw new ApiError(message, response.status)
  }
  return payload as T
}
const json = (body: unknown): RequestInit => ({ headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
async function loadPapers() {
  const first=await request<{items:Paper[];total:number}>('/papers?limit=200&offset=0')
  const items=[...first.items]
  for(let offset=items.length;offset<first.total;) {
    const next=await request<{items:Paper[];total:number}>(`/papers?limit=200&offset=${offset}`)
    if(!next.items.length)break
    items.push(...next.items);offset+=next.items.length
  }
  return {items:[...new Map(items.map(p=>[p.id,p])).values()],total:first.total}
}
export const api = {
  researchStatus: () => request<ResearchStatus>('/research/status'),
  researchQuota: () => request<{quota:ResearchStatus['quota'];checked_at:number;available:boolean;quota_error_code?:string|null;quota_using_recent?:boolean;budget?:ResearchStatus['budget']}>('/research/quota'),
  followReading: (id:string) => request<{tasks:ResearchTask[]}>(`/research/collections/${encodeURIComponent(id)}/reading`, {method:'POST'}),
  researchSettings: (body:ResearchSettings) => request<ResearchSettings>('/research/settings', {method:'PUT',...json(body)}),
  quotaPolicy: (body:Pick<ResearchSettings,'start_remaining'|'stop_remaining'|'long_reserve'>) => request<ResearchSettings>('/research/quota-policy', {method:'PATCH',...json(body)}),
  collectionResearch: (id:string, revisionId?:string) => request<CollectionResearchState>(`/research/collections/${encodeURIComponent(id)}${revisionId?'?revision_id='+encodeURIComponent(revisionId):''}`),
  researchScope: (id:string,body:ResearchScope) => request<ResearchScope>(`/research/collections/${encodeURIComponent(id)}/scope`, {method:'PUT',...json(body)}),
  updateResearch: (id:string,kind:'essay'|'findings'='essay') => request<ResearchTask>(`/research/collections/${encodeURIComponent(id)}/update?kind=${kind}`,{method:'POST'}),
  researchFindings: (id:string) => request<ResearchFindingsState>(`/research/collections/${encodeURIComponent(id)}/findings`),
  planResearch: (id:string) => request<ResearchTask>(`/research/collections/${encodeURIComponent(id)}/agenda`,{method:'POST'}),
  findingAction: (id:string,action:FindingAction) => request<ResearchFinding>(`/research/findings/${encodeURIComponent(id)}`,{method:'PATCH',...json({action})}),
  findingHistory: (id:string) => request<{revisions:FindingRevision[]}>(`/research/findings/${encodeURIComponent(id)}/history`),
  researchTaskAction: (id:string,action:'retry'|'cancel') => request<ResearchTask>(`/research/tasks/${encodeURIComponent(id)}/${action}`,{method:'POST'}),
  maintenanceRuns: (limit=20, scope?:{type?:string;id?:string}) => request<{items:MaintenanceRun[]}>(`/knowledge/maintenance/runs?limit=${limit}${scope?.type?`&scope_type=${encodeURIComponent(scope.type)}`:''}${scope?.id?`&scope_id=${encodeURIComponent(scope.id)}`:''}`),
  maintenanceRun: (id:string) => request<MaintenanceRunDetail>(`/knowledge/maintenance/runs/${encodeURIComponent(id)}`),
  maintenanceBacklog: (scope:{type:string;id?:string;paperIds?:string[]}) => request<import('../types').MaintenanceBacklog>(`/knowledge/maintenance/backlog?scope_type=${encodeURIComponent(scope.type)}${scope.id?`&scope_id=${encodeURIComponent(scope.id)}`:''}${scope.paperIds?.length?`&paper_ids=${encodeURIComponent(scope.paperIds.join(','))}`:''}`),
  createMaintenanceRun: (body:{scope_type:'library'|'collection'|'papers';scope_id?:string;paper_ids?:string[];allow_external?:boolean;force?:boolean}) => request<MaintenanceRunDetail>('/knowledge/maintenance/runs',{method:'POST',...json(body)}),
  applySafeMaintenance: (id:string) => request<{run:MaintenanceRunDetail;results:Array<{id:string;status:string;detail?:string}>}>(`/knowledge/maintenance/runs/${encodeURIComponent(id)}/apply-safe`,{method:'POST'}),
  maintenanceAction: (id:string,action:'retry'|'cancel') => request<MaintenanceRun>(`/knowledge/maintenance/runs/${encodeURIComponent(id)}/${action}`,{method:'POST'}),
  applyMaintenanceIssue: (id:string) => request<{issue:MaintenanceIssue;run:MaintenanceRun}>(`/knowledge/maintenance/issues/${encodeURIComponent(id)}/apply`,{method:'POST'}),
  rejectMaintenanceIssue: (id:string) => request<{issue:MaintenanceIssue;run:MaintenanceRun}>(`/knowledge/maintenance/issues/${encodeURIComponent(id)}/reject`,{method:'POST'}),
  undoMaintenanceIssue: (id:string) => request<{issue:MaintenanceIssue;run:MaintenanceRun}>(`/knowledge/maintenance/issues/${encodeURIComponent(id)}/undo`,{method:'POST'}),
  readingPresence: (clientId:string,reading:boolean) => request<{ok:boolean}>('/research/presence',{method:'POST',...json({client_id:clientId,reading})}),
  papers: loadPapers,
  deleteCollection: (id: string) => request<void>(`/collections/${encodeURIComponent(id)}`, {method:'DELETE'}),
  collections: () => request<{ items: Collection[] }>('/collections'),
  paper: (id: string) => request<PaperDetail>(`/papers/${encodeURIComponent(id)}`),
  deletePaper: (id: string) => request<{deleted_ids:string[]}>(`/papers/${encodeURIComponent(id)}`, {method:'DELETE'}),
  deletePapers: (paper_ids: string[]) => request<{deleted_ids:string[]}>('/papers/batch-delete', {method:'POST',...json({paper_ids})}),
  update: (id: string, body: PaperMetadataUpdate & { is_favorite?: boolean; reading_status?: ReadingStatus; tags?: string[] }) => request<Paper>(`/papers/${encodeURIComponent(id)}`, { method: 'PATCH', ...json(body) }),
  import: (file: File, analyze=false) => { const body = new FormData(); body.append('file', file); body.append('analyze',String(analyze)); return request<PaperDetail>('/papers/import', { method: 'POST', body }) },
  importUrl: (url: string, analyze=false) => request<PaperDetail>('/papers/import-url', { method: 'POST', ...json({url,analyze}) }),
  intelligenceTasks: (paperId:string) => request<{tasks:IntelligenceTask[]}>(`/intelligence/tasks?paper_id=${encodeURIComponent(paperId)}&limit=1`),
  queueAnalysis: (paper_ids:string[],force=false) => request<{tasks:IntelligenceTask[]}>('/intelligence/tasks',{method:'POST',...json({paper_ids,force})}),
  cancelAnalysis: (id:string) => request<IntelligenceTask>(`/intelligence/tasks/${encodeURIComponent(id)}/cancel`,{method:'POST'}),
  librarian: (body:ChatIdentity&{question:string;collection_id?:string;paper_ids?:string[];history?:HistoryItem[];reading_page?:number;conversation_kind?:'paper'|'librarian'},signal?:AbortSignal) => request<LibraryAnswer>('/intelligence/ask',{method:'POST',...json(body),signal}),
  conversations: (kind:ChatKind,paperId:string|undefined,context?:Record<string,unknown>,offset=0) => request<{items:SavedConversation[];has_more:boolean}>(`/conversations?kind=${kind}${paperId?`&paper_id=${encodeURIComponent(paperId)}`:''}${context?`&context=${encodeURIComponent(JSON.stringify(context))}`:''}&offset=${offset}`),
  conversation: <R,>(id:string) => request<ConversationRead<R>>(`/conversations/${encodeURIComponent(id)}`),
  createConversation: (kind:ChatKind,paperId:string|undefined,context:Record<string,unknown>) => request<SavedConversation>('/conversations',{method:'POST',...json({kind,paper_id:paperId,context})}),
  refreshMetadata: (id: string) => request<PaperDetail>(`/papers/${encodeURIComponent(id)}/refresh-metadata`, { method: 'POST' }),
  createCollection: (name: string, description: string, color = '#536f89') => request<Collection>('/collections', { method: 'POST', ...json({ name, description, color }) }),
  membership: (collectionId: string, paperId: string, add: boolean) => request<unknown>(`/collections/${encodeURIComponent(collectionId)}/papers/${encodeURIComponent(paperId)}`, { method: add ? 'PUT' : 'DELETE' }),
  addCollectionPapers: (collectionId: string, paperIds: string[]) => request<Collection>(`/collections/${encodeURIComponent(collectionId)}/papers`, {method: 'POST', ...json({paper_ids: paperIds})}),
  analyze: (id: string) => request<PaperDetail>(`/papers/${encodeURIComponent(id)}/analyze`, { method: 'POST' }),
  ask: (id: string, question: string, identity:ChatIdentity={},signal?:AbortSignal) => request<Answer>(`/papers/${encodeURIComponent(id)}/ask`, { method: 'POST', ...json({ question,...identity }),signal }),
  explain: (id:string, body:ChatIdentity&{chunk_id?:string;selected_text?:string;translated_text?:string;page?:number;bbox?:number[];image_data_url?:string;visual_kind?:'figure'|'table';visual_label?:string;style?:ExplainStyle;question?:string;context_scope?:'auto'|'paragraph'|'section'|'full';allow_external?:boolean;history?:Array<{question:string;answer:string}>}) => request<Answer>(`/papers/${encodeURIComponent(id)}/explain`, {method:'POST',...json(body)}),
  note: (id: string, body: NoteInput) => request<Note>(`/papers/${encodeURIComponent(id)}/notes`, { method: 'POST', ...json(body) }),
  updateNote: (id:string,noteId:string,body:{content:string;kind:NoteKind}) => request<Note>(`/papers/${encodeURIComponent(id)}/notes/${encodeURIComponent(noteId)}`,{method:'PATCH',...json(body)}),
  deleteNote: (id: string, noteId: string) => request<unknown>(`/papers/${encodeURIComponent(id)}/notes/${encodeURIComponent(noteId)}`, { method: 'DELETE' }),
  graph: (collectionId: string) => request<Graph>(`/graph${collectionId ? `?collection_id=${encodeURIComponent(collectionId)}` : ''}`),
  search: (query: string, collectionId='') => request<{items: SearchHit[]}>(`/search?query=${encodeURIComponent(query)}${collectionId?'&collection_id='+encodeURIComponent(collectionId):''}`),
  settings: () => request<ModelSettings>('/settings'),
  modelProfiles: () => request<ModelProfiles>('/settings/profiles'),
  codexAccount: () => request<CodexAccountStatus>('/settings/codex'),
  codexConcurrency: (max_concurrency:number) => request<ModelProfiles>('/settings/codex/concurrency', {method:'PUT',...json({max_concurrency})}),
  codexModels: (refresh=false) => request<CodexModels>(`/settings/codex/models${refresh?'?refresh=true':''}`),
  codexLogin: () => request<CodexAccountStatus>('/settings/codex/login', {method:'POST'}),
  codexCancelLogin: () => request<CodexAccountStatus>('/settings/codex/login', {method:'DELETE'}),
  codexLogout: () => request<CodexAccountStatus>('/settings/codex/logout', {method:'POST'}),
  saveModelProfile: (id:string|null,body:ModelProfileInput) => request<ModelProfile>(`/settings/profiles${id?'/'+encodeURIComponent(id):''}`, {method:id?'PUT':'POST',...json(body)}),
  deleteModelProfile: (id:string) => request<ModelProfiles>(`/settings/profiles/${encodeURIComponent(id)}`,{method:'DELETE'}),
  modelRouting: (body:ModelRouting) => request<ModelProfiles>('/settings/routing',{method:'PUT',...json(body)}),
  readingParagraphs: (id:string) => request<ReadingDocument>(`/papers/${encodeURIComponent(id)}/reading-paragraphs`),
  visualRegions: (id:string) => request<{items:PdfVisualRegion[]}>(`/papers/${encodeURIComponent(id)}/visual-regions`),
  translationJobs: (id:string) => request<{jobs:TranslationJob[]}>(`/papers/${encodeURIComponent(id)}/translation-jobs`),
  queueTranslations: (id:string,mode:'selected'|'full',paragraphIds?:string[]) => request<TranslationJob>(`/papers/${encodeURIComponent(id)}/translation-jobs`,{method:'POST',...json({mode,...(paragraphIds?{paragraph_ids:paragraphIds}:{})})}),
  translationJobAction: (id:string,action:TranslationJobAction) => request<TranslationJob>(`/translation-jobs/${encodeURIComponent(id)}/${action}`,{method:'POST'}),
  prioritizeTranslation: (id:string,paragraphId:string) => request<TranslationJob>(`/papers/${encodeURIComponent(id)}/translation-jobs/prioritize`,{method:'POST',...json({paragraph_id:paragraphId})}),
  reviewParagraph: (id:string,paragraphId:string,signal?:AbortSignal) => request<ParagraphReview>(`/papers/${encodeURIComponent(id)}/reading-paragraphs/review`,{method:'POST',...json({paragraph_id:paragraphId}),signal}),
  translateParagraph: (id:string,paragraphId:string,signal?:AbortSignal,force=false) => request<ReadingTranslation & {model_version?:string;cached:boolean}>(`/papers/${encodeURIComponent(id)}/translate`, {method:'POST',...json({paragraph_id:paragraphId,...(force?{force:true}:{})}),signal}),
  quickTranslate: (text:string, signal?:AbortSignal) => request<QuickTranslation>('/dictionary/lookup', {method:'POST',...json({text}),signal}),
  updateModelSettings: (body: {base_url:string;model:string;api_key?:string|null;wire_api:'chat_completions'|'responses';reasoning_effort:'disabled'|'none'|'minimal'|'low'|'medium'|'high'|'xhigh';timeout:number;test_connection:boolean}) => request<ModelSettings>('/settings/model', {method:'PUT', ...json(body)}),
  clearModelSettings: () => request<ModelSettings>('/settings/model', {method:'DELETE'}),
  translate: (id: string, chunkId: string) => request<{text: string; provider: string}>(`/papers/${encodeURIComponent(id)}/translate`, {method: 'POST', ...json({chunk_id: chunkId})}),
  activity: (days = 365) => request<ResearchActivity>(`/activity?days=${encodeURIComponent(days)}`),
  recordActivity: (kind: ActivityKind, paperId?: string) => request<ActivityDay>('/activity', {method:'POST', ...json({kind, ...(paperId ? {paper_id: paperId} : {})})}),
  paperKnowledge: (id:string) => request<KnowledgePaper>(`/papers/${encodeURIComponent(id)}/knowledge`),
  reviewKnowledgeCandidates: (id:string,candidateIds:string[],decision:'confirm'|'reject') => request<KnowledgePaper>(`/papers/${encodeURIComponent(id)}/knowledge/review`, {method:'POST',...json({candidate_ids:candidateIds,decision})}),
  paperKnowledgeAudit: (id:string) => request<KnowledgeAudit>(`/papers/${encodeURIComponent(id)}/knowledge/audit`),
  confirmKnowledgeCandidate: (id:string, body?:{name?:string;description?:string}) => request<KnowledgeCandidate>(`/knowledge/candidates/${encodeURIComponent(id)}/confirm`, {method:'POST', ...json(body ?? {})}),
  rejectKnowledgeCandidate: (id:string) => request<KnowledgeCandidate>(`/knowledge/candidates/${encodeURIComponent(id)}/reject`, {method:'POST'}),
  confirmKnowledgeRelation: (id:string) => request<KnowledgeRelation>(`/knowledge/relations/${encodeURIComponent(id)}/confirm`, {method:'POST'}),
  editConfirmKnowledgeCandidate: (id:string, body:{name:string;description?:string}) => request<KnowledgeCandidate>(`/knowledge/candidates/${encodeURIComponent(id)}/edit-confirm`, {method:'POST', ...json(body)}),
  extractKnowledgeParagraph: (id:string, paragraphId:string) => request<KnowledgePaper>(`/papers/${encodeURIComponent(id)}/knowledge/paragraph`, {method:'POST', ...json({paragraph_id:paragraphId})}),
  knowledgeEntities: (entityType?:string, paperIds?:string[]) => request<{items:KnowledgeEntityIndexItem[]}>(`/knowledge/entities${entityType||paperIds?'?'+new URLSearchParams({...entityType?{entity_type:entityType}:{},...paperIds?{paper_ids:paperIds.join(',')}:{}}):''}`),
  knowledgeOverview: (paperIds:string[]) => request<{candidates:KnowledgeCandidate[];relations:KnowledgeRelation[]}>(`/knowledge/overview${paperIds.length?`?paper_ids=${encodeURIComponent(paperIds.join(','))}`:''}`),
  knowledgeEntity: (id:string) => request<KnowledgeEntityDetail>(`/knowledge/entities/${encodeURIComponent(id)}`),
  updateKnowledgeEntity: (id:string, body:KnowledgeEntityInput) => request<KnowledgeEntityDetail>(`/knowledge/entities/${encodeURIComponent(id)}`, {method:'PATCH',...json(body)}),
  previewKnowledgeMerge: (id:string, targetId:string) => request<KnowledgeMergePreview>(`/knowledge/entities/${encodeURIComponent(id)}/merge-preview`, {method:'POST',...json({target_id:targetId})}),
  mergeKnowledgeEntity: (id:string, targetId:string) => request<KnowledgeEntityDetail>(`/knowledge/entities/${encodeURIComponent(id)}/merge`, {method:'POST',...json({target_id:targetId})}),
  updateKnowledgeRelation: (id:string, body:KnowledgeRelationInput) => request<KnowledgeRelation>(`/knowledge/relations/${encodeURIComponent(id)}`, {method:'PATCH',...json(body)}),
  createKnowledgeRelation: (paperId:string, body:KnowledgeRelationInput & {evidence:KnowledgeEvidence[]}) => request<KnowledgeRelation>(`/papers/${encodeURIComponent(paperId)}/knowledge/relations`, {method:'POST',...json(body)}),
  rejectKnowledgeRelation: (id:string) => request<KnowledgeRelation>(`/knowledge/relations/${encodeURIComponent(id)}/reject`, {method:'POST'}),
  restoreKnowledgeRelation: (id:string) => request<KnowledgeRelation>(`/knowledge/relations/${encodeURIComponent(id)}/restore`, {method:'POST'}),
  knowledgeRelations: (status:'confirmed'|'candidate'|'all'='confirmed') => request<{items:KnowledgeRelation[]}>(`/knowledge/relations?status=${encodeURIComponent(status)}`),
  resolveKnowledgeRelation: (id:string, body:{target_name:string;target_type:'paper'|'method'|'dataset'|'benchmark'|'task'|'metric'|'concept'|'venue'}) => request<KnowledgeRelation>(`/knowledge/relations/${encodeURIComponent(id)}/resolve`, {method:'POST', ...json(body)}),
}
export const errorMessage = (error: unknown): string => error instanceof Error ? error.message : String(error)
