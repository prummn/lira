"""Conversions keep database-only JSON fields out of HTTP contracts."""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from ..models import Collection, Evidence, Note, Paper, PaperAuthor, PaperChunk, Translation
from ..schemas import (
    AnalysisRead,
    ChunkRead,
    CollectionRead,
    EvidenceRead,
    NoteRead,
    PaperDetail,
    PaperSummary,
    PaperCard,
    TranslationRead,
)

logger = logging.getLogger(__name__)


def values(raw: str | None) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid stored JSON list; preserving underlying record")
        return []
    return parsed if isinstance(parsed, list) else []


def utc(date: datetime) -> datetime:
    return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date


def source_values(raw: str | None) -> dict[str, str]:
    try:
        value = json.loads(raw or '{}')
    except json.JSONDecodeError:
        return {}
    return {str(key): item for key, item in value.items() if isinstance(item, str)} if isinstance(value, dict) else {}


def load_options():
    return (
        selectinload(Paper.author_links).selectinload(PaperAuthor.author),
        selectinload(Paper.collection_links),
        selectinload(Paper.analysis),
        selectinload(Paper.evidence),
        selectinload(Paper.chunks),
        selectinload(Paper.notes),
        selectinload(Paper.translations),
    )


def find_paper(session: Session, paper_id: str) -> Paper | None:
    return (
        session.scalars(
            select(Paper)
            .options(*load_options())
            .where(Paper.id == paper_id)
            .execution_options(populate_existing=True)
        )
        .unique()
        .one_or_none()
    )


def paper_summary(paper: Paper) -> PaperSummary:
    return PaperSummary(
        id=paper.id,
        title=paper.title,
        abstract=paper.abstract,
        year=paper.year,
        venue=paper.venue,
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        arxiv_version=paper.arxiv_version,
        source_url=paper.source_url,
        metadata_sources=source_values(paper.metadata_sources_json),
        metadata_warnings=values(paper.metadata_warnings_json),
        pdf_path=paper.pdf_path,
        reading_status=paper.reading_status,
        is_favorite=paper.is_favorite,
        analysis_status=paper.analysis_status,
        tags=values(paper.tags_json),
        authors=[l.author.name for l in paper.author_links],
        collection_ids=[l.collection_id for l in paper.collection_links],
        page_count=paper.page_count,
        is_demo=paper.is_demo,
        pdf_available=bool(paper.pdf_path and Path(paper.pdf_path).is_file()),
    )


def chunk_read(chunk: PaperChunk) -> ChunkRead:
    return ChunkRead(
        id=chunk.id,
        page=chunk.page or 1,
        section=chunk.section,
        content=chunk.content,
        bbox=values(chunk.bbox_json) or None,
        page_width=chunk.page_width,
        page_height=chunk.page_height,
    )


def evidence_read(evidence: Evidence) -> EvidenceRead:
    return EvidenceRead(
        id=evidence.id,
        claim=evidence.claim,
        source_text=evidence.source_text,
        page=evidence.page,
        section=evidence.section,
        confidence=evidence.confidence,
        source_type=evidence.source_type,
        chunk_id=evidence.chunk_id,
        bbox=values(evidence.bbox_json) or None,
        page_width=evidence.page_width,
        page_height=evidence.page_height,
    )


def note_read(note: Note) -> NoteRead:
    return NoteRead(
        id=note.id,
        content=note.content,
        page=note.page,
        kind=note.kind,
        source_text=note.source_text,
        bbox=values(note.bbox_json) or None,
        created_at=utc(note.created_at),
    )


def translation_read(translation: Translation) -> TranslationRead:
    return TranslationRead(
        id=translation.id,
        chunk_id=translation.chunk_id,
        text=translation.text,
        source_text=translation.source_text,
        provider=translation.provider,
        mode=translation.mode,
        model_version=translation.model_version,
        prompt_version=translation.prompt_version,
        created_at=utc(translation.created_at),
    )


def paper_detail(paper: Paper) -> PaperDetail:
    analysis = paper.analysis
    summary = paper_summary(paper)
    current_sources = {chunk.id: chunk.content for chunk in paper.chunks}
    card_data = {'title':paper.title}
    if analysis and analysis.card_json:
        try:
            stored_card = json.loads(analysis.card_json)
            if isinstance(stored_card,dict):
                card_data.update(stored_card)
        except json.JSONDecodeError:
            logger.warning('Invalid stored Paper Card JSON; preserving underlying analysis')
    card_data['title'] = paper.title
    result = (
        AnalysisRead(
            one_liner=analysis.one_liner,
            problem=analysis.problem,
            method=analysis.method,
            findings=analysis.findings,
            limitations=analysis.limitations,
            concepts=values(analysis.concepts_json),
            provider=analysis.provider,
            mode=analysis.mode,
            evidence_ids=values(analysis.evidence_ids_json),
            card=PaperCard.model_validate(card_data),
            model_version=analysis.model_version,
            prompt_version=analysis.prompt_version,
        )
        if analysis
        else None
    )
    return PaperDetail(
        **summary.model_dump(),
        created_at=utc(paper.created_at),
        updated_at=utc(paper.updated_at),
        analysis=result,
        evidence=[
            evidence_read(e)
            for e in sorted(paper.evidence, key=lambda e: (e.page or 0, e.id))
        ],
        chunks=[chunk_read(c) for c in paper.chunks],
        notes=[note_read(n) for n in paper.notes],
        translations=[translation_read(t) for t in sorted(paper.translations, key=lambda item: (item.created_at, item.id)) if current_sources.get(t.chunk_id) == t.source_text],
    )


def collection_read(collection: Collection) -> CollectionRead:
    return CollectionRead(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        color=collection.color,
        paper_count=len(collection.paper_links),
        created_at=utc(collection.created_at),
        updated_at=utc(collection.updated_at),
    )
