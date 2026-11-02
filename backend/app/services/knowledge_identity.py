"""Stable paper-local identities and lossless archival of duplicate extractions.

An extraction run describes provenance, not object identity. Only exact names,
unambiguous declared aliases, and already established canonical IDs can join
records. Similar spellings and same-name objects of different types stay apart.
"""
from __future__ import annotations

import json
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from ..models import KnowledgeCandidate, KnowledgeChange, KnowledgeEntity, KnowledgeRelation, Paper
from .knowledge import normalize_name

ACCEPTED = {'confirmed', 'known', 'alias'}
REVIEWED = {'confirmed', 'rejected'}
HUMAN_ACTIONS = {'confirm_candidate', 'reject_candidate', 'edit_relation', 'confirm_relation',
    'reject_relation', 'restore_relation', 'resolve_relation', 'restore'}

# A research contribution can be a benchmark or dataset as well as a method.
# These are type constraints only: valid original evidence is still required.
_RESEARCH_TYPES = frozenset({'method', 'paper', 'benchmark', 'dataset'})
_EVALUATED_TYPES = frozenset({'method', 'paper', 'benchmark'})
_RELATION_TYPES = {
    **{name: (_RESEARCH_TYPES, _RESEARCH_TYPES) for name in (
        'builds_on', 'extends', 'compares_with', 'replaces', 'inspired_by', 'contrasts_with',
    )},
    'uses_dataset': (_EVALUATED_TYPES, frozenset({'dataset', 'benchmark'})),
    'evaluated_on': (_EVALUATED_TYPES, frozenset({'dataset', 'benchmark', 'task'})),
    # A metric can supply an explicit evaluation/reward dependency (e.g. EM
    # in Reflexion); this does not turn the metric into a method.
    'requires_concept': (_EVALUATED_TYPES | {'task', 'concept'}, frozenset({'concept', 'method', 'metric'})),
}


def relation_endpoint_types(relation: str, *, target: bool) -> frozenset[str]:
    return _RELATION_TYPES.get(relation, (frozenset(), frozenset()))[int(target)]


def effective_kind(row):
    entity = getattr(row, 'entity', None)
    return entity.entity_type if entity and entity.status == 'active' else row.entity_type


def human_change(row):
    session = object_session(row)
    if session is None:
        return None
    kind = 'candidate' if isinstance(row, KnowledgeCandidate) else 'relation'
    return session.scalar(select(KnowledgeChange).where(KnowledgeChange.subject_type == kind,
        KnowledgeChange.subject_id == row.id, KnowledgeChange.action.in_(HUMAN_ACTIONS))
        .order_by(KnowledgeChange.created_at.desc(), KnowledgeChange.id.desc()).limit(1))


def ambiguous_aliases(rows) -> set[tuple[str, str]]:
    owners = {}
    for row in rows:
        name = normalize_name(row.name)
        aliases = row.aliases if hasattr(row, 'aliases') else json.loads(row.aliases_json or '[]')
        for alias in aliases:
            key = normalize_name(alias)
            if key and key != name:
                owners.setdefault((row.entity_type, key), set()).add(name)
    return {key for key, names in owners.items() if len(names) > 1}


def unique_names(names, canonical: str) -> list[str]:
    seen = {normalize_name(canonical)}
    result = []
    for name in names:
        key = normalize_name(name)
        if key and key not in seen:
            seen.add(key)
            result.append(name.strip())
    return result


def merge_evidence(*raw_values: str) -> str:
    evidence = {}
    for raw in raw_values:
        for item in json.loads(raw or '[]'):
            if isinstance(item, dict) and item.get('chunk_id') and item.get('quote'):
                key = (item['chunk_id'], item['quote'])
                evidence[key] = {**evidence.get(key, {}), **{k:v for k,v in item.items() if v is not None}}
    return json.dumps(list(evidence.values()), ensure_ascii=False)


def _priority(row):
    change = human_change(row)
    stamp = change.created_at if change else row.updated_at or row.created_at
    timestamp = stamp.replace(tzinfo=timezone.utc).timestamp() if stamp else 0
    # Explicit human decisions beat new model output, including rejected rows.
    created = row.created_at.replace(tzinfo=timezone.utc).timestamp() if row.created_at else 0
    maintained = change is not None or row.status in REVIEWED
    return (maintained, timestamp if maintained else 0,
        bool(getattr(row, 'entity_id', None)) and row.status in ACCEPTED, -created, row.id)


def match_candidate(rows, kind: str, name: str, aliases=(), entity_id=None, blocked=frozenset()):
    key = normalize_name(name)
    if entity_id:
        canonical = [row for row in rows if row.entity_id == entity_id]
        if canonical:
            return max(canonical, key=_priority)
    local = [row for row in rows if row.entity_type == kind
        and not (entity_id and row.entity_id and row.entity_id != entity_id)]
    exact = [row for row in local if row.normalized_name == key]
    if exact:
        return max(exact, key=_priority)
    matches = []
    incoming = {normalize_name(alias) for alias in aliases}
    for row in local:
        if entity_id and row.entity_id and row.entity_id != entity_id:
            continue
        names = {normalize_name(a) for a in json.loads(row.aliases_json or '[]')}
        if ((entity_id and row.entity_id == entity_id)
            or (key in names and (kind, key) not in blocked)
            or (row.normalized_name in incoming and (kind, row.normalized_name) not in blocked)):
            matches.append(row)
    return matches[0] if len(matches) == 1 else None


def relation_endpoint(rows, name: str, relation: str, *, target: bool):
    key = normalize_name(name)
    allowed = relation_endpoint_types(relation, target=target)
    exact = [row for row in rows if effective_kind(row) in allowed and row.normalized_name == key]
    if exact:
        return exact[0] if len(exact) == 1 else None
    matches = [row for row in rows if effective_kind(row) in allowed and key in {
        row.normalized_name, *(normalize_name(a) for a in json.loads(row.aliases_json or '[]')),
        *([row.entity.normalized_name, *(normalize_name(a) for a in json.loads(row.entity.aliases_json or '[]'))] if row.entity else []),
    }]
    return matches[0] if len(matches) == 1 else None


def relation_key(row):
    return (row.relation, row.source_candidate_id or ('name', row.source_normalized_name),
        row.target_candidate_id or ('name', row.target_normalized_name))


def enrich(row, *, evidence_json: str, aliases=(), name=None, description=None, role=None, confidence=None):
    row.evidence_json = merge_evidence(row.evidence_json, evidence_json)
    if isinstance(row, KnowledgeCandidate):
        row.aliases_json = json.dumps(unique_names([
            *json.loads(row.aliases_json or '[]'), *aliases, *([name] if name else []),
        ], row.name), ensure_ascii=False)
    if row.status not in REVIEWED and human_change(row) is None:
        if description and len(description) > len(row.description or ''):
            row.description = description
        if role:
            weights = {'proposed':6, 'used':5, 'component':4, 'baseline':3, 'compared':2, 'cited':1}
            if weights.get(role, 0) > weights.get(row.role, 0):
                row.role = role
        if confidence is not None:
            row.confidence = max(row.confidence, confidence)


def archived_row(session: Session, model, row_id: str):
    """Old IDs remain valid after archival, including IDs in an open browser."""
    kind = 'candidate' if model is KnowledgeCandidate else 'relation'
    seen = set()
    while row_id and row_id not in seen:
        seen.add(row_id)
        row = session.get(model, row_id)
        if row is not None:
            return row
        archive = session.scalar(select(KnowledgeChange).where(
            KnowledgeChange.subject_type == kind, KnowledgeChange.subject_id == row_id,
            KnowledgeChange.action == 'duplicate_archived').order_by(KnowledgeChange.created_at.desc()))
        row_id = json.loads(archive.after_json).get('canonical_id') if archive else None
    return None


def _archive(session, duplicate, keeper):
    from .knowledge_curation import snapshot
    import uuid
    session.add(KnowledgeChange(id='kh-'+uuid.uuid4().hex,
        subject_type='candidate' if isinstance(duplicate, KnowledgeCandidate) else 'relation',
        subject_id=duplicate.id, action='duplicate_archived',
        before_json=json.dumps({**snapshot(duplicate),
            'created_at':duplicate.created_at.isoformat() if duplicate.created_at else None,
            'updated_at':duplicate.updated_at.isoformat() if duplicate.updated_at else None}, ensure_ascii=False),
        after_json=json.dumps({'canonical_id':keeper.id, 'canonical':snapshot(keeper)}, ensure_ascii=False)))
    session.delete(duplicate)


def reconcile_paper(session: Session, paper: Paper) -> dict[str, int]:
    """Archive exact legacy duplicates, preserve decisions, and rewire edges."""
    from .knowledge import paper_knowledge_status
    from .knowledge_curation import record, snapshot

    candidates = list(session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.paper_id == paper.id)).all())
    relations = list(session.scalars(select(KnowledgeRelation).where(KnowledgeRelation.paper_id == paper.id)).all())
    counts = {'candidates':0, 'relations':0}
    # Prefer reviewed records first. Shared aliases alone never imply identity.
    survivors = []
    blocked = ambiguous_aliases(candidates)
    for row in sorted(candidates, key=_priority, reverse=True):
        keeper = match_candidate(survivors, row.entity_type, row.name,
            json.loads(row.aliases_json or '[]'), row.entity_id, blocked)
        if keeper is None or (keeper.entity_id and row.entity_id and keeper.entity_id != row.entity_id):
            survivors.append(row)
            continue
        enrich(keeper, evidence_json=row.evidence_json, aliases=json.loads(row.aliases_json or '[]'),
            name=row.name, description=row.description, role=row.role, confidence=row.confidence)
        for edge in relations:
            before = snapshot(edge)
            if edge.source_candidate_id == row.id:
                edge.source_candidate_id = keeper.id
            if edge.target_candidate_id == row.id:
                edge.target_candidate_id = keeper.id
            if snapshot(edge) != before:
                record(session, edge, 'endpoint_reconciled', before)
        _archive(session, row, keeper)
        counts['candidates'] += 1
    # Flush updated FKs before deleting their former endpoints (SQLite enforces
    # immediate foreign keys, and ORM has no relationship between these rows).
    session.flush()
    edge_groups = {}
    by_id = {row.id:row for row in survivors}
    for row in relations:
        # Incremental extractions can mention an object from a previous run.
        for attr, label, target in [('source_candidate_id', row.source_name, False), ('target_candidate_id', row.target_name, True)]:
            if not getattr(row, attr):
                endpoint = relation_endpoint(survivors, label, row.relation, target=target)
                if endpoint:
                    setattr(row, attr, endpoint.id)
        ends = [by_id.get(cid) for cid in (row.source_candidate_id, row.target_candidate_id)]
        ignored_end = any(end and end.status == 'rejected' for end in ends)
        self_edge = bool(all(ends) and (ends[0].id == ends[1].id or (ends[0].entity_id and ends[0].entity_id == ends[1].entity_id)))
        if row.status == 'confirmed' and (ignored_end or not all(ends) or self_edge):
            before = snapshot(row)
            row.status = 'conflict' if self_edge else 'unresolved'
            record(session, row, 'endpoint_rejected' if ignored_end else 'merge_relation_conflict', before)
        if row.status == 'unresolved' and all(ends) and not ignored_end and not self_edge:
            row.status = 'candidate'
        edge_groups.setdefault(relation_key(row), []).append(row)
    for group in edge_groups.values():
        keeper = max(group, key=_priority)
        for duplicate in group:
            if duplicate is keeper:
                continue
            enrich(keeper, evidence_json=duplicate.evidence_json, description=duplicate.description, confidence=duplicate.confidence)
            _archive(session, duplicate, keeper)
            counts['relations'] += 1
    session.flush()
    paper.knowledge_status = paper_knowledge_status(survivors, [g[0] if len(g)==1 else max(g, key=_priority) for g in edge_groups.values()])
    if counts['candidates'] or counts['relations']:
        session.expire(paper, ['knowledge_candidates', 'knowledge_relations'])
    return counts


def reconcile_library(session: Session) -> dict[str, int]:
    counts = {'candidates':0, 'relations':0}
    for paper in session.scalars(select(Paper)).all():
        repaired = reconcile_paper(session, paper)
        for key in counts:
            counts[key] += repaired[key]
    # Old confirmations stored aliases only on extraction candidates. Recover
    # them without taking over another canonical object's alias namespace.
    from .knowledge_curation import record, snapshot
    entities = list(session.scalars(select(KnowledgeEntity).where(KnowledgeEntity.status == 'active')).all())
    accepted = list(session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.status.in_(ACCEPTED))).all())
    for entity in entities:
        if session.scalar(select(KnowledgeChange.id).where(KnowledgeChange.subject_type == 'entity',
            KnowledgeChange.subject_id == entity.id, KnowledgeChange.action == 'edit_entity').limit(1)):
            continue
        aliases = json.loads(entity.aliases_json or '[]')
        for candidate in accepted:
            if candidate.entity_id != entity.id:
                continue
            for name in [candidate.name, *json.loads(candidate.aliases_json or '[]')]:
                key = normalize_name(name)
                collision = any(other.id != entity.id and other.entity_type == entity.entity_type
                    and key in {other.normalized_name, *(normalize_name(a) for a in json.loads(other.aliases_json or '[]'))} for other in entities)
                if not collision:
                    aliases.append(name)
        encoded = json.dumps(unique_names(aliases, entity.name), ensure_ascii=False)
        if json.loads(encoded) != json.loads(entity.aliases_json or '[]'):
            before = snapshot(entity)
            entity.aliases_json = encoded
            record(session, entity, 'recover_aliases', before)
    session.flush()
    return counts
