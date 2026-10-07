export type Page = 'library' | 'reader' | 'knowledge' | 'researchers' | 'settings'
export type ReadingStatus = 'unread' | 'skimming' | 'reading' | 'read' | 'important'
export interface Paper {
  id: string; title: string; abstract: string | null; year: number | null; venue: string | null
  doi: string | null; arxiv_id: string | null; arxiv_version?: number | null; reading_status: ReadingStatus; is_favorite: boolean
  analysis_status: string; tags: string[]; authors: string[]; collection_ids: string[]
  page_count: number; is_demo: boolean; pdf_available: boolean; pdf_path?: string | null
  source_url?: string | null; metadata_sources?: Record<string,string>; metadata_warnings?: string[]
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
export interface Note { id: string; content: string; page: number | null; kind: NoteKind; source_text: string | null; bbox: number[] | null; created_at: string }
export interface Analysis {
  one_liner: string | null; problem: string | null; method: string | null; findings: string | null
  limitations: string | null; concepts: string[]; provider?: string; mode?: string
  card?: PaperCard
  model_version?:string|null; prompt_version?:string|null
}
export interface Translation { id:string;chunk_id:string;text:string;source_text:string;provider:string;mode:string;model_version:string|null;prompt_version:string;created_at:string }
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
export interface ModelSettings { provider: string; mode: string; configured: boolean; translation_available: boolean; model?:string|null; configuration_error?:string|null }
