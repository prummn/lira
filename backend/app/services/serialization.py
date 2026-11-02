"""Conversions keep database-only JSON fields out of HTTP contracts."""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, object_session
from ..models import Collection, Evidence, IntelligenceTask, KnowledgeCandidate, KnowledgeRelation, Note, Paper, PaperAuthor, PaperChunk, Translation
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
    TaskRead,
    KnowledgeCandidateRead,
    KnowledgeEvidence,
    KnowledgeRelationRead,
    KnowledgeEntityDetailRead,
    KnowledgeEntityLinkRead,
    KnowledgeEntityPaperRead,
)
from .knowledge_view import classify_candidate, classify_relation

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
        selectinload(Paper.intelligence_tasks),
        selectinload(Paper.knowledge_candidates),
        selectinload(Paper.knowledge_relations),
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
        intelligence_status=paper.intelligence_status,
        intelligence_report=json_object(paper.intelligence_report_json) if paper.intelligence_report_json else None,
        intelligence_task=task_read(max(paper.intelligence_tasks, key=lambda task: (task.created_at, task.id))) if paper.intelligence_tasks else None,
        intelligence_analyzed_at=utc(paper.intelligence_analyzed_at) if paper.intelligence_analyzed_at else None,
        knowledge_status=paper.knowledge_status,
        tags=values(paper.tags_json),
        authors=[l.author.name for l in paper.author_links],
        collection_ids=[l.collection_id for l in paper.collection_links],
        page_count=paper.page_count,
        is_demo=paper.is_demo,
        pdf_available=bool(paper.pdf_path and Path(paper.pdf_path).is_file()),
    )


def json_object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or '{}')
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def task_read(task: IntelligenceTask) -> TaskRead:
    return TaskRead(id=task.id, paper_id=task.paper_id, status=task.status, phase=task.phase,
        completed_steps=task.completed_steps, total_steps=task.total_steps, report=json_object(task.report_json),
        error=task.error, created_at=utc(task.created_at), updated_at=utc(task.updated_at))


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
        source_url=getattr(evidence, 'source_url', None),
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
        anchors=values(note.anchors_json),
        created_at=utc(note.created_at),
        updated_at=utc(note.updated_at),
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


def knowledge_evidence_read(raw: dict) -> KnowledgeEvidence:
    return KnowledgeEvidence(
        paper_id=raw.get('paper_id'), paper_title=raw.get('paper_title'),
        chunk_id=raw.get('chunk_id', ''), page=raw.get('page'), section=raw.get('section'), quote=raw.get('quote', ''),
        bbox=tuple(raw['bbox']) if isinstance(raw.get('bbox'), list) and len(raw['bbox']) == 4 else None,
        page_width=raw.get('page_width'), page_height=raw.get('page_height'),
    )


def knowledge_candidate_read(candidate: KnowledgeCandidate) -> KnowledgeCandidateRead:
    entity = candidate.entity if candidate.entity_id and object_session(candidate) else None
    name = entity.name if entity else candidate.name
    kind = entity.entity_type if entity else candidate.entity_type
    layer, importance = classify_candidate(kind, name, candidate.role, candidate.description or '')
    context = json_object(candidate.conflict_json).get('_steward_context', {})
    if isinstance(context, dict) and context.get('verdict') in {'incidental', 'incorrect'}:
        layer, importance = 'comparison', 'context'
    return KnowledgeCandidateRead(
        id=candidate.id, paper_id=candidate.paper_id, entity_id=candidate.entity_id,
        entity_type=kind, name=name, normalized_name=entity.normalized_name if entity else candidate.normalized_name,
        extracted_name=candidate.name,
        aliases=values(candidate.aliases_json), description=candidate.description, role=candidate.role,
        confidence=candidate.confidence, status=candidate.status,
        evidence=[knowledge_evidence_read({**item, 'paper_id':candidate.paper_id}) for item in values(candidate.evidence_json) if isinstance(item, dict)],
        conflict=json_object(candidate.conflict_json), run_id=candidate.run_id,
        model_version=candidate.model_version, prompt_version=candidate.prompt_version,
          layer=layer, importance=importance,
    )


def knowledge_relation_read(relation: KnowledgeRelation) -> KnowledgeRelationRead:
    session = object_session(relation)
    source = session.get(KnowledgeCandidate, relation.source_candidate_id) if session and relation.source_candidate_id else None
    target = session.get(KnowledgeCandidate, relation.target_candidate_id) if session and relation.target_candidate_id else None
    source_entity = source.entity if source else None
    target_entity = target.entity if target else None
    family, importance = classify_relation(relation.relation, relation.target_name)
    return KnowledgeRelationRead(
        id=relation.id, paper_id=relation.paper_id, relation=relation.relation,
        source_name=source_entity.name if source_entity else relation.source_name, source_normalized_name=source_entity.normalized_name if source_entity else relation.source_normalized_name,
        target_name=target_entity.name if target_entity else relation.target_name, target_normalized_name=target_entity.normalized_name if target_entity else relation.target_normalized_name,
        source_entity_id=source.entity_id if source else None, target_entity_id=target.entity_id if target else None,
        source_candidate_id=relation.source_candidate_id, target_candidate_id=relation.target_candidate_id,
        description=relation.description, confidence=relation.confidence, status=relation.status,
        evidence=[knowledge_evidence_read({**item, 'paper_id':relation.paper_id}) for item in values(relation.evidence_json) if isinstance(item, dict)],
        conflict=json_object(relation.conflict_json), run_id=relation.run_id,
        model_version=relation.model_version, prompt_version=relation.prompt_version,
          family=family, importance=importance,
    )


def knowledge_entity_link_read(*, kind: str, label: str, url: str, source: str) -> KnowledgeEntityLinkRead:
    return KnowledgeEntityLinkRead(kind=kind, label=label, url=url, source=source)


def knowledge_entity_detail_read(entity, *, candidates: list[KnowledgeCandidate], papers: list[dict], relations: list[KnowledgeRelation], evidence: list[dict], links: list[dict]) -> KnowledgeEntityDetailRead:
    """Serialize an entity dossier assembled by the knowledge API."""
    return KnowledgeEntityDetailRead(
        id=entity.id,
        entity_type=entity.entity_type,
        name=entity.name,
        normalized_name=entity.normalized_name,
        aliases=values(entity.aliases_json),
        description=entity.description,
        status=entity.status,
        candidates=[knowledge_candidate_read(item) for item in candidates],
        papers=[KnowledgeEntityPaperRead(**item) for item in papers],
        relations=[knowledge_relation_read(item) for item in relations],
        evidence=[knowledge_evidence_read(item) for item in evidence],
        links=[knowledge_entity_link_read(**item) for item in links],
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
        knowledge_candidates=[knowledge_candidate_read(item) for item in paper.knowledge_candidates],
        knowledge_relations=[knowledge_relation_read(item) for item in paper.knowledge_relations],
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
