export type Page = 'library' | 'reader' | 'knowledge' | 'researchers' | 'settings' | 'librarian'
export type NotebookTab = 'overview' | 'evidence' | 'ask' | 'notes'
export type ReadingStatus = 'unread' | 'skimming' | 'reading' | 'read' | 'important'
export interface Paper {
  id: string; title: string; abstract: string | null; year: number | null; venue: string | null
  doi: string | null; arxiv_id: string | null; arxiv_version?: number | null; reading_status: ReadingStatus; is_favorite: boolean
  analysis_status: string; tags: string[]; authors: string[]; collection_ids: string[]
  page_count: number; is_demo: boolean; pdf_available: boolean; pdf_path?: string | null
  source_url?: string | null; metadata_sources?: Record<string,string>; metadata_warnings?: string[]
  intelligence_status?: IntelligenceStatus; intelligence_report?: IntelligenceReport | null
  intelligence_task?: IntelligenceTask | null; intelligence_analyzed_at?: string | null
}
export interface PaperMetadataUpdate {
  title?: string; authors?: string[]; year?: number | null; venue?: string | null
  doi?: string | null; arxiv_id?: string | null
}
export interface Collection { id: string; name: string; description: string | null; color: string; paper_count: number }
export interface Chunk {
  id: string; page: number; section: string | null; content: string; bbox: number[] | null
  page_width: number | null; page_height: number | null
}
export interface Evidence {
  id: string; claim: string; source_text: string; page: number | null; section: string | null
  confidence: number; source_type: string; chunk_id?: string | null; bbox?: number[] | null
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
export interface ReadingParagraph { id:string;text:string;source_text:string;section:string|null;kind:'prose'|'caption';anchors:ReadingAnchor[] }
export interface ReadingTranslation { text:string;model?:string|null }
export interface ReadingDocument { paragraphs:ReadingParagraph[];translations:Record<string,ReadingTranslation> }
export interface CardItem { content: string; evidence_ids: string[]; section?: string | null }
export type CardField = 'one_sentence_summary'|'problem'|'motivation'|'background'|'core_idea'|'method'|'main_results'|'limitations'|'contributions'|'datasets'|'metrics'|'baselines'|'ablation_findings'|'future_work'|'claims'|'related_methods'|'prerequisite_concepts'|'abstract_zh'|'abstract_en'|'tldr'|'section_summaries'
export type PaperCard = Partial<Record<CardField, CardItem | CardItem[] | null>> & {title?:string}
export interface PaperDetail extends Paper {
  created_at: string; updated_at: string; analysis: Analysis | null; chunks: Chunk[]; notes: Note[]; evidence: Evidence[]
  translations?:Translation[]
}
export interface Answer { answer: string; provider: string; mode: string; citations: Evidence[]; insufficient_evidence: boolean }
export type ExplainStyle = 'technical'|'simple'|'mathematical'|'prerequisites'
export interface Graph {
  nodes: { id: string; label: string; year: number | null; authors: string[] }[]
  edges: {id: string; source: string; target: string; relation: string; description?: string; relation_source?: string }[]
}
export interface SearchHit { paper_id: string; title: string; chunk_id: string; page: number; section: string | null; content: string; match_type: string }
export interface ModelSettings { provider: string; mode: string; configured: boolean; translation_available: boolean; model?:string|null; base_url?:string|null; api_key_configured?:boolean; configuration_error?:string|null; wire_api?:string|null; reasoning_effort?:string|null; intelligence_available?:boolean; quality?:Record<string,unknown> }
export interface ModelProfile {
  provider_kind?:'api'|'codex'
  id:string; name:string; base_url:string; model:string; api_key_configured:boolean
  wire_api:'chat_completions'|'responses'; reasoning_effort:'disabled'|'none'|'minimal'|'low'|'medium'|'high'|'xhigh'
  timeout:number; max_concurrency:number; completion_parameter:'max_tokens'|'max_completion_tokens'; json_mode:'json_object'|'none'
}
export interface ModelRouting { active_id:string|null; fallback_ids:string[]; auto_fallback:boolean }
export interface ModelProfiles extends ModelRouting { profiles:ModelProfile[]; configuration_error?:string }
export type ModelProfileInput = Omit<ModelProfile,'id'|'api_key_configured'> & { api_key:string|null; test_connection:boolean }
export interface CodexAccountStatus {
  available:boolean; authenticated:boolean; pending:boolean; email:string|null; plan:string|null
  login_url:string|null; error?:string|null; error_code?:string; retryable?:boolean; limits_error?:string
  limits:{name:string;used_percent:number;window_minutes:number|null;resets_at:number|null}[]
}
export type IntelligenceStatus = 'unanalyzed'|'queued'|'running'|'completed'|'partial'|'failed'|'cancelled'
export interface Usage { input_tokens?:number|null; output_tokens?:number|null; total_tokens?:number|null; model_calls?:number; remote_calls?:number; cache_hits?:number;unknown_usage_calls?:number; calls?:{cached:boolean;model:string;provider?:{profile_id?:string;profile_name?:string;failure?:{code:string}}}[] }
export interface IntelligenceReport { coverage?:Record<string,unknown>; usage?:Usage; [key:string]:unknown }
export interface IntelligenceTask { id:string;paper_id:string;status:Exclude<IntelligenceStatus,'unanalyzed'>;phase:string;completed_steps:number;total_steps:number;report:IntelligenceReport;error:string|null;created_at?:string;updated_at?:string }
export interface LibraryCitation { id:string;paper_id:string;title:string;source_id:string;source_text:string;source_type:'paper'|'external_metadata'|'user'|'ai';page?:number|null;section?:string|null;chunk_id?:string|null;bbox?:number[]|null;page_width?:number|null;page_height?:number|null }
export interface LibraryClaim { content:string;kind:'fact'|'comparison'|'inference'|'user_note'|'metadata';citations:LibraryCitation[] }
export interface LibraryAnswer { answer:string;items:LibraryClaim[];citations:LibraryCitation[];provider:string;mode:string;model?:string|null;insufficient_evidence:boolean;limitations:string[];retrieved_paper_ids:string[];queries:string[];coverage:Record<string,unknown>;usage:Usage;cached:boolean }
export interface HistoryItem { role:'user'|'assistant';content:string }
export interface LibrarianTurn { id:string;question:string;response:LibraryAnswer }
export interface LibrarianThread { scope:string;selectedIds:string[];turns:LibrarianTurn[] }
