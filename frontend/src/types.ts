export type Page = 'library' | 'reader' | 'knowledge' | 'researchers' | 'settings' | 'librarian' | 'research' | 'background'
export type NotebookTab = 'overview' | 'evidence' | 'ask' | 'notes' | 'knowledge'
export type ReadingStatus = 'unread' | 'skimming' | 'reading' | 'read' | 'important'
export type ActivityKind = 'reading' | 'notes' | 'language' | 'search' | 'imports'
export interface ActivityDay { date:string; reading:number; notes:number; language:number; search:number; imports:number; total:number; paper_ids:string[] }
export interface ResearchActivity { days:ActivityDay[]; total:number; active_days_30:number; streak:number }
export interface Paper {
  id: string; title: string; abstract: string | null; year: number | null; venue: string | null
  doi: string | null; arxiv_id: string | null; arxiv_version?: number | null; reading_status: ReadingStatus; is_favorite: boolean
  analysis_status: string; tags: string[]; authors: string[]; collection_ids: string[]
  page_count: number; is_demo: boolean; pdf_available: boolean; pdf_path?: string | null
  source_url?: string | null; metadata_sources?: Record<string,string>; metadata_warnings?: string[]
  intelligence_status?: IntelligenceStatus; intelligence_report?: IntelligenceReport | null
  intelligence_task?: IntelligenceTask | null; intelligence_analyzed_at?: string | null
  knowledge_status?: 'unread'|'candidates'|'partially_settled'|'settled'|'needs_review'
}
export interface PaperMetadataUpdate {
  title?: string; authors?: string[]; year?: number | null; venue?: string | null
  doi?: string | null; arxiv_id?: string | null
}
export type KnowledgePaperSummary = Pick<Paper,'id'|'title'|'abstract'|'year'|'venue'|'arxiv_id'|'source_url'|'authors'|'is_demo'|'analysis_status'|'intelligence_status'> & {
  analysis: Pick<Analysis,'problem'|'method'|'findings'|'limitations'|'concepts'|'provider'|'mode'> | null
}
export interface Collection { id: string; name: string; description: string | null; color: string; paper_count: number }
export interface ResearchSettings { enabled:boolean; profile_id:string|null; idle_seconds:number; start_remaining:number; stop_remaining:number; long_reserve:number; investigations_enabled?:boolean; maintenance_enabled:boolean; maintenance_interval_minutes:number; maintenance_calls_per_run:number; maintenance_scope:'library'|'enabled_collections' }
export interface ResearchTask { id:string; collection_id:string; kind:'essay'|'findings'|'agenda'|'investigation'; status:string; stage:string; calls:number; error:string|null; created_at:string; updated_at:string; usage:Record<string,unknown> }
export interface EssaySource { id:string; paper_id:string; title:string; chunk_id:string; page:number|null; section:string|null; text:string; quote:string; claim:string }
export interface EssayRevision { id:string; number:number; title:string; dek:string; changes:string; model:string; created_at:string; markdown?:string; sources?:EssaySource[]; coverage?:Array<{paper_id:string;title:string;total_chars:number;included_chars:number;chunks:number}> }
export type ResearchWorkType = 'essay'|'connections'|'gaps'|'review'|'questions'|'reading'
export interface ResearchScope {enabled:boolean;focus:string;work_types:ResearchWorkType[]}
export interface CollectionResearchState { scope:ResearchScope; revision:EssayRevision|null; revisions:EssayRevision[]; task:ResearchTask|null }
export type FindingKind = 'connection'|'gap'|'review'|'question'|'reading'
export type FindingAction = 'keep'|'dismiss'|'restore'|'done'|'again'|'remembered'
export interface FindingContent {kind:FindingKind;title:string;body:string;next_step:string;sources:EssaySource[];model:string}
export interface ResearchFinding extends FindingContent {id:string;collection_id:string;status:'unread'|'kept'|'dismissed'|'done';review_count:number;due_at:string|null;created_at:string;updated_at:string}
export interface ReadingOrigin {kind:'note'|'chat';id:string;paper_id:string;question?:string;page:number|null;chunk_id?:string|null;selected_text?:string|null}
export interface ResearchInvestigation extends Omit<ResearchTask,'kind'> {kind:FindingKind;title:string;question:string;rationale:string;paper_ids:string[];section_hints:string[];existing_id:string|null;outcome_ids:string[];origin?:ReadingOrigin|null}
export interface ResearchAgendaState {planner:ResearchTask|null;tasks:ResearchInvestigation[]}
export interface ResearchFindingsState {scope:ResearchScope;items:ResearchFinding[];task:ResearchTask|null;due_count:number;agenda?:ResearchAgendaState}
export interface FindingRevision extends FindingContent {id:string;created_at:string}
export type MaintenanceScope =
  | {scope_type:'library';scope_id?:never;paper_ids?:never}
  | {scope_type:'collection';scope_id:string;paper_ids?:never}
  | {scope_type:'papers';scope_id?:never;paper_ids:string[]}
export type MaintenanceRunInput = MaintenanceScope & {allow_external?:boolean;force?:boolean}
export interface MaintenanceRun { id:string; scope_type:'library'|'collection'|'papers'; scope_id:string|null; status:'queued'|'running'|'complete'|'partial'|'failed'|'cancelled'; allow_external:boolean; model_name:string|null; prompt_version:string|null; source_fingerprint:string; started_at:string|null; finished_at:string|null; error_message:string|null; safe_count:number; review_count:number; conflict_count:number; applied_count:number; usage:Record<string,unknown> }
export type MaintenanceIssueStatus = 'proposed'|'auto_applied'|'needs_review'|'accepted'|'rejected'|'stale'|'undone'
export interface MaintenanceIssue { id:string; run_id:string; kind:'identity'|'relation'|'evidence'|'coverage'|'importance'|'structure'; severity:'critical'|'warning'|'info'; status:MaintenanceIssueStatus; confidence:number; confidence_basis:Record<string,unknown>; auto_eligible:boolean; subject_ids:string[]; evidence:KnowledgeEvidence[]; external_leads:Record<string,unknown>[]; summary:string; reasoning:string; proposed_action:Record<string,unknown>; source_fingerprint:string; applied_change_ids:string[]; created_at:string; updated_at:string }
export interface MaintenanceRunDetail extends MaintenanceRun { issues:MaintenanceIssue[] }
export interface MaintenanceTaskSummary {
  id:string;scope_type:MaintenanceRun['scope_type'];scope_id:string|null;scope_title:string|null;status:MaintenanceRun['status']
  paper_count:number;total:number;completed:number;pending:number;failed:number;reason:string|null
  active_paper_id:string|null;active_paper_title:string|null;error:string|null;model_name:string|null
  active_papers?:Array<{id:string;title:string|null}>
}
export interface MaintenanceBacklog {pending_papers:number;review_papers:number;checked_papers:number;pending_objects:number;pending_relations:number;items:Array<{paper_id:string;title:string;status:'running'|'queued'|'retry_wait'|'failed'|'untracked'|'needs_review';run_id:string|null;pending_objects:number;pending_relations:number;error:string|null}>}
export interface ResearchStatus { scheduler?:{official:{configured:number;effective:number;active:number;waiting:number};active:number;waiting:number}; settings:ResearchSettings; reason:string; quota:Array<{name:string;used_percent:number|null;window_minutes:number|null;resets_at:number|null;limit_id?:string}>; quota_checked_at:number|null; quota_attempted_at?:number|null; quota_using_recent?:boolean; quota_error_code?:string|null; tasks:ResearchTask[]; scope_ids:string[]; maintenance:MaintenanceRun|null;translation_jobs?:TranslationJobSummary[];analysis_tasks?:AnalysisTaskSummary[];maintenance_tasks?:MaintenanceTaskSummary[] }
export interface Chunk {
  id: string; page: number; section: string | null; content: string; bbox: number[] | null
  page_width: number | null; page_height: number | null
}
export interface Evidence {
  id: string; claim: string; source_text: string; page: number | null; section: string | null
  confidence: number; source_type: string; source_url?: string | null; chunk_id?: string | null; bbox?: number[] | null
  page_width?: number | null; page_height?: number | null
}
export type NoteKind = 'note' | 'idea' | 'question' | 'todo' | 'highlight'
export interface NoteAnchor { page:number; bbox:number[]; page_width?:number|null; page_height?:number|null; rects:number[][] }
export interface Note { id: string; content: string; page: number | null; kind: NoteKind; source_text: string | null; bbox: number[] | null; anchors?:NoteAnchor[]; created_at: string; updated_at?:string }
export interface NoteInput {content:string;kind:NoteKind;page?:number|null;source_text?:string|null;bbox?:number[]|null;anchors?:NoteAnchor[]}
export interface Analysis {
  one_liner: string | null; problem: string | null; method: string | null; findings: string | null
  limitations: string | null; concepts: string[]; provider?: string; mode?: string
  card?: PaperCard
  model_version?:string|null; prompt_version?:string|null
}
export interface Translation { id:string;chunk_id:string;text:string;source_text:string;provider:string;mode:string;model_version:string|null;prompt_version:string;created_at:string }
export interface ReadingAnchor { chunk_id:string;page:number;bbox:number[]|null;page_width:number|null;page_height:number|null }
export interface ReadingParagraph { id:string;text:string;source_text:string;section:string|null;kind:'prose'|'caption';anchors:ReadingAnchor[];review_needed?:boolean;review_available?:boolean;review_uncertain?:boolean }
export interface PdfVisualRegion { id:string;page:number;kind:'figure'|'table'|'equation';label:string;caption:string;bbox:number[];page_width:number;page_height:number }
export interface ReadingTranslation { text:string;model?:string|null }
export interface TranslationQueueItem { id:string;paragraph_id:string;original_paragraph_id:string;aliases:string[];status:'queued'|'running'|'completed'|'failed'|'cancelled';phase:string|null;error:string|null;page:number|null;translation?:ReadingTranslation|null }
export interface TranslationJob { id:string;paper_id:string;mode:'selected'|'full';status:'queued'|'running'|'paused'|'completed'|'cancelled'|'failed';reason:string|null;error:string|null;model_name:string|null;completed:number;total:number;failed:number;items:TranslationQueueItem[];created_at:string;updated_at:string;scope_total?:number;scope_skipped?:number;scope_reason?:string|null }
export type TranslationJobAction = 'pause'|'resume'|'cancel'|'retry'
export interface TranslationJobSummary extends Omit<TranslationJob,'items'> {paper_title:string;in_flight:boolean}
export interface TranslationQueueEntry extends TranslationQueueItem { job_id:string;job_status:TranslationJob['status'] }
export interface QuickDefinition { part_of_speech:string|null; text:string; example:string|null }
export interface QuickTranslation { query:string; normalized_query:string; translation:string|null; phonetic:string|null; definitions:QuickDefinition[]; source:'youdao'|'dictionaryapi'; cached:boolean }
export interface ReadingDocument { paragraphs:ReadingParagraph[];translations:Record<string,ReadingTranslation>;translation_errors?:Record<string,string> }
export interface ParagraphReview extends ReadingDocument { selected_paragraph_id:string|null;paragraph_redirects:Record<string,string>;review:{checked:number;merged:number;uncertain:number;cached:boolean;model?:string} }
export interface CardItem { content: string; evidence_ids: string[]; section?: string | null }
export type CardField = 'one_sentence_summary'|'problem'|'motivation'|'background'|'core_idea'|'method'|'main_results'|'limitations'|'contributions'|'datasets'|'metrics'|'baselines'|'ablation_findings'|'future_work'|'claims'|'related_methods'|'prerequisite_concepts'|'abstract_zh'|'abstract_en'|'tldr'|'section_summaries'
export type PaperCard = Partial<Record<CardField, CardItem | CardItem[] | null>> & {title?:string}
export interface PaperDetail extends Paper {
  created_at: string; updated_at: string; analysis: Analysis | null; chunks: Chunk[]; notes: Note[]; evidence: Evidence[]
  translations?:Translation[]
  knowledge_candidates?: KnowledgeCandidate[]
  knowledge_relations?: KnowledgeRelation[]
}
export interface KnowledgeEvidence { paper_id?:string|null; paper_title?:string|null; chunk_id:string; page:number|null; section:string|null; quote:string; bbox:number[]|null; page_width:number|null; page_height:number|null }
export type KnowledgeEntityType = 'paper'|'method'|'dataset'|'benchmark'|'task'|'metric'|'concept'|'venue'
export type KnowledgeCandidateStatus = 'candidate'|'confirmed'|'rejected'|'conflict'|'unresolved'|'new'|'known'|'alias'
export type KnowledgePresentationLayer = 'primary'|'baseline'|'ablation'|'component'|'evaluation'|'comparison'
export type KnowledgeImportance = 'core'|'supporting'|'context'
export type KnowledgeRelationFamily = 'lineage'|'comparison'|'ablation'|'evaluation'|'dependency'
export interface KnowledgeCandidate { id:string; paper_id:string; entity_id:string|null; extracted_name?:string; entity_type:KnowledgeEntityType; name:string; normalized_name:string; aliases:string[]; description:string|null; role:string; confidence:number; status:KnowledgeCandidateStatus; evidence:KnowledgeEvidence[]; conflict:Record<string,unknown>; run_id:string|null; model_version:string|null; prompt_version:string|null; layer?:KnowledgePresentationLayer; importance?:KnowledgeImportance }
export interface KnowledgeRelation { id:string; paper_id:string; relation:string; source_name:string; source_normalized_name:string; target_name:string; target_normalized_name:string; source_candidate_id:string|null; target_candidate_id:string|null; source_entity_id?:string|null; target_entity_id?:string|null; description:string|null; confidence:number; status:KnowledgeCandidateStatus; evidence:KnowledgeEvidence[]; conflict:Record<string,unknown>; run_id:string|null; model_version:string|null; prompt_version:string|null; family?:KnowledgeRelationFamily; importance?:KnowledgeImportance }
export interface KnowledgePaper { paper_id:string; paper_status:'unread'|'candidates'|'partially_settled'|'settled'|'needs_review'; candidates:KnowledgeCandidate[]; relations:KnowledgeRelation[]; counts:Record<string,number> }
export type KnowledgeAuditState = 'confirmed'|'candidate'|'ignored'|'missing'
export interface KnowledgeAuditItem { name:string; state:KnowledgeAuditState; candidate_id:string|null; evidence_count:number; why:string; entity_type?:KnowledgeEntityType }
export interface KnowledgeAuditSuggestion { name:string; entity_type:KnowledgeEntityType; why:string; evidence:KnowledgeEvidence[] }
export interface KnowledgeAudit { paper_id:string; coverage:Record<string,Record<string,KnowledgeAuditItem>>; suggestions:KnowledgeAuditSuggestion[] }
export interface KnowledgeEntityLink { kind:'official'|'repository'|'paper'|'search'|'github'|'dataset'; label:string; url:string; source:string }
export interface KnowledgeEntityPaper { paper_id:string; title:string; role:string; status:KnowledgeCandidateStatus; evidence_count:number }
export interface KnowledgeEntityIndexItem { id:string; entity_type:KnowledgeEntityType; name:string; normalized_name:string; aliases:string[]; description:string|null; status:string; paper_count?:number; relation_count?:number; contextual_paper_count?:number; context_only?:boolean; context_summary?:string|null }
export interface KnowledgeChange { id:string; action:string; subject_type:string; subject_id:string; before:Record<string,unknown>; after:Record<string,unknown>; created_at:string }
export interface KnowledgeEntityDetail extends KnowledgeEntityIndexItem { candidates?:KnowledgeCandidate[]; papers:KnowledgeEntityPaper[]; relations:KnowledgeRelation[]; evidence:KnowledgeEvidence[]; links:KnowledgeEntityLink[]; history?:KnowledgeChange[] }
export interface KnowledgeEntityInput { name:string; entity_type:KnowledgeEntityType; aliases:string[]; description:string|null; links:Array<{kind:'official'|'repository'|'paper'|'dataset';label:string;url:string}> }
export interface KnowledgeMergePreview { source_id:string; source_name:string; source_description?:string|null; target_id:string; target_name:string; target_description?:string|null; candidate_count:number; paper_count:number; relation_count:number; aliases:string[]; relations_to_review?:Array<{id:string;paper_id:string;relation:string;description:string|null}> }
export interface KnowledgeRelationInput { source_candidate_id:string; target_candidate_id:string; relation:string; description:string|null }
export interface SavedChatResponse { conversation_id?:string;turn_id?:string }
export interface Answer extends SavedChatResponse { answer: string; provider: string; mode: string; citations: Evidence[]; insufficient_evidence: boolean; context_scope?: 'selection'|'paragraph'|'section'|'related'|'full'|'paper'|'external'; external_sources?: boolean; visual_used?: boolean; facts?: string[]; inferences?: string[]; unknowns?: string[]; needs_more_context?: boolean }
export type ExplainStyle = 'technical'|'simple'|'mathematical'|'prerequisites'
export interface Graph {
  nodes: { id: string; label: string; year: number | null; authors: string[] }[]
  edges: {id: string; source: string; target: string; relation: string; description?: string; relation_source?: string; reference_label?:string|null; evidence?:{chunk_id:string;page:number|null;quote:string}[] }[]
}
export interface SearchHit { paper_id: string; title: string; chunk_id: string; page: number; section: string | null; content: string; match_type: string }
export interface ModelSettings { provider: string; mode: string; configured: boolean; translation_available: boolean; model?:string|null; base_url?:string|null; api_key_configured?:boolean; configuration_error?:string|null; wire_api?:string|null; reasoning_effort?:string|null; intelligence_available?:boolean; quality?:Record<string,unknown> }
export interface ModelProfile {
  provider_kind?:'api'|'codex'
  id:string; name:string; base_url:string; model:string; api_key_configured:boolean
  wire_api:'chat_completions'|'responses'; reasoning_effort:'disabled'|'none'|'minimal'|'low'|'medium'|'high'|'xhigh'|'max'|'ultra'
  timeout:number; max_concurrency:number; completion_parameter:'max_tokens'|'max_completion_tokens'; json_mode:'json_object'|'none'
}
export interface ModelRouting { active_id:string|null; fallback_ids:string[]; auto_fallback:boolean }
export interface ModelProfiles extends ModelRouting { profiles:ModelProfile[]; configuration_error?:string; codex_max_concurrency?:number }
export type ModelProfileInput = Omit<ModelProfile,'id'|'api_key_configured'> & { api_key:string|null; test_connection:boolean }
export interface CodexAccountStatus {
  available:boolean; authenticated:boolean; pending:boolean; email:string|null; plan:string|null
  login_url:string|null; error?:string|null; error_code?:string; retryable?:boolean; limits_error?:string; limits_error_code?:string; limits_retryable?:boolean
  limits:{name:string;used_percent:number|null;window_minutes:number|null;resets_at:number|null;limit_id?:string}[]
}
export interface CodexModel {
  id:string;model:string;display_name:string;description:string;is_default:boolean
  default_reasoning_effort:Exclude<ModelProfile['reasoning_effort'],'disabled'>|null
  supported_reasoning_efforts:{effort:Exclude<ModelProfile['reasoning_effort'],'disabled'>;description:string}[]
}
export interface CodexModels {models:CodexModel[];default_model:string|null}
export type IntelligenceStatus = 'unanalyzed'|'queued'|'running'|'completed'|'partial'|'failed'|'cancelled'
export interface Usage { input_tokens?:number|null; output_tokens?:number|null; total_tokens?:number|null; model_calls?:number; remote_calls?:number; cache_hits?:number;unknown_usage_calls?:number; calls?:{cached:boolean;model:string;provider?:{profile_id?:string;profile_name?:string;failure?:{code:string}}}[] }
export interface IntelligenceReport { coverage?:Record<string,unknown>; usage?:Usage; [key:string]:unknown }
export interface IntelligenceTask { id:string;paper_id:string;status:Exclude<IntelligenceStatus,'unanalyzed'>;phase:string;completed_steps:number;total_steps:number;report:IntelligenceReport;error:string|null;created_at?:string;updated_at?:string }
export type AnalysisTaskSummary = Omit<IntelligenceTask,'report'> & {paper_title:string}
export interface LibraryCitation { id:string;paper_id:string;title:string;source_id:string;source_text:string;source_type:'paper'|'external_metadata'|'user'|'ai';page?:number|null;section?:string|null;chunk_id?:string|null;bbox?:number[]|null;page_width?:number|null;page_height?:number|null }
export interface LibraryClaim { content:string;kind:'fact'|'comparison'|'inference'|'background'|'user_note'|'metadata';citations:LibraryCitation[] }
export interface LibraryAnswer extends SavedChatResponse { answer:string;items:LibraryClaim[];citations:LibraryCitation[];provider:string;mode:string;model?:string|null;insufficient_evidence:boolean;limitations:string[];retrieved_paper_ids:string[];queries:string[];coverage:Record<string,unknown>;usage:Usage;cached:boolean }
export interface HistoryItem { role:'user'|'assistant';content:string }
export type ChatKind = 'paper'|'explanation'|'librarian'
export interface ChatIdentity { conversation_id?:string;request_id?:string }
export interface SavedConversation { id:string;kind:ChatKind;paper_id:string|null;context:Record<string,unknown>;title:string;created_at:string;updated_at:string;turn_count:number;latest_status?:SavedTurn<unknown>['status']|null;latest_question?:string;latest_turn_id?:string|null }
export interface SavedTurn<R> { id:string;question:string;status:'running'|'completed'|'failed'|'interrupted';response:R|null;error:string|null;created_at:string }
export interface ConversationRead<R> extends SavedConversation { turns:SavedTurn<R>[] }
export interface LibrarianTurn { id:string;question:string;response:LibraryAnswer }
export interface LibrarianThread { scope:string;selectedIds:string[];turns:LibrarianTurn[] }
