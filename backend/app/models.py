"""SQLAlchemy models for local-first paper intelligence data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
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
