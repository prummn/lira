"""Validated API contracts; geometry always belongs to original PDF coordinates."""

from __future__ import annotations
from datetime import datetime
from typing import Literal
import math
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .services.downloads import normalize_arxiv_id
from .services.metadata import normalize_doi

BBox = tuple[float, float, float, float]
ReadingStatus = Literal["unread", "skimming", "reading", "read", "important"]
NoteKind = Literal["note", "idea", "question", "todo", "highlight"]


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


class NoteCreate(GeometryModel):
    content: str = Field(min_length=1, max_length=100000)
    page: int | None = Field(default=None, ge=1)
    kind: NoteKind = "note"
    source_text: str | None = None

    @field_validator("content")
    @classmethod
    def nonempty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()


class NoteRead(NoteCreate):
    id: str
    created_at: datetime


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


class PaperSummary(BaseModel):
    id: str
    title: str
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    source_url: str | None = None
    metadata_sources: dict[str, str] = Field(default_factory=dict)
    metadata_warnings: list[str] = Field(default_factory=list)
    pdf_path: str | None = None
    reading_status: str
    is_favorite: bool
    analysis_status: str
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


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)

    @field_validator("question")
    @classmethod
    def valid_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()


class AskResponse(BaseModel):
    answer: str
    provider: str
    mode: str
    citations: list[EvidenceRead]
    insufficient_evidence: bool


class TranslateRequest(BaseModel):
    chunk_id: str = Field(min_length=1)
    force: bool = False


class ExplainRequest(BaseModel):
    chunk_id: str = Field(min_length=1)
    selected_text: str = Field(min_length=1,max_length=12000)
    style: Literal['technical','simple','mathematical','prerequisites'] = 'technical'
    @field_validator('selected_text')
    @classmethod
    def nonempty_selection(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('请先选择原文片段')
        return value
