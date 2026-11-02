"""Paper-level, evidence-backed curation with reversible automatic decisions."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from ..models import KnowledgeCandidate, KnowledgeChange, KnowledgeEntity, KnowledgeRelation
from ..providers.base import ProviderError
from .knowledge import ENTITY_TYPES, RELATIONS, _valid_evidence, normalize_name, paper_knowledge_status
from .knowledge_curation import check_namespace, record, snapshot, unique_aliases, confirmable
from .knowledge_identity import human_change, relation_endpoint, reconcile_paper

VERSION = 'paper-steward-v1'
BODY_LIMIT = 90000
THRESHOLD = .96


class Citation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chunk_id: str
    quote: str = Field(min_length=1, max_length=6000)


class ObjectDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=300)
    entity_type: str
    role: str
    description: str = Field(default='', max_length=2000)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    citations: list[Citation] = Field(min_length=1, max_length=8)
    entity_id: str | None = None


class RelationDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_name: str = Field(min_length=1, max_length=300)
    target_name: str = Field(min_length=1, max_length=300)
    relation: str
    description: str = Field(default='', max_length=2000)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    citations: list[Citation] = Field(min_length=1, max_length=8)


class RelationReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    relation_id: str
    verdict: str = Field(pattern='^(supported|unsupported|uncertain)$')
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=2000)
    citations: list[Citation] = Field(min_length=1, max_length=8)


class ObjectReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_id: str
    verdict: str = Field(pattern='^(supported|incidental|incorrect|uncertain)$')
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=2000)
    citations: list[Citation] = Field(min_length=1, max_length=8)


class CurationBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(default='', max_length=3000)
    candidates: list[ObjectDecision] = Field(default_factory=list, max_length=64)
    relations: list[RelationDecision] = Field(default_factory=list, max_length=96)
    reviews: list[RelationReview] = Field(default_factory=list, max_length=96)
    object_reviews: list[ObjectReview] = Field(default_factory=list, max_length=96)


def output_schema():
    schema = CurationBatch.model_json_schema()
    def strict(node):
        if isinstance(node, dict):
            node.pop('default', None)
            if node.get('type') == 'object':
                node['additionalProperties'] = False
                node['required'] = list(node.get('properties', {}))
            for value in node.values(): strict(value)
        elif isinstance(node, list):
            for value in node: strict(value)
    strict(schema)
    return schema


def fingerprint(paper):
    payload = [VERSION, paper.title,
        [(c.id, c.content, c.section) for c in sorted(paper.chunks, key=lambda c: c.id)],
        sorted([snapshot(c) for c in paper.knowledge_candidates], key=lambda r: r['id']),
        sorted([snapshot(r) for r in paper.knowledge_relations], key=lambda r: r['id'])]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build_bundle(session, paper):
    """Supply original main text, rather than the first twelve extraction blocks."""
    chunks, count = [], 0
    from .translation_queue import _cutoff_section
    ordered = sorted(paper.chunks, key=lambda c: (c.page or 0, c.id))
    cutoff = next((i for i, c in enumerate(ordered) if _cutoff_section(c.section)), len(ordered))
    body = ordered[:cutoff]
    for c in body:
        remaining = BODY_LIMIT - count
        if remaining <= 0:
            break
        content = c.content[:remaining]
        chunks.append({'chunk_id': c.id, 'page': c.page, 'section': c.section, 'content': content})
        count += len(content)
    # Existing mistakes may originate in an appendix. Supply their actual
    # neighborhood for review, without extracting new appendix inventories.
    ordered = sorted(paper.chunks, key=lambda c: (c.page or 0, c.id))
    cited = {e.get('chunk_id') for r in [*paper.knowledge_relations, *paper.knowledge_candidates] if r.status != 'rejected'
             for e in json.loads(r.evidence_json or '[]')}
    supplied = {c['chunk_id'] for c in chunks}
    review_chunks, review_chars = [], 0
    # Supply every referenced original before spending the review budget on
    # neighbors. Early appendix neighborhoods must not crowd out later objects.
    for chunk in ordered:
        if chunk.id not in cited or chunk.id in supplied or review_chars + len(chunk.content) > 20000:
            continue
        review_chunks.append({'chunk_id': chunk.id, 'page': chunk.page,
            'section': chunk.section, 'content': chunk.content})
        supplied.add(chunk.id); review_chars += len(chunk.content)
    for i, chunk in enumerate(ordered):
        if chunk.id not in cited:
            continue
        for neighbor in [chunk, *ordered[max(0, i-12):i+4]]:
            if neighbor.id in supplied or review_chars + len(neighbor.content) > 20000:
                continue
            review_chunks.append({'chunk_id': neighbor.id, 'page': neighbor.page,
                'section': neighbor.section, 'content': neighbor.content})
            supplied.add(neighbor.id); review_chars += len(neighbor.content)
    entities = session.scalars(select(KnowledgeEntity).where(KnowledgeEntity.status == 'active')
                              .order_by(KnowledgeEntity.entity_type, KnowledgeEntity.name)).all()
    local = {c.entity_id for c in paper.knowledge_candidates if c.entity_id}
    text = ' '.join(c['content'] for c in chunks)
    entities.sort(key=lambda e: (e.id not in local, not _mentions(text, [e.name, *json.loads(e.aliases_json or '[]')]), e.id))
    entities = entities[:300]
    unlinked = [e.id for e in entities if e.id not in local and _mentions(text, [e.name, *json.loads(e.aliases_json or '[]')])][:80]
    return {'mode': 'paper_curation', 'version': VERSION, 'paper_id': paper.id, 'title': paper.title,
        'fingerprint': fingerprint(paper), 'chunks': chunks, 'review_chunks': review_chunks, 'source_chars': count,
        'coverage': 'main_text' if sum(len(c.content) for c in body) <= BODY_LIMIT else 'bounded',
        'unlinked_mentions': unlinked, 'candidates': [snapshot(c) for c in paper.knowledge_candidates],
        'relations': [snapshot(r) for r in paper.knowledge_relations],
        'registry': [{'id': e.id, 'entity_type': e.entity_type, 'name': e.name,
                      'aliases': json.loads(e.aliases_json or '[]'), 'description': e.description} for e in entities]}


def _evidence(paper, citations, bundle, *, review=False):
    from ..providers.validation import canonical_quote
    supplied = {c['chunk_id']: c['content'] for c in bundle['chunks'] + (bundle.get('review_chunks', []) if review else [])}
    raw = [c.model_dump() for c in citations]
    for citation in raw:
        if citation['chunk_id'] in supplied:
            source = supplied[citation['chunk_id']]
            quote = citation['quote']
            matched = canonical_quote(source, quote, allow_pdf_formatting=True)
            if matched is None and len(quote) >= 40 and quote.endswith(('.', ';', '。')):
                matched = canonical_quote(source, quote[:-1], allow_pdf_formatting=True)
            if matched is None and len(source) <= 6000:
                # A model may abbreviate a real paragraph with an ellipsis.
                # Restore its complete original chunk only when every nontrivial
                # fragment matches in order; never retain the abbreviated quote.
                parts = re.split(r'\s*(?:\.\.\.|…)\s*', quote)
                if len(parts) > 1 and all(len(part.strip()) >= 20 for part in parts):
                    tail = source
                    for part in parts:
                        fragment = canonical_quote(tail, part, allow_pdf_formatting=True)
                        if fragment is None: break
                        tail = tail[tail.index(fragment) + len(fragment):]
                    else:
                        matched = source
            citation['quote'] = matched
    if any(c['chunk_id'] not in supplied or not c['quote'] for c in raw):
        raise ProviderError('知识整理引文未出现在本次原文上下文中，已有知识已保留', code='invalid_curation')
    valid = _valid_evidence(paper, raw)
    if len(valid) != len({(c['chunk_id'], c['quote']) for c in raw}):
        raise ProviderError('知识整理引文无法通过原文核验，已有知识已保留', code='invalid_curation')
    return valid


def _mentions(text, names):
    text = re.sub(r'\s+', ' ', text.replace('\\n', ' '))
    return any(re.search(r'(?<!\w)' + re.escape(re.sub(r'\s+', ' ', name)) + r'(?!\w)', text, re.I) for name in names if name)


def _expand_names(paper, evidence, bundle, names):
    if all(_mentions(' '.join(e['quote'] for e in evidence), variants) for variants in names):
        return evidence
    supplied = {c['chunk_id']: c['content'] for c in bundle['chunks'] + bundle.get('review_chunks', [])}
    expanded = [{'chunk_id': e['chunk_id'], 'quote': supplied[e['chunk_id']]} for e in evidence
        if e['chunk_id'] in supplied and len(supplied[e['chunk_id']]) <= 6000]
    ordered = sorted(bundle['chunks'] + bundle.get('review_chunks', []), key=lambda c: (c.get('page') or 0, c['chunk_id']))
    positions = {c['chunk_id']: i for i,c in enumerate(ordered)}
    for variants in names:
        if _mentions(' '.join(e['quote'] for e in expanded), variants):
            continue
        found = None
        for item in evidence:
            index = positions.get(item['chunk_id'])
            if index is None: continue
            origin = ordered[index]
            neighbors = ordered[max(0,index-2):index+3]
            found = next((c for c in neighbors if c.get('section') == origin.get('section')
                and len(c['content']) <= 6000 and _mentions(c['content'], variants)), None)
            if found: break
        if found:
            expanded.append({'chunk_id':found['chunk_id'], 'quote':found['content']})
    return _valid_evidence(paper, expanded) if expanded else evidence


def _equivalent(name, entity, evidence):
    known = {normalize_name(entity.name), *(normalize_name(a) for a in json.loads(entity.aliases_json or '[]'))}
    if normalize_name(name) in known:
        return True
    qualified = re.fullmatch(r'(.+?)\s*\(([^()]+)\)', name)
    if qualified and normalize_name(qualified.group(1)) in known and any(_mentions(e['quote'], [name]) for e in evidence):
        return True
    for e in evidence:
        text = e['quote']
        if not (_mentions(text, [name]) and _mentions(text, [entity.name])):
            continue
        a, b = re.escape(name), re.escape(entity.name)
        if re.search(rf'(?:{a}\s*\(\s*{b}\s*\)|{b}\s*\(\s*{a}\s*\)|{a}\s+(?:means|stands for|is short for)\s+{b})', text, re.I):
            return True
    return False


def _review_neighborhood(paper, row, evidence, bundle):
    """Bind an owner heading to the existing passage it introduces."""
    ordered = sorted(bundle['chunks'] + bundle.get('review_chunks', []), key=lambda c: (c.get('page') or 0, c['chunk_id']))
    positions = {c['chunk_id']: i for i,c in enumerate(ordered)}
    original = _valid_evidence(paper, json.loads(row.evidence_json or '[]'))
    linked = []
    for old in original:
        at = positions.get(old['chunk_id'])
        if at is None: continue
        for review in evidence:
            idx = positions.get(review['chunk_id'])
            if idx is not None and abs(idx-at) <= 12 and ordered[idx].get('section') == ordered[at].get('section'):
                linked.append(old); break
    return _valid_evidence(paper, [*evidence, *linked]) if linked else evidence


def _incident(edge, row, rows):
    for identifier, name in ((edge.source_candidate_id, edge.source_name), (edge.target_candidate_id, edge.target_name)):
        if identifier == row.id:
            return True
        if identifier is None and normalize_name(name) == row.normalized_name:
            matches = [c for c in rows if c.normalized_name == row.normalized_name]
            if len(matches) == 1:
                return True
    return False


def _context_dismissed(session, row):
    for change in session.scalars(select(KnowledgeChange).where(
            KnowledgeChange.subject_type == 'candidate', KnowledgeChange.subject_id == row.id,
            KnowledgeChange.action == 'confirm_candidate')):
        before = json.loads(change.before_json).get('conflict_json', '{}')
        after = json.loads(change.after_json).get('conflict_json', '{}')
        if '_steward_context' in json.loads(before or '{}') and '_steward_context' not in json.loads(after or '{}'):
            return True
    return False


def _contextual(row):
    context = json.loads(row.conflict_json or '{}').get('_steward_context', {})
    return context.get('verdict') in {'incidental', 'incorrect'}


def _change(session, row, action, before):
    record(session, row, 'steward_' + action, before)


def _protected_object(session, rows, item, evidence):
    for row in rows:
        if row.status != 'rejected' and not human_change(row):
            continue
        names = [row.name, *json.loads(row.aliases_json or '[]')]
        if normalize_name(item.name) in {normalize_name(n) for n in names}:
            return True
        if row.entity and (item.entity_id == row.entity_id or _equivalent(item.name, row.entity, evidence)):
            return True
    # A removed canonical name/alias must not be recreated as another entity.
    for change in session.scalars(select(KnowledgeChange).where(
            KnowledgeChange.subject_type == 'entity', KnowledgeChange.action == 'edit_entity')):
        old = json.loads(change.before_json)
        entity = session.get(KnowledgeEntity, change.subject_id)
        if not entity or entity.entity_type != item.entity_type:
            continue
        old_names = {normalize_name(n) for n in [old.get('name', ''), *json.loads(old.get('aliases_json', '[]'))]}
        current = {entity.normalized_name, *(normalize_name(n) for n in json.loads(entity.aliases_json or '[]'))}
        if normalize_name(item.name) in old_names - current:
            return True
    return False


def _protected_edge(session, paper, source, target, predicate):
    def matches(data):
        return (data.get('paper_id') == paper.id and data.get('relation') == predicate
            and (data.get('source_candidate_id') == source.id or data.get('source_normalized_name') == source.normalized_name)
            and (data.get('target_candidate_id') == target.id or data.get('target_normalized_name') == target.normalized_name))
    for change in session.scalars(select(KnowledgeChange).where(
            KnowledgeChange.subject_type == 'relation', KnowledgeChange.action.in_(['edit_relation','reject_relation','resolve_relation']))):
        if matches(json.loads(change.before_json)) or matches(json.loads(change.after_json)):
            return True
    return False


def _accept(session, row, evidence, registry_id=None, aliases=()):
    from fastapi import HTTPException
    try:
        # A namespace conflict is local to this proposed identity. Roll back
        # its entity/alias writes while preserving other verified decisions.
        with session.begin_nested():
            return _accept_identity(session, row, evidence, registry_id, aliases)
    except HTTPException as error:
        if error.status_code != 409:
            raise
        return False


def _accept_identity(session, row, evidence, registry_id=None, aliases=()):
    from .knowledge import _entity_lookup
    entity = session.get(KnowledgeEntity, registry_id) if registry_id else _entity_lookup(session, row.entity_type, row.normalized_name)
    if entity and (entity.entity_type != row.entity_type or entity.status != 'active' or not _equivalent(row.name, entity, evidence)):
        return False
    if entity is None:
        entity = KnowledgeEntity(id='ke-' + uuid.uuid4().hex[:20], entity_type=row.entity_type, name=row.name,
            normalized_name=row.normalized_name, aliases_json='[]', description=row.description, status='active')
        session.add(entity); session.flush(); _change(session, entity, 'create', {})
    if entity is not None:
        # Alias additions are identity changes too: keep their own undo snapshot.
        declared = [a for a in aliases if _equivalent(a, entity, evidence)]
        names = unique_aliases([*json.loads(entity.aliases_json or '[]'), row.name, *declared], entity.name)
        check_namespace(session, entity.entity_type, [entity.name, *names], {entity.id})
        encoded = json.dumps(names, ensure_ascii=False)
        if json.loads(entity.aliases_json or '[]') != names:
            if session.scalar(select(KnowledgeChange.id).where(KnowledgeChange.subject_type == 'entity',
                    KnowledgeChange.subject_id == entity.id, KnowledgeChange.action == 'edit_entity').limit(1)):
                return False
            before = snapshot(entity); entity.aliases_json = encoded; _change(session, entity, 'aliases', before)
    before = snapshot(row)
    from .knowledge_identity import merge_evidence
    row.evidence_json = merge_evidence(row.evidence_json, json.dumps(evidence, ensure_ascii=False))
    row.entity = entity; row.entity_id = entity.id; row.status = 'confirmed'
    if before != snapshot(row):
        _change(session, row, 'confirm', before)
    return True


def apply_batch(session, paper, data, bundle):
    # Keep a rejected namespace collision or malformed reply from leaving half
    # a graph behind while preserving the worker's previous checkpoints.
    with session.begin_nested():
        return _apply_batch(session, paper, data, bundle)


def _apply_batch(session, paper, data, bundle):
    """Validate the entire reply before applying any source-grounded decision."""
    try:
        batch = CurationBatch.model_validate(data)
    except ValidationError:
        raise ProviderError('知识整理结果格式无效，已有知识已保留', code='invalid_curation') from None
    if fingerprint(paper) != bundle['fingerprint']:
        raise ProviderError('知识已在整理期间更新，本次结果未写入', 409, code='stale_curation')
    objects, edges, outside_body = [], [], 0
    body_ids = {c['chunk_id'] for c in bundle['chunks']}
    for item in batch.candidates:
        if item.entity_type not in ENTITY_TYPES or item.role not in {'proposed','used','baseline','ablation','component','cited','compared'}:
            raise ProviderError('知识整理对象类型无效', code='invalid_curation')
        evidence = _evidence(paper, item.citations, bundle, review=True)
        if any(c.chunk_id not in body_ids for c in item.citations):
            outside_body += 1
            continue
        if not _mentions(' '.join(e['quote'] for e in evidence), [item.name]):
            # A short quote can omit its own paragraph label (File editor).
            # Expand only inside the same verified, supplied body chunk.
            contexts = {c['chunk_id']: c['content'] for c in bundle['chunks']}
            expanded = next(({'chunk_id': c.chunk_id, 'quote': contexts[c.chunk_id]} for c in item.citations
                if _mentions(contexts[c.chunk_id], [item.name]) and len(contexts[c.chunk_id]) <= 6000), None)
            if expanded:
                evidence = _valid_evidence(paper, [expanded])
            else:
                evidence = _expand_names(paper, evidence, bundle, [[item.name]])
        objects.append((item, evidence))
    for item in batch.relations:
        if item.relation not in RELATIONS:
            raise ProviderError('知识整理关系类型无效', code='invalid_curation')
        evidence = _evidence(paper, item.citations, bundle, review=True)
        if any(c.chunk_id not in body_ids for c in item.citations):
            outside_body += 1
            continue
        edges.append((item, evidence))
    reviews = [(item, _evidence(paper, item.citations, bundle, review=True)) for item in batch.reviews]
    object_reviews = [(item, _evidence(paper, item.citations, bundle, review=True)) for item in batch.object_reviews]
    before_changes = set(session.scalars(select(KnowledgeChange.id)))
    report = dict(paper_id=paper.id, title=paper.title, source_chars=bundle['source_chars'], source_chunks=len(bundle['chunks']),
        coverage=bundle['coverage'], objects_added=0, objects_confirmed=0, relations_added=0, relations_confirmed=0,
        aliases_linked=0, objects_rejected=0, objects_contextualized=0, relations_rejected=0, protected=0, deferred=outside_body, summary=batch.summary, checked_at=datetime.now(timezone.utc).isoformat())
    rows = list(session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.paper_id == paper.id)))
    for item, evidence in objects:
        if item.confidence < THRESHOLD or not _mentions(' '.join(e['quote'] for e in evidence), [item.name]):
            report['deferred'] += 1; continue
        if _protected_object(session, rows, item, evidence):
            report['protected'] += 1; continue
        row = next((r for r in rows if r.entity_type == item.entity_type and r.normalized_name == normalize_name(item.name)), None)
        if row and (row.status == 'rejected' or human_change(row)):
            report['protected'] += 1; continue
        if row and row.status in {'confirmed','known','alias'} and row.entity_id:
            continue
        entity = session.get(KnowledgeEntity, item.entity_id) if item.entity_id else None
        if item.entity_id and (not entity or not _equivalent(item.name, entity, evidence) or entity.entity_type != item.entity_type):
            report['deferred'] += 1; continue
        if row is None:
            row = KnowledgeCandidate(id='kc-' + uuid.uuid4().hex[:24], paper_id=paper.id, paper=paper,
                entity_type=item.entity_type, name=item.name, normalized_name=normalize_name(item.name),
                aliases_json='[]', role=item.role, description=item.description, confidence=item.confidence,
                status='new', evidence_json=json.dumps(evidence, ensure_ascii=False), run_id=VERSION)
            session.add(row); session.flush(); _change(session, row, 'create', {}); rows.append(row)
            report['objects_added'] += 1
        if _accept(session, row, evidence, item.entity_id, item.aliases):
            report['objects_confirmed'] += 1
            report['aliases_linked'] += int(bool(entity and normalize_name(item.name) != entity.normalized_name))
        else:
            report['deferred'] += 1
    session.flush()
    # A supported review settles identity before this pass resolves its edges.
    for item, evidence in object_reviews:
        if item.verdict != 'supported':
            continue
        row = next((r for r in rows if r.id == item.candidate_id), None)
        if row is None or item.confidence < THRESHOLD:
            report['deferred'] += 1; continue
        if row.status == 'rejected' or human_change(row) or _contextual(row):
            report['protected'] += 1; continue
        if row.status in {'confirmed', 'known', 'alias'} and row.entity_id:
            continue
        evidence = _expand_names(paper, evidence, bundle, [[row.name]])
        if not _mentions(' '.join(e['quote'] for e in evidence), [row.name]):
            report['deferred'] += 1; continue
        identity = ObjectDecision(name=row.name, entity_type=row.entity_type, role=row.role or 'cited',
            entity_id=row.entity_id, confidence=item.confidence, citations=item.citations)
        if _protected_object(session, rows, identity, evidence):
            report['protected'] += 1; continue
        if _accept(session, row, evidence, row.entity_id):
            report['objects_confirmed'] += 1
        else:
            report['deferred'] += 1
    session.flush()
    existing = list(session.scalars(select(KnowledgeRelation).where(KnowledgeRelation.paper_id == paper.id)))
    for item, evidence in edges:
        source = relation_endpoint(rows, item.source_name, item.relation, target=False)
        target = relation_endpoint(rows, item.target_name, item.relation, target=True)
        if (item.confidence < THRESHOLD or not source or not target or source is target
                or any(r.status not in {'confirmed','known','alias'} or _contextual(r) for r in (source,target))):
            report['deferred'] += 1; continue
        if _protected_edge(session, paper, source, target, item.relation):
            report['protected'] += 1; continue
        text = ' '.join(e['quote'] for e in evidence)
        evidence = _expand_names(paper, evidence, bundle, [[r.name, *json.loads(r.aliases_json or '[]')] for r in (source,target)])
        text = ' '.join(e['quote'] for e in evidence)
        if not all(_mentions(text, [r.name, *json.loads(r.aliases_json or '[]')]) for r in (source,target)):
            report['deferred'] += 1; continue
        row = next((r for r in existing if r.relation == item.relation
            and r.source_normalized_name == normalize_name(item.source_name)
            and r.target_normalized_name == normalize_name(item.target_name)), None)
        if row and (row.status == 'rejected' or human_change(row)):
            report['protected'] += 1; continue
        if row and row.status == 'confirmed':
            continue
        if row is None:
            row = KnowledgeRelation(id='kr-' + uuid.uuid4().hex[:24],paper_id=paper.id,
                relation=item.relation,source_name=source.name,source_normalized_name=source.normalized_name,
                target_name=target.name,target_normalized_name=target.normalized_name,
                source_candidate_id=source.id,target_candidate_id=target.id,status='candidate',
                description=item.description,confidence=item.confidence,evidence_json=json.dumps(evidence,ensure_ascii=False),run_id=VERSION)
            session.add(row);session.flush();_change(session,row,'create',{});existing.append(row);report['relations_added']+=1
        before=snapshot(row)
        from .knowledge_identity import merge_evidence
        row.evidence_json = merge_evidence(row.evidence_json, json.dumps(evidence, ensure_ascii=False))
        row.source_candidate_id=source.id;row.target_candidate_id=target.id
        if confirmable(session,row):
            row.status='confirmed';_change(session,row,'confirm',before);report['relations_confirmed']+=1
    for item, evidence in reviews:
        row = next((r for r in existing if r.id == item.relation_id), None)
        if row is None or item.confidence < THRESHOLD or item.verdict == 'uncertain':
            report['deferred'] += 1; continue
        if row.status == 'rejected' or human_change(row):
            report['protected'] += 1; continue
        evidence = _expand_names(paper, evidence, bundle, [[row.source_name], [row.target_name]])
        text = ' '.join(e['quote'] for e in evidence)
        original_ids = {e.get('chunk_id') for e in _valid_evidence(paper, json.loads(row.evidence_json or '[]'))}
        anchored = bool(original_ids & {e['chunk_id'] for e in evidence})
        if not anchored and not all(_mentions(text, [name]) for name in (row.source_name, row.target_name)):
            report['deferred'] += 1; continue
        before = snapshot(row)
        if item.verdict == 'unsupported':
            row.status = 'rejected'
            _change(session, row, 'reject', before); report['relations_rejected'] += 1
        elif row.status != 'confirmed':
            source = relation_endpoint(rows, row.source_name, row.relation, target=False)
            target = relation_endpoint(rows, row.target_name, row.relation, target=True)
            if source and target:
                row.source_candidate_id, row.target_candidate_id = source.id, target.id
            from .knowledge_identity import merge_evidence
            row.evidence_json = merge_evidence(row.evidence_json, json.dumps(evidence, ensure_ascii=False))
            if source and target and not any(_contextual(r) for r in (source,target)) and confirmable(session, row):
                row.status = 'confirmed'; _change(session, row, 'confirm', before)
                report['relations_confirmed'] += 1
            else:
                row.source_candidate_id = before['source_candidate_id']
                row.target_candidate_id = before['target_candidate_id']
                row.evidence_json = before['evidence_json']
                report['deferred'] += 1
    session.flush()
    for item, evidence in object_reviews:
        row = next((r for r in rows if r.id == item.candidate_id), None)
        if row is None or item.confidence < THRESHOLD or item.verdict in {'supported','uncertain'}:
            continue
        if _context_dismissed(session, row):
            report['protected'] += 1; continue
        if row.status == 'rejected':
            report['protected'] += 1; continue
        evidence = _review_neighborhood(paper, row, evidence, bundle)
        evidence = _expand_names(paper, evidence, bundle, [[row.name]])
        original_ids = {e.get('chunk_id') for e in json.loads(row.evidence_json or '[]')}
        direct_source = bool(original_ids & {e['chunk_id'] for e in evidence})
        if not direct_source and not _mentions(' '.join(e['quote'] for e in evidence), [row.name]):
            report['deferred'] += 1; continue
        if human_change(row) or any(_incident(edge, row, rows) and human_change(edge) for edge in existing):
            # Preserve accepted identity and manual roles. Context is a separate,
            # reversible source assessment, not a silent rejection of user work.
            before = snapshot(row)
            context = json.loads(row.conflict_json or '{}')
            context['_steward_context'] = {'verdict': item.verdict, 'reason': item.reason,
                'confidence': item.confidence, 'evidence': evidence, 'version': VERSION}
            row.conflict_json = json.dumps(context, ensure_ascii=False)
            if before != snapshot(row):
                _change(session, row, 'context', before); report['objects_contextualized'] += 1
            for edge in existing:
                if _incident(edge, row, rows) and edge.status != 'rejected' and not human_change(edge):
                    before = snapshot(edge); edge.status = 'rejected'; _change(session, edge, 'reject', before)
                    report['relations_rejected'] += 1
            report['protected'] += 1; continue
        before = snapshot(row); row.status = 'rejected'; _change(session, row, 'reject', before)
        report['objects_rejected'] += 1
        for edge in existing:
            if _incident(edge, row, rows) and edge.status != 'rejected' and not human_change(edge):
                before = snapshot(edge); edge.status = 'rejected'; _change(session, edge, 'reject', before)
                report['relations_rejected'] += 1
    session.flush()
    paper.knowledge_status=paper_knowledge_status(rows,existing)
    report['pending_objects'] = sum(r.status not in {'confirmed','known','alias','rejected'} for r in rows)
    report['pending_relations'] = sum(r.status not in {'confirmed','rejected'} for r in existing)
    session.expire(paper,['knowledge_candidates','knowledge_relations'])
    report['change_ids']=[v for v in session.scalars(select(KnowledgeChange.id)) if v not in before_changes]
    report['result_fingerprint']=fingerprint(paper)
    return report


def undo_changes(session, change_ids):
    """Refuse stale undo before mutating anything; created objects leave no orphans."""
    changes=list(session.scalars(select(KnowledgeChange).where(KnowledgeChange.id.in_(change_ids))
        .order_by(KnowledgeChange.created_at,KnowledgeChange.id)))
    models={'entity':KnowledgeEntity,'candidate':KnowledgeCandidate,'relation':KnowledgeRelation}
    latest={}
    for change in changes:latest[(change.subject_type,change.subject_id)]=change
    for (kind,identifier),change in latest.items():
        row=session.get(models[kind],identifier)
        if row is None or snapshot(row)!=json.loads(change.after_json):
            raise ProviderError('整理后这些对象已有新修改，不能覆盖后续决定',409,code='stale_curation')
    created_entities = {c.subject_id for c in changes if c.subject_type == 'entity' and not json.loads(c.before_json)}
    touched_candidates = {c.subject_id for c in changes if c.subject_type == 'candidate'}
    touched_relations = {c.subject_id for c in changes if c.subject_type == 'relation'}
    if touched_candidates and session.scalar(select(KnowledgeRelation.id).where(
            ((KnowledgeRelation.source_candidate_id.in_(touched_candidates)) |
             (KnowledgeRelation.target_candidate_id.in_(touched_candidates))),
            ~KnowledgeRelation.id.in_(touched_relations)).limit(1)):
        raise ProviderError('这些对象已有后续关系引用，不能直接撤销其创建',409,code='stale_curation')
    if created_entities and session.scalar(select(KnowledgeCandidate.id).where(
            KnowledgeCandidate.entity_id.in_(created_entities), ~KnowledgeCandidate.id.in_(touched_candidates)).limit(1)):
        raise ProviderError('这些对象已被其他论文采用，不能直接撤销其创建',409,code='stale_curation')
    paper_ids = {getattr(session.get(models[c.subject_type], c.subject_id), 'paper_id', None) for c in changes}
    for change in reversed(changes):
        row=session.get(models[change.subject_type],change.subject_id)
        before=json.loads(change.before_json)
        if not before:
            session.delete(row);session.flush()
        else:
            for key,value in before.items():setattr(row,key,value)
            session.flush()
    from ..models import Paper
    for identifier in paper_ids - {None}:
        paper = session.get(Paper, identifier)
        if paper:
            session.expire(paper, ['knowledge_candidates', 'knowledge_relations'])
            paper.knowledge_status = paper_knowledge_status(paper.knowledge_candidates, paper.knowledge_relations)
