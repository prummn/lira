"""Validated API contracts; geometry always belongs to original PDF coordinates."""

from __future__ import annotations
from datetime import date, datetime
from typing import Literal
import math
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .conversation_schemas import ChatRequest, ChatResponse
from .services.downloads import normalize_arxiv_id
from .services.metadata import normalize_doi

BBox = tuple[float, float, float, float]
ReadingStatus = Literal["unread", "skimming", "reading", "read", "important"]
NoteKind = Literal["note", "idea", "question", "todo", "highlight"]
IntelligenceStatus = Literal['unanalyzed', 'queued', 'running', 'completed', 'partial', 'failed', 'cancelled']
ActivityKind = Literal['reading', 'notes', 'language', 'search', 'imports']
KnowledgeEntityType = Literal['paper', 'method', 'dataset', 'benchmark', 'task', 'metric', 'concept', 'venue']
KnowledgeCandidateStatus = Literal['candidate', 'confirmed', 'rejected', 'conflict', 'unresolved', 'new', 'known', 'alias']
KnowledgeEntityStatus = Literal['active', 'needs_review', 'unsupported']
KnowledgeRelationKind = Literal['builds_on', 'extends', 'compares_with', 'replaces', 'uses_dataset', 'evaluated_on', 'inspired_by', 'contrasts_with', 'requires_concept']
KnowledgePresentationLayer = Literal['primary', 'baseline', 'ablation', 'component', 'evaluation', 'comparison']
KnowledgeImportance = Literal['core', 'supporting', 'context']
KnowledgeRelationFamily = Literal['lineage', 'comparison', 'ablation', 'evaluation', 'dependency']


class ActivityCreate(BaseModel):
    kind: ActivityKind
    paper_id: str | None = Field(default=None, min_length=1, max_length=64)


class ActivityDayRead(BaseModel):
    date: date
    reading: int
    notes: int
    language: int
    search: int
    imports: int
    total: int
    paper_ids: list[str] = Field(default_factory=list)


class ActivityRead(BaseModel):
    days: list[ActivityDayRead]
    total: int
    active_days_30: int
    streak: int


class KnowledgeEvidence(BaseModel):
    paper_id: str | None = None
    paper_title: str | None = None
    chunk_id: str = Field(min_length=1, max_length=64)
    page: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=100)
    quote: str = Field(min_length=1, max_length=4000)
    bbox: BBox | None = None
    page_width: float | None = Field(default=None, gt=0)
    page_height: float | None = Field(default=None, gt=0)


class KnowledgeCandidateRead(BaseModel):
    id: str
    paper_id: str
    entity_id: str | None = None
    extracted_name: str | None = None
    entity_type: KnowledgeEntityType
    name: str
    normalized_name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    role: Literal['proposed', 'used', 'baseline', 'ablation', 'component', 'cited', 'compared'] = 'cited'
    confidence: float = Field(ge=0, le=1)
    status: KnowledgeCandidateStatus
    evidence: list[KnowledgeEvidence] = Field(min_length=1)
    conflict: dict = Field(default_factory=dict)
    run_id: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    layer: KnowledgePresentationLayer = 'comparison'
    importance: KnowledgeImportance = 'supporting'


class KnowledgeRelationRead(BaseModel):
    id: str
    paper_id: str
    relation: KnowledgeRelationKind
    source_name: str
    source_normalized_name: str
    target_name: str
    target_normalized_name: str
    source_candidate_id: str | None = None
    target_candidate_id: str | None = None
    source_entity_id: str | None = None
    target_entity_id: str | None = None
    description: str | None = None
    confidence: float = Field(ge=0, le=1)
    status: KnowledgeCandidateStatus
    evidence: list[KnowledgeEvidence] = Field(min_length=1)
    conflict: dict = Field(default_factory=dict)
    run_id: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    family: KnowledgeRelationFamily = 'comparison'
    importance: KnowledgeImportance = 'supporting'


class KnowledgePaperRead(BaseModel):
    paper_id: str
    paper_status: Literal['unread', 'candidates', 'partially_settled', 'settled', 'needs_review']
    candidates: list[KnowledgeCandidateRead] = Field(default_factory=list)
    relations: list[KnowledgeRelationRead] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class KnowledgeAuditRead(BaseModel):
    """Deterministic, source-grounded coverage projection for one paper."""

    paper_id: str
    coverage: dict[str, dict[str, dict]] = Field(default_factory=dict)
    suggestions: list[dict] = Field(default_factory=list)


class KnowledgeEntityPaperRead(BaseModel):
    paper_id: str
    title: str
    role: str = 'related'
    status: str = 'candidate'
    evidence_count: int = 0


class KnowledgeEntityLinkRead(BaseModel):
    kind: Literal['official', 'repository', 'paper', 'search', 'github', 'dataset']
    label: str
    url: str
    source: str = 'curated'


class KnowledgeEntityDetailRead(BaseModel):
    id: str
    entity_type: KnowledgeEntityType
    name: str
    normalized_name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    status: KnowledgeEntityStatus
    candidates: list[KnowledgeCandidateRead] = Field(default_factory=list)
    papers: list[KnowledgeEntityPaperRead] = Field(default_factory=list)
    relations: list[KnowledgeRelationRead] = Field(default_factory=list)
    evidence: list[KnowledgeEvidence] = Field(default_factory=list)
    links: list[KnowledgeEntityLinkRead] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)


class KnowledgeLinkInput(BaseModel):
    kind: Literal['official', 'repository', 'paper', 'dataset']
    label: str = Field(min_length=1, max_length=150)
    url: str = Field(min_length=1, max_length=2048)

    @field_validator('url')
    @classmethod
    def http_link(cls, value: str) -> str:
        from urllib.parse import urlsplit
        value = value.strip()
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('资料链接必须是有效的 http 或 https 地址')
        return value


class KnowledgeEntityUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    entity_type: KnowledgeEntityType
    aliases: list[str] = Field(default_factory=list, max_length=100)
    description: str | None = Field(default=None, max_length=12000)
    links: list[KnowledgeLinkInput] = Field(default_factory=list, max_length=30)

    @field_validator('name')
    @classmethod
    def meaningful_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('名称不能为空')
        return value.strip()


class KnowledgeEntityMerge(BaseModel):
    target_id: str = Field(min_length=1, max_length=64)


class KnowledgeRelationUpdate(BaseModel):
    source_candidate_id: str = Field(min_length=1, max_length=64)
    target_candidate_id: str = Field(min_length=1, max_length=64)
    relation: KnowledgeRelationKind
    description: str | None = Field(default=None, max_length=12000)


class KnowledgeRelationCreate(KnowledgeRelationUpdate):
    evidence: list[KnowledgeEvidence] = Field(min_length=1, max_length=12)


class KnowledgeRelationResolution(BaseModel):
    target_name: str = Field(min_length=1, max_length=300)
    target_type: KnowledgeEntityType

    @field_validator('target_name')
    @classmethod
    def clean_target_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('目标实体名称不能为空')
        return value


class CandidateDecision(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=8000)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None and value.strip() else value


class CandidateBatchDecision(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=64)
    decision: Literal['confirm', 'reject']


class ModelSettingsUpdate(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)
    wire_api: Literal['chat_completions', 'responses'] = 'chat_completions'
    reasoning_effort: Literal['disabled', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh'] = 'disabled'
    timeout: float = Field(default=600, ge=1, le=1800)
    test_connection: bool = True

    @field_validator('base_url', 'model', 'api_key')
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError('模型配置不能包含控制字符')
        return value


class ModelProfileUpdate(ModelSettingsUpdate):
    provider_kind: Literal['api', 'codex'] = 'api'
    reasoning_effort: Literal['disabled', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'] = 'disabled'
    name: str = Field(min_length=1, max_length=80)
    max_concurrency: int = Field(default=1, ge=1, le=16)
    completion_parameter: Literal['max_tokens', 'max_completion_tokens'] = 'max_completion_tokens'
    json_mode: Literal['json_object', 'none'] = 'json_object'

    @field_validator('name')
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('请输入有效的配置名称')
        return value.strip()


class ModelRoutingUpdate(BaseModel):
    active_id: str | None = None
    fallback_ids: list[str] = Field(default_factory=list, max_length=20)
    auto_fallback: bool = False


class CodexConcurrencyUpdate(BaseModel):
    max_concurrency: int = Field(ge=1, le=8)


class TaskRead(BaseModel):
    id: str
    paper_id: str
    status: Literal['queued', 'running', 'completed', 'partial', 'failed', 'cancelled']
    phase: str
    completed_steps: int
    total_steps: int
    report: dict = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class IntelligenceTaskCreate(BaseModel):
    paper_ids: list[str] = Field(min_length=1, max_length=200)
    force: bool = False

    @field_validator('paper_ids')
    @classmethod
    def unique_paper_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 64 for item in value):
            raise ValueError('论文 ID 无效')
        return list(dict.fromkeys(value))


class IntelligenceTaskList(BaseModel):
    tasks: list[TaskRead]


class GeometryModel(BaseModel):
    bbox: BBox | None = None

    @field_validator("bbox")
    @classmethod
    def valid_bbox(cls, value: BBox | None) -> BBox | None:
        if value and (
            not all(math.isfinite(c) and c >= 0 for c in value)
            or value[0] >= value[2]
            or value[1] >= value[3]
        ):
            raise ValueError(
                "bbox must contain nonnegative ordered finite coordinates [x0,y0,x1,y1]"
            )
        return value


class EvidenceRead(GeometryModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    claim: str
    source_text: str
    page: int | None = None
    section: str | None = None
    confidence: float
    source_type: str
    source_url: str | None = None
    chunk_id: str | None = None
    page_width: float | None = None
    page_height: float | None = None


class ChunkRead(GeometryModel):
    id: str
    page: int
    section: str | None = None
    content: str
    page_width: float | None = None
    page_height: float | None = None


class CardItem(BaseModel):
    content: str
    evidence_ids: list[str]


class SectionSummary(CardItem):
    section: str


class PaperCard(BaseModel):
    title: str = ''
    one_sentence_summary: CardItem | None = None
    problem: CardItem | None = None
    motivation: CardItem | None = None
    background: CardItem | None = None
    core_idea: CardItem | None = None
    method: CardItem | None = None
    main_results: CardItem | None = None
    limitations: CardItem | None = None
    contributions: list[CardItem] = Field(default_factory=list)
    datasets: list[CardItem] = Field(default_factory=list)
    metrics: list[CardItem] = Field(default_factory=list)
    baselines: list[CardItem] = Field(default_factory=list)
    ablation_findings: list[CardItem] = Field(default_factory=list)
    future_work: list[CardItem] = Field(default_factory=list)
    claims: list[CardItem] = Field(default_factory=list)
    related_methods: list[CardItem] = Field(default_factory=list)
    prerequisite_concepts: list[CardItem] = Field(default_factory=list)
    section_summaries: list[SectionSummary] = Field(default_factory=list)
    tldr: list[CardItem] = Field(default_factory=list)
    abstract_zh: CardItem | None = None
    abstract_en: CardItem | None = None


class AnalysisRead(BaseModel):
    one_liner: str | None = None
    problem: str | None = None
    method: str | None = None
    findings: str | None = None
    limitations: str | None = None
    concepts: list[str] = Field(default_factory=list)
    provider: str
    mode: str
    evidence_ids: list[str] = Field(default_factory=list)
    card: PaperCard = Field(default_factory=PaperCard)
    model_version: str | None = None
    prompt_version: str | None = None


class NoteAnchor(GeometryModel):
    page: int = Field(ge=1)
    bbox: BBox
    page_width: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    page_height: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    rects: list[BBox] = Field(default_factory=list, max_length=1000)

    @model_validator(mode='after')
    def valid_regions(self):
        x0, y0, x1, y1 = self.bbox
        if self.page_width is not None and x1 > self.page_width + .02 or self.page_height is not None and y1 > self.page_height + .02:
            raise ValueError('标记超出页面范围')
        for rect in self.rects:
            GeometryModel.valid_bbox(rect)
            if rect[0] < x0 - .02 or rect[1] < y0 - .02 or rect[2] > x1 + .02 or rect[3] > y1 + .02:
                raise ValueError('逐行标记必须位于选区范围内')
        return self


class NoteCreate(GeometryModel):
    content: str = Field(min_length=1, max_length=100000)
    page: int | None = Field(default=None, ge=1)
    kind: NoteKind = "note"
    source_text: str | None = None
    anchors: list[NoteAnchor] = Field(default_factory=list, max_length=64)

    @model_validator(mode='after')
    def consistent_anchors(self):
        if self.anchors:
            first = self.anchors[0]
            pages = [anchor.page for anchor in self.anchors]
            if pages != sorted(set(pages)):
                raise ValueError('引用页码必须递增且不重复')
            if self.page is not None and self.page != first.page or self.bbox is not None and self.bbox != first.bbox:
                raise ValueError('引用首页与定位信息不一致')
            self.page, self.bbox = first.page, first.bbox
        return self

    @field_validator("content")
    @classmethod
    def nonempty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()


class NoteRead(NoteCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class NoteUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str = Field(min_length=1, max_length=100000)
    kind: NoteKind = 'note'

    @field_validator('content')
    @classmethod
    def nonempty(cls, value):
        return NoteCreate.nonempty_content(value)


class TranslationRead(BaseModel):
    id: str
    chunk_id: str
    text: str
    source_text: str
    provider: str
    mode: str
    model_version: str | None = None
    prompt_version: str
    created_at: datetime


class TranslationResponse(TranslationRead):
    cached: bool
    paragraph_id: str | None = None


class PaperSummary(BaseModel):
    id: str
    title: str
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    arxiv_version: int | None = None
    source_url: str | None = None
    metadata_sources: dict[str, str] = Field(default_factory=dict)
    metadata_warnings: list[str] = Field(default_factory=list)
    pdf_path: str | None = None
    reading_status: str
    is_favorite: bool
    analysis_status: str
    intelligence_status: IntelligenceStatus = 'unanalyzed'
    intelligence_report: dict | None = None
    intelligence_task: TaskRead | None = None
    intelligence_analyzed_at: datetime | None = None
    knowledge_status: Literal['unread', 'candidates', 'partially_settled', 'settled', 'needs_review'] = 'unread'
    tags: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    collection_ids: list[str] = Field(default_factory=list)
    page_count: int = 0
    is_demo: bool = False
    pdf_available: bool = False


class PaperDetail(PaperSummary):
    created_at: datetime
    updated_at: datetime
    analysis: AnalysisRead | None = None
    evidence: list[EvidenceRead] = Field(default_factory=list)
    chunks: list[ChunkRead] = Field(default_factory=list)
    notes: list[NoteRead] = Field(default_factory=list)
    translations: list[TranslationRead] = Field(default_factory=list)
    knowledge_candidates: list[KnowledgeCandidateRead] = Field(default_factory=list)
    knowledge_relations: list[KnowledgeRelationRead] = Field(default_factory=list)


class PaperListResponse(BaseModel):
    items: list[PaperSummary]
    total: int
    limit: int
    offset: int


class PaperCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    abstract: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    reading_status: ReadingStatus = "unread"
    tags: list[str] = Field(default_factory=list)
    author_names: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("标题不能为空")
        return value.strip()


class PaperUpdate(BaseModel):
    reading_status: ReadingStatus | None = None
    is_favorite: bool | None = None
    tags: list[str] | None = None
    title: str | None = Field(default=None, max_length=500)
    authors: list[str] | None = Field(default=None, max_length=150)
    year: int | None = Field(default=None, ge=1900, le=2200)
    venue: str | None = Field(default=None, max_length=200)
    doi: str | None = Field(default=None, max_length=200)
    arxiv_id: str | None = Field(default=None, max_length=100)

    @field_validator('title')
    @classmethod
    def nonempty_title(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError('标题不能为空')
        return value.strip()

    @field_validator('authors')
    @classmethod
    def valid_authors(cls, value: list[str] | None) -> list[str]:
        if value is None or any(not name.strip() or len(name.strip()) > 200 for name in value):
            raise ValueError('作者姓名必须为 1 至 200 个字符；无作者时请传空数组')
        return list(dict.fromkeys(name.strip() for name in value))

    @field_validator('venue')
    @classmethod
    def clean_venue(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator('doi')
    @classmethod
    def valid_doi(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = normalize_doi(value)
        if normalized is None:
            raise ValueError('请输入有效 DOI，例如 10.1234/example')
        return normalized

    @field_validator('arxiv_id')
    @classmethod
    def valid_arxiv(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = normalize_arxiv_id(value)
        if normalized is None:
            raise ValueError('请输入有效 arXiv 编号或 abs/pdf 链接')
        return normalized


class URLImportRequest(BaseModel):
    analyze: bool = False
    url: str = Field(min_length=1, max_length=2048)

    @field_validator('url')
    @classmethod
    def clean_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('请输入论文链接')
        return value.strip()


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    color: str = Field(default="#5B6CFF", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("集合名称不能为空")
        return value.strip()


class CollectionPapersAdd(BaseModel):
    paper_ids: list[str] = Field(min_length=1, max_length=500)


class CollectionRead(BaseModel):
    id: str
    name: str
    description: str | None = None
    color: str
    paper_count: int = 0
    created_at: datetime
    updated_at: datetime


class CollectionListResponse(BaseModel):
    items: list[CollectionRead]
    total: int




class AskRequest(ChatRequest):
    question: str = Field(min_length=1, max_length=4000)

    @field_validator("question")
    @classmethod
    def valid_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()


class AskResponse(ChatResponse):
    answer: str
    provider: str
    mode: str
    citations: list[EvidenceRead]
    insufficient_evidence: bool
    context_scope: Literal['selection', 'paragraph', 'section', 'related', 'full', 'paper', 'external'] = 'paper'
    external_sources: bool = False
    visual_used: bool = False
    facts: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    needs_more_context: bool = False


class TranslateRequest(BaseModel):
    chunk_id: str | None = Field(default=None, min_length=1)
    paragraph_id: str | None = Field(default=None, min_length=1)
    force: bool = False


class ParagraphReviewRequest(BaseModel):
    paragraph_id: str = Field(min_length=1,max_length=100)


class QuickTranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=80)

    @field_validator('text')
    @classmethod
    def valid_short_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('请选择一个英文单词或短词')
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError('速译文本不能包含控制字符')
        return value


class QuickDefinitionRead(BaseModel):
    part_of_speech: str | None = None
    text: str
    example: str | None = None


class QuickTranslationResponse(BaseModel):
    query: str
    normalized_query: str
    translation: str | None = None
    phonetic: str | None = None
    definitions: list[QuickDefinitionRead] = Field(default_factory=list)
    source: str
    cached: bool


class ExplainRequest(ChatRequest):
    chunk_id: str | None = Field(default=None, min_length=1)
    selected_text: str | None = Field(default=None, max_length=12000)
    translated_text: str | None = Field(default=None, max_length=12000)
    page: int | None = Field(default=None, ge=1)
    bbox: BBox | None = None
    image_data_url: str | None = Field(default=None, max_length=8000000)
    visual_kind: Literal['figure','table','equation'] | None = None
    visual_label: str | None = Field(default=None, max_length=100)
    question: str | None = Field(default=None, max_length=4000)
    style: Literal['technical','simple','mathematical','prerequisites'] = 'technical'
    context_scope: Literal['auto','paragraph','section','full'] = 'auto'
    allow_external: bool = False
    history: list['ExplainTurn'] = Field(default_factory=list, max_length=8)
    @field_validator('selected_text')
    @classmethod
    def clean_selection(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator('translated_text')
    @classmethod
    def clean_translation_selection(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator('image_data_url')
    @classmethod
    def valid_image_data_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')):
            raise ValueError('图像必须是 PNG、JPEG 或 WebP 的 data URL')
        if len(value) > 8000000:
            raise ValueError('图像过大，请降低阅读器缩放后重试')
        return value

    @model_validator(mode='after')
    def require_context(self):
        if not self.selected_text and not self.image_data_url:
            raise ValueError('请先选择原文或已识别的图表')
        if self.image_data_url and self.page is None:
            raise ValueError('图表提问需要当前页码')
        if self.bbox is not None and not self.image_data_url:
            raise ValueError('图表区域需要对应的裁剪图像')
        # A detected figure/table may carry nearby extracted text without a
        # single canonical chunk id. The cropped image is the primary evidence
        # in that case, so do not reject the request when the region crosses
        # columns, captions, or layout fragments.
        if self.selected_text and not self.chunk_id and not self.image_data_url:
            raise ValueError('原文选段缺少来源')
        return self

    @field_validator('question')
    @classmethod
    def valid_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ExplainTurn(BaseModel):
    """A bounded prior turn used to make selection questions conversational."""

    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=16000)

    @field_validator('question', 'answer')
    @classmethod
    def trim_turn_text(cls, value: str) -> str:
        return value.strip()
