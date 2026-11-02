"""SQLAlchemy models for local-first paper intelligence data."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class shared by all ORM models."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PaperAuthor(Base):
    __tablename__ = "paper_authors"
    __table_args__ = (
        UniqueConstraint("paper_id", "author_id", name="uq_paper_author"),
    )

    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[str] = mapped_column(
        ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paper: Mapped["Paper"] = relationship(back_populates="author_links")
    author: Mapped["Author"] = relationship(back_populates="paper_links")


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    affiliation: Mapped[Optional[str]] = mapped_column(String(300))
    paper_links: Mapped[list[PaperAuthor]] = relationship(
        back_populates="author", cascade="all, delete-orphan"
    )


class Paper(Base, TimestampMixin):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    abstract: Mapped[Optional[str]] = mapped_column(Text)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    venue: Mapped[Optional[str]] = mapped_column(String(200))
    doi: Mapped[Optional[str]] = mapped_column(String(200), unique=True)
    arxiv_id: Mapped[Optional[str]] = mapped_column(String(100))
    arxiv_version: Mapped[Optional[int]] = mapped_column(Integer)
    source_url: Mapped[Optional[str]] = mapped_column(String(2048))
    metadata_sources_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    metadata_warnings_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(1000))
    reading_status: Mapped[str] = mapped_column(
        String(32), default="unread", nullable=False
    )
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    analysis_status: Mapped[str] = mapped_column(
        String(32), default="ready", nullable=False
    )
    intelligence_status: Mapped[str] = mapped_column(String(32), default="unanalyzed", nullable=False)
    intelligence_report_json: Mapped[Optional[str]] = mapped_column(Text)
    intelligence_analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    knowledge_status: Mapped[str] = mapped_column(String(32), default="unread", nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    author_links: Mapped[list[PaperAuthor]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        order_by="PaperAuthor.order_index",
    )
    collection_links: Mapped[list[CollectionPaper]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )
    chunks: Mapped[list[PaperChunk]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="PaperChunk.id"
    )
    analysis: Mapped[Optional[PaperAnalysis]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", uselist=False
    )
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )
    notes: Mapped[list[Note]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="Note.created_at"
    )
    translations: Mapped[list[Translation]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="Translation.created_at"
    )
    intelligence_tasks: Mapped[list[IntelligenceTask]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="IntelligenceTask.created_at"
    )
    knowledge_candidates: Mapped[list["KnowledgeCandidate"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="KnowledgeCandidate.created_at"
    )
    knowledge_relations: Mapped[list["KnowledgeRelation"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="KnowledgeRelation.created_at"
    )


class IntelligenceTask(Base, TimestampMixin):
    __tablename__ = "intelligence_tasks"
    __table_args__ = (Index("uq_intelligence_active_paper", "paper_id", unique=True, sqlite_where=text("status IN ('queued','running')")),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    phase: Mapped[str] = mapped_column(String(64), default="queued", nullable=False)
    run_token: Mapped[Optional[str]] = mapped_column(String(32))
    completed_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    paper: Mapped[Paper] = relationship(back_populates="intelligence_tasks")


class ModelCallCache(Base):
    __tablename__ = "model_call_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    usage_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class ChatConversation(Base, TimestampMixin):
    __tablename__ = 'chat_conversations'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    paper_id: Mapped[Optional[str]] = mapped_column(ForeignKey('papers.id', ondelete='CASCADE'), index=True)
    context_json: Mapped[str] = mapped_column(Text, default='{}', nullable=False)
    context_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), default='', nullable=False)


class ChatTurn(Base):
    __tablename__ = 'chat_turns'
    __table_args__ = (Index('uq_chat_running', 'conversation_id', unique=True, sqlite_where=text("status = 'running'")),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('chat_conversations.id', ondelete='CASCADE'), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default='running', nullable=False)
    response_json: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class ResearchActivity(Base):
    """One local aggregate row per calendar day of research activity."""

    __tablename__ = "research_activity"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    reading: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    language: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    search: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imports: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paper_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)


class CollectionPaper(Base):
    __tablename__ = "collection_papers"
    __table_args__ = (
        UniqueConstraint("collection_id", "paper_id", name="uq_collection_paper"),
    )

    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    collection: Mapped["Collection"] = relationship(back_populates="paper_links")
    paper: Mapped[Paper] = relationship(back_populates="collection_links")


class Collection(Base, TimestampMixin):
    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(32), default="#5B6CFF", nullable=False)
    paper_links: Mapped[list[CollectionPaper]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )


class ResearchControl(Base):
    __tablename__ = 'research_control'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    settings_json: Mapped[str] = mapped_column(Text, nullable=False)
    budget_json: Mapped[str] = mapped_column(Text, default='{}', server_default='{}', nullable=False)


class ResearchScope(Base, TimestampMixin):
    __tablename__ = 'research_scopes'
    collection_id: Mapped[str] = mapped_column(ForeignKey('collections.id', ondelete='CASCADE'), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    focus: Mapped[str] = mapped_column(Text, default='', nullable=False)
    work_types_json: Mapped[str] = mapped_column(Text, default='["essay"]', server_default='["essay"]', nullable=False)


class ResearchTask(Base, TimestampMixin):
    __tablename__ = 'research_tasks'
    __table_args__ = (UniqueConstraint('collection_id', 'fingerprint', name='uq_research_material'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(ForeignKey('collections.id', ondelete='CASCADE'), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), default='essay', server_default='essay', nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_key: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default='queued', nullable=False)
    stage: Mapped[str] = mapped_column(String(24), default='synthesis', nullable=False)
    material_json: Mapped[str] = mapped_column(Text, nullable=False)
    checkpoint_json: Mapped[str] = mapped_column(Text, default='{}', nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_json: Mapped[str] = mapped_column(Text, default='{}', nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)


class ResearchRevision(Base):
    __tablename__ = 'research_revisions'
    __table_args__ = (UniqueConstraint('collection_id', 'number', name='uq_research_revision'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(ForeignKey('collections.id', ondelete='CASCADE'), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('research_tasks.id', ondelete='CASCADE'), nullable=False, unique=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    dek: Mapped[str] = mapped_column(Text, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    changes: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_json: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class ResearchFinding(Base, TimestampMixin):
    __tablename__ = 'research_findings'
    __table_args__ = (UniqueConstraint('collection_id', 'identity', name='uq_research_finding_identity'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(ForeignKey('collections.id', ondelete='CASCADE'), nullable=False, index=True)
    identity: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    next_step: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default='unread', nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    model: Mapped[str] = mapped_column(String(200), nullable=False)


class ResearchFindingRevision(Base):
    __tablename__ = 'research_finding_revisions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey('research_findings.id', ondelete='CASCADE'), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('research_tasks.id', ondelete='CASCADE'), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class PaperChunk(Base):
    __tablename__ = "paper_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    bbox_json: Mapped[Optional[str]] = mapped_column(Text)
    page_width: Mapped[Optional[float]] = mapped_column()
    page_height: Mapped[Optional[float]] = mapped_column()
    paper: Mapped[Paper] = relationship(back_populates="chunks")


class PaperAnalysis(Base):
    __tablename__ = "paper_analysis"

    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    one_liner: Mapped[Optional[str]] = mapped_column(Text)
    problem: Mapped[Optional[str]] = mapped_column(Text)
    method: Mapped[Optional[str]] = mapped_column(Text)
    findings: Mapped[Optional[str]] = mapped_column(Text)
    limitations: Mapped[Optional[str]] = mapped_column(Text)
    concepts_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    provider: Mapped[str] = mapped_column(
        String(100), default="MockProvider", nullable=False
    )
    mode: Mapped[str] = mapped_column(String(32), default="extractive", nullable=False)
    evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    card_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    model_version: Mapped[Optional[str]] = mapped_column(String(200))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(100))
    paper: Mapped[Paper] = relationship(back_populates="analysis")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(default=0.9, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(32), default="explicit", nullable=False
    )
    chunk_id: Mapped[Optional[str]] = mapped_column(String(64))
    bbox_json: Mapped[Optional[str]] = mapped_column(Text)
    page_width: Mapped[Optional[float]] = mapped_column()
    page_height: Mapped[Optional[float]] = mapped_column()
    paper: Mapped[Paper] = relationship(back_populates="evidence")


class Note(Base, TimestampMixin):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[Optional[int]] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32), default="note", nullable=False)
    source_text: Mapped[Optional[str]] = mapped_column(Text)
    bbox_json: Mapped[Optional[str]] = mapped_column(Text)
    anchors_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    paper: Mapped[Paper] = relationship(back_populates="notes")


class Translation(Base):
    __tablename__ = "translations"
    __table_args__ = (
        UniqueConstraint("chunk_id", "source_hash", "provider", "config_version", "prompt_version", name="uq_translation_cache"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("paper_chunks.id", ondelete="CASCADE"), nullable=False, index=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    config_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[Optional[str]] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    paper: Mapped[Paper] = relationship(back_populates="translations")


class TranslationJob(Base, TimestampMixin):
    __tablename__ = 'translation_jobs'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey('papers.id', ondelete='CASCADE'), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    profile_id: Mapped[Optional[str]] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    config_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default='queued', nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(String(64))
    error: Mapped[Optional[str]] = mapped_column(Text)
    calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_json: Mapped[str] = mapped_column(Text, default='{}', nullable=False)
    # Full pretranslation keeps the eligible body separate from the skipped
    # appendix/reference tail so progress never suggests the whole PDF was
    # translated. Selected jobs leave the scope counters at zero.
    scope_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scope_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scope_reason: Mapped[Optional[str]] = mapped_column(String(64))
    items: Mapped[list['TranslationItem']] = relationship(cascade='all, delete-orphan', order_by='TranslationItem.position')


class TranslationItem(Base, TimestampMixin):
    __tablename__ = 'translation_items'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('translation_jobs.id', ondelete='CASCADE'), nullable=False, index=True)
    work_item_id: Mapped[Optional[str]] = mapped_column(ForeignKey('translation_items.id', ondelete='SET NULL'), index=True)
    paragraph_id: Mapped[str] = mapped_column(String(64), nullable=False)
    original_paragraph_id: Mapped[str] = mapped_column(String(64), nullable=False)
    aliases_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    refs_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default='queued', nullable=False)
    phase: Mapped[Optional[str]] = mapped_column(String(24))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    translation_id: Mapped[Optional[str]] = mapped_column(ForeignKey('translations.id', ondelete='SET NULL'))


class Edge(Base, TimestampMixin):
    __tablename__ = "edges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    target_paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(64), default="cites", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    relation_source: Mapped[str] = mapped_column(
        String(32), default="user", nullable=False
    )


class KnowledgeEntity(Base, TimestampMixin):
    """Canonical field entity; only confirmed candidates create one."""

    __tablename__ = "knowledge_entities"
    __table_args__ = (UniqueConstraint("entity_type", "normalized_name", name="uq_knowledge_entity_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    links_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    merged_into_id: Mapped[Optional[str]] = mapped_column(ForeignKey("knowledge_entities.id"))


class KnowledgeChange(Base):
    """Append-only snapshots of researcher changes, including merge origins."""

    __tablename__ = "knowledge_changes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class KnowledgeCandidate(Base, TimestampMixin):
    """Paper-local extracted item awaiting researcher review."""

    __tablename__ = "knowledge_candidates"
    __table_args__ = (
        Index("ix_knowledge_candidate_paper_status", "paper_id", "status"),
        Index("ix_knowledge_candidate_normalized", "entity_type", "normalized_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(ForeignKey("knowledge_entities.id", ondelete="SET NULL"), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="cited", nullable=False)
    confidence: Mapped[float] = mapped_column(default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="candidate", nullable=False, index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(200))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(100))
    conflict_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    paper: Mapped[Paper] = relationship(back_populates="knowledge_candidates")
    entity: Mapped[Optional[KnowledgeEntity]] = relationship()


class KnowledgeRelation(Base, TimestampMixin):
    """Paper-local, evidence-backed edge candidate."""

    __tablename__ = "knowledge_relations"
    __table_args__ = (Index("ix_knowledge_relation_paper_status", "paper_id", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(48), nullable=False)
    source_name: Mapped[str] = mapped_column(String(300), nullable=False)
    source_normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    target_name: Mapped[str] = mapped_column(String(300), nullable=False)
    target_normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    source_candidate_id: Mapped[Optional[str]] = mapped_column(ForeignKey("knowledge_candidates.id", ondelete="SET NULL"))
    target_candidate_id: Mapped[Optional[str]] = mapped_column(ForeignKey("knowledge_candidates.id", ondelete="SET NULL"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="candidate", nullable=False, index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(200))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(100))
    conflict_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    paper: Mapped[Paper] = relationship(back_populates="knowledge_relations")


class KnowledgeMaintenanceRun(Base, TimestampMixin):
    """Persistent cross-paper audit and repair plan."""

    __tablename__ = "knowledge_maintenance_runs"
    __table_args__ = (
        Index("ix_knowledge_maintenance_run_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False, index=True)
    allow_external: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model_name: Mapped[Optional[str]] = mapped_column(String(200))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(100))
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    safe_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applied_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    issues: Mapped[list["KnowledgeMaintenanceIssue"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="KnowledgeMaintenanceIssue.created_at"
    )


class KnowledgeMaintenanceIssue(Base, TimestampMixin):
    """One evidence-backed problem and its typed, reversible action proposal."""

    __tablename__ = "knowledge_maintenance_issues"
    __table_args__ = (
        Index("ix_knowledge_maintenance_issue_run_status", "run_id", "status"),
        Index("ix_knowledge_maintenance_issue_source_fingerprint", "source_fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("knowledge_maintenance_runs.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="proposed", nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    confidence_basis_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    auto_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subject_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    external_leads_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_action_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    applied_change_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    run: Mapped["KnowledgeMaintenanceRun"] = relationship(back_populates="issues")
