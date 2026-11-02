"""Evidence-first reconciliation for paper knowledge candidates."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeCandidate, KnowledgeEntity, KnowledgeRelation, Paper, PaperChunk
from ..providers.base import KnowledgeCandidateEntry, KnowledgeRelationEntry

ENTITY_TYPES = {'paper', 'method', 'dataset', 'benchmark', 'task', 'metric', 'concept', 'venue'}
RELATIONS = {'builds_on', 'extends', 'compares_with', 'replaces', 'uses_dataset', 'evaluated_on', 'inspired_by', 'contrasts_with', 'requires_concept'}
STATUSES = {'candidate', 'confirmed', 'rejected', 'conflict', 'unresolved', 'new', 'known', 'alias'}


def normalize_name(value: str) -> str:
    value = unicodedata.normalize('NFKC', value or '').casefold()
    value = re.sub(r"[\u2010-\u2015\-_/]+", ' ', value)
    value = re.sub(r"[^\w\s.+#]", ' ', value, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', value).strip()


def _evidence(citation) -> dict:
    chunk = citation.chunk
    return {
        'chunk_id': chunk.id,
        'page': chunk.page,
        'section': chunk.section,
        'quote': citation.source_text,
        'bbox': json.loads(chunk.bbox_json) if chunk.bbox_json else None,
        'page_width': chunk.page_width,
        'page_height': chunk.page_height,
    }


def _valid_evidence(paper: Paper, raw: Iterable[dict]) -> list[dict]:
    chunks = {chunk.id: chunk for chunk in paper.chunks}
    result: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        chunk = chunks.get(item.get('chunk_id'))
        quote = item.get('quote')
        if chunk is None or not isinstance(quote, str) or not quote.strip() or quote not in chunk.content:
            continue
        result.append({
            'chunk_id': chunk.id, 'page': chunk.page, 'section': chunk.section,
            'quote': quote, 'bbox': json.loads(chunk.bbox_json) if chunk.bbox_json else None,
            'page_width': chunk.page_width, 'page_height': chunk.page_height,
        })
    return list({(item['chunk_id'], item['quote']): item for item in result}.values())


def _id(*values: str) -> str:
    digest = hashlib.sha256('|'.join(values).encode('utf-8')).hexdigest()[:24]
    return 'kc-' + digest


def _status_for(entity: KnowledgeEntity | None, aliases: list[str], name: str) -> tuple[str, KnowledgeEntity | None, dict]:
    if entity is None:
        return 'new', None, {}
    if normalize_name(name) != normalize_name(entity.name):
        return 'alias', entity, {'canonical_name': entity.name}
    return 'known', entity, {'canonical_name': entity.name}


def _entity_lookup(session: Session, entity_type: str, normalized_name: str) -> KnowledgeEntity | None:
    exact = session.scalar(select(KnowledgeEntity).where(KnowledgeEntity.entity_type == entity_type, KnowledgeEntity.normalized_name == normalized_name, KnowledgeEntity.status == 'active'))
    if exact:
        return exact
    for item in session.scalars(select(KnowledgeEntity).where(KnowledgeEntity.entity_type == entity_type, KnowledgeEntity.status == 'active')).all():
        aliases = json.loads(item.aliases_json or '[]')
        if normalized_name in {normalize_name(alias) for alias in aliases}:
            return item
    return None


def _entry_payload(entry: KnowledgeCandidateEntry, paper: Paper) -> tuple[dict, str] | None:
    evidence = _valid_evidence(paper, [_evidence(citation) for citation in entry.citations])
    if not evidence or entry.entity_type not in ENTITY_TYPES or not entry.name.strip():
        return None
    normalized = normalize_name(entry.name)
    return evidence, normalized


def persist_candidates(
    session: Session,
    paper: Paper,
    entries: list[KnowledgeCandidateEntry],
    relations: list[KnowledgeRelationEntry],
    *,
    run_id: str,
) -> tuple[list[KnowledgeCandidate], list[KnowledgeRelation]]:
    """Upsert a paper's identities; runs and quotes are provenance, not identity."""
    from .knowledge_identity import ambiguous_aliases, archived_row, enrich, match_candidate, reconcile_paper, relation_endpoint, relation_key
    reconcile_paper(session, paper)
    existing = list(session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.paper_id == paper.id)).all())
    blocked = ambiguous_aliases([*existing, *entries])
    candidates: list[KnowledgeCandidate] = []
    for entry in entries:
        payload = _entry_payload(entry, paper)
        if payload is None:
            continue
        evidence, normalized = payload
        entity = _entity_lookup(session, entry.entity_type, normalized)
        status, entity, conflict = _status_for(entity, entry.aliases, entry.name)
        candidate = match_candidate(existing, entry.entity_type, entry.name, entry.aliases, entity.id if entity else None, blocked)
        evidence_json = json.dumps(evidence, ensure_ascii=False)
        if candidate is None:
            candidate = KnowledgeCandidate(
                id=_id(paper.id, 'object', entry.entity_type, normalized), paper_id=paper.id, entity_id=entity.id if entity else None,
                entity_type=entry.entity_type, name=entry.name.strip(), normalized_name=normalized,
                aliases_json=json.dumps(entry.aliases, ensure_ascii=False), description=entry.description,
                role=entry.role, confidence=max(0, min(1, entry.confidence)), status=status,
                evidence_json=evidence_json, run_id=run_id,
                model_version=getattr(entry, 'model_version', None), prompt_version=getattr(entry, 'prompt_version', None),
                conflict_json=json.dumps(conflict, ensure_ascii=False),
            )
            session.add(candidate)
            existing.append(candidate)
        else:
            enrich(candidate, evidence_json=evidence_json, aliases=entry.aliases,
                name=entry.name, description=entry.description, role=entry.role, confidence=entry.confidence)
            if candidate.status not in {'confirmed', 'rejected'} and entity:
                candidate.entity_id = entity.id
                candidate.entity = entity
                candidate.status = status
        if candidate not in candidates:
            candidates.append(candidate)
    session.flush()
    stored_relations = list(session.scalars(select(KnowledgeRelation).where(KnowledgeRelation.paper_id == paper.id)).all())
    relation_rows: list[KnowledgeRelation] = []
    for relation in relations:
        if relation.relation not in RELATIONS or not relation.source_name.strip() or not relation.target_name.strip():
            continue
        evidence = _valid_evidence(paper, [_evidence(citation) for citation in relation.citations])
        if not evidence:
            continue
        source_norm, target_norm = normalize_name(relation.source_name), normalize_name(relation.target_name)
        source_candidate = relation_endpoint(existing, relation.source_name, relation.relation, target=False)
        target_candidate = relation_endpoint(existing, relation.target_name, relation.relation, target=True)
        source_id = source_candidate.id if source_candidate else None
        target_id = target_candidate.id if target_candidate else None
        key = (relation.relation, source_id or ('name', source_norm), target_id or ('name', target_norm))
        row = next((item for item in stored_relations if relation_key(item) == key), None)
        stable_id = _id(paper.id, 'relation', relation.relation, source_id or source_norm, target_id or target_norm)
        if row is None:
            row = archived_row(session, KnowledgeRelation, stable_id)
        if row is None:
            # Human corrections may change the predicate and endpoints of an
            # older random-ID extraction. Its before-state records provenance.
            from ..models import KnowledgeChange
            changes = session.scalars(select(KnowledgeChange).where(KnowledgeChange.subject_type == 'relation',
                KnowledgeChange.action.in_(['edit_relation', 'resolve_relation']))
                .order_by(KnowledgeChange.created_at.desc())).all()
            for change in changes:
                before = json.loads(change.before_json)
                if before.get('paper_id') == paper.id and (before.get('relation'), before.get('source_normalized_name'), before.get('target_normalized_name')) == (relation.relation, source_norm, target_norm):
                    row = archived_row(session, KnowledgeRelation, change.subject_id)
                    if row:
                        break
        if row is None:
            row = KnowledgeRelation(
                id=stable_id, paper_id=paper.id, relation=relation.relation,
                source_name=relation.source_name.strip(), source_normalized_name=source_norm,
                target_name=relation.target_name.strip(), target_normalized_name=target_norm,
                source_candidate_id=source_candidate.id if source_candidate else None,
                target_candidate_id=target_candidate.id if target_candidate else None,
                description=relation.description, confidence=max(0, min(1, relation.confidence)),
                status='candidate' if source_candidate and target_candidate else 'unresolved',
                evidence_json=json.dumps(evidence, ensure_ascii=False), run_id=run_id,
            )
            session.add(row)
            stored_relations.append(row)
        else:
            enrich(row, evidence_json=json.dumps(evidence, ensure_ascii=False),
                description=relation.description, confidence=relation.confidence)
        if row not in relation_rows:
            relation_rows.append(row)
    paper.knowledge_status = paper_knowledge_status(existing, stored_relations)
    session.flush()
    session.expire(paper, ['knowledge_candidates', 'knowledge_relations'])
    return candidates, relation_rows


def confirm_candidate(session: Session, candidate: KnowledgeCandidate, *, name: str | None = None, description: str | None = None) -> KnowledgeCandidate:
    from fastapi import HTTPException
    from .knowledge_curation import check_namespace, record, snapshot, unique_aliases
    if not _valid_evidence(candidate.paper, _json_evidence(candidate.evidence_json)):
        raise HTTPException(422, '未找到这篇论文中的有效原文证据，暂时不能确认对象')
    before = snapshot(candidate)
    final_name = (name or candidate.name).strip()
    normalized = normalize_name(final_name)
    linked = candidate.entity if candidate.entity_id else None
    if linked and linked.merged_into_id:
        from .knowledge_curation import entity_for
        linked = entity_for(session, linked.id)
    preserves_identity = linked and (name is None or normalized in {candidate.normalized_name, linked.normalized_name, normalize_name(linked.name), *(normalize_name(alias) for alias in json.loads(linked.aliases_json or '[]'))})
    entity_type = linked.entity_type if linked else candidate.entity_type
    entity = linked if preserves_identity else _entity_lookup(session, entity_type, normalized)
    from ..models import KnowledgeChange
    maintained = entity and session.scalar(select(KnowledgeChange.id).where(
        KnowledgeChange.subject_type == 'entity', KnowledgeChange.subject_id == entity.id,
        KnowledgeChange.action == 'edit_entity').limit(1)) is not None
    aliases = unique_aliases([
        *(json.loads(entity.aliases_json or '[]') if entity else []),
        *([] if maintained else [*json.loads(candidate.aliases_json or '[]'), candidate.name,
            *([final_name] if entity else [])]),
    ], entity.name if entity else final_name)
    check_namespace(session, entity_type, [entity.name if entity else final_name, *aliases], {entity.id} if entity else set())
    if entity is None:
        entity = KnowledgeEntity(id='ke-' + uuid.uuid4().hex[:20], entity_type=entity_type, name=final_name, normalized_name=normalized, aliases_json=json.dumps(aliases, ensure_ascii=False), description=description or candidate.description, status='active')
        session.add(entity)
    else:
        entity.aliases_json = json.dumps(aliases, ensure_ascii=False)
        entity.normalized_name = normalize_name(entity.name)
    candidate.aliases_json = json.dumps(unique_aliases([*json.loads(candidate.aliases_json or '[]'), candidate.name], final_name), ensure_ascii=False)
    candidate.entity_id = entity.id
    candidate.entity = entity
    candidate.name = final_name
    candidate.normalized_name = normalized
    candidate.description = description or candidate.description
    candidate.status = 'confirmed'
    context = json.loads(candidate.conflict_json or '{}')
    context.pop('_steward_context', None)
    candidate.conflict_json = json.dumps(context, ensure_ascii=False)
    session.flush()
    if snapshot(candidate) != before:
        record(session, candidate, 'confirm_candidate', before)
    return candidate


def reject_candidate(session: Session, candidate: KnowledgeCandidate) -> KnowledgeCandidate:
    from .knowledge_curation import record, snapshot
    before = snapshot(candidate)
    candidate.status = 'rejected'
    session.flush()
    if snapshot(candidate) != before:
        record(session, candidate, 'reject_candidate', before)
    return candidate


def resolve_relation(
    session: Session,
    relation: KnowledgeRelation,
    *,
    target_name: str,
    target_type: str,
) -> KnowledgeRelation:
    """Resolve an unresolved edge against a canonical target entity.

    Resolution is deterministic and idempotent: a second request reuses the
    same entity and paper-local candidate.  Existing evidence is retained
    verbatim; a candidate is confirmed only when at least one stored quote is
    present in the paper's source chunks.
    """
    from .knowledge_curation import confirmable
    if target_type not in ENTITY_TYPES:
        raise ValueError('无效的目标实体类型')
    final_name = (target_name or '').strip()
    normalized = normalize_name(final_name)
    if not normalized:
        raise ValueError('目标实体名称不能为空')
    if relation.status == 'rejected':
        raise ValueError('请先恢复被忽略的关系')
    if relation.status == 'confirmed' and confirmable(session, relation):
        return relation
    evidence = _valid_evidence(relation.paper, _json_evidence(relation.evidence_json))
    if not evidence:
        raise ValueError('未找到这篇论文中的有效原文证据')
    candidate = session.scalar(select(KnowledgeCandidate).where(
        KnowledgeCandidate.paper_id == relation.paper_id,
        KnowledgeCandidate.entity_type == target_type,
        KnowledgeCandidate.normalized_name == normalized,
        KnowledgeCandidate.status != 'rejected',
    ).order_by(KnowledgeCandidate.created_at, KnowledgeCandidate.id))
    if candidate is None:
        candidate = KnowledgeCandidate(
            id='kc-' + uuid.uuid4().hex[:24], paper_id=relation.paper_id, paper=relation.paper,
            entity_type=target_type, name=final_name, normalized_name=normalized,
            aliases_json='[]', role='cited', confidence=relation.confidence,
            status='candidate', evidence_json=json.dumps(evidence, ensure_ascii=False),
            run_id='relation-resolution',
        )
        session.add(candidate)
    if candidate.status not in {'confirmed', 'known', 'alias'} or not candidate.entity_id:
        confirm_candidate(session, candidate, name=final_name)
    relation.target_candidate_id = candidate.id
    relation.target_name = final_name
    relation.target_normalized_name = normalized
    session.flush()
    relation.status = 'confirmed' if confirmable(session, relation) else 'unresolved'
    session.flush()
    return relation


def _json_evidence(raw: str | None) -> list[dict]:
    try:
        value = json.loads(raw or '[]')
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def paper_knowledge_status(candidates: list[KnowledgeCandidate], relations: list[KnowledgeRelation]) -> str:
    rows = [*candidates, *relations]
    if not rows:
        return 'unread'
    statuses = {row.status for row in rows}
    if 'conflict' in statuses or 'unresolved' in statuses:
        return 'needs_review'
    if all(status in {'confirmed', 'rejected', 'known', 'alias'} for status in statuses):
        return 'settled'
    if any(status == 'confirmed' for status in statuses):
        return 'partially_settled'
    return 'candidates'
