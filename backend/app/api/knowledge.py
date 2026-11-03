"""Reviewable paper knowledge candidates and confirmed field registry."""

from __future__ import annotations

import json
import uuid
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, raiseload

from ..db import get_db
from ..models import KnowledgeCandidate, KnowledgeEntity, KnowledgeRelation, PaperChunk, Paper, PaperAuthor, CollectionPaper
from ..providers import get_model_provider
from ..providers.base import ProviderError
from ..schemas import KnowledgeEntityUpdate, KnowledgeEntityMerge, KnowledgeRelationUpdate, KnowledgeRelationCreate, CandidateDecision, CandidateBatchDecision, KnowledgeCandidateRead, KnowledgePaperRead, KnowledgeRelationRead, KnowledgeAuditRead, KnowledgeEntityDetailRead, KnowledgeRelationResolution
from ..services.knowledge import confirm_candidate, paper_knowledge_status, reject_candidate, resolve_relation, normalize_name
from ..services import knowledge_curation as curation
from ..services.knowledge_audit import audit_paper_knowledge
from ..services.serialization import knowledge_candidate_read, knowledge_relation_read, knowledge_entity_detail_read
from ..services.reading_paragraphs import paragraphs_for
from .dependencies import require_paper

router = APIRouter()


@router.get('/knowledge/papers')
def field_papers(collection_id: str | None = None, session: Session = Depends(get_db)) -> dict:
    """Stored reading summaries for field views; no source text or fresh audits."""
    statement = select(Paper).options(selectinload(Paper.analysis),
        selectinload(Paper.author_links).selectinload(PaperAuthor.author), raiseload('*'))
    if collection_id:
        from .dependencies import require_collection
        require_collection(session, collection_id)
        statement = statement.where(Paper.id.in_(select(CollectionPaper.paper_id).where(
            CollectionPaper.collection_id == collection_id)))
    items = []
    for paper in session.scalars(statement.order_by(Paper.year, Paper.id)):
        analysis = paper.analysis
        items.append(dict(id=paper.id, title=paper.title, abstract=paper.abstract, year=paper.year,
            venue=paper.venue, arxiv_id=paper.arxiv_id, source_url=paper.source_url,
            authors=[link.author.name for link in paper.author_links], is_demo=paper.is_demo,
            analysis_status=paper.analysis_status, intelligence_status=paper.intelligence_status,
            analysis={**{key:getattr(analysis,key) for key in
                ('problem','method','findings','limitations','provider','mode')},
                'concepts':json.loads(analysis.concepts_json or '[]')} if analysis else None))
    return {'items':items}


def _paper_payload(session: Session, paper_id: str) -> KnowledgePaperRead:
    paper = require_paper(session, paper_id)
    candidates = session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.paper_id == paper_id).order_by(KnowledgeCandidate.created_at, KnowledgeCandidate.id)).all()
    relations = session.scalars(select(KnowledgeRelation).where(KnowledgeRelation.paper_id == paper_id).order_by(KnowledgeRelation.created_at, KnowledgeRelation.id)).all()
    status = paper_knowledge_status(candidates, relations)
    if paper.knowledge_status != status:
        paper.knowledge_status = status
        session.commit()
    return KnowledgePaperRead(
        paper_id=paper_id, paper_status=status,
        candidates=[knowledge_candidate_read(item) for item in candidates if json.loads(item.evidence_json or '[]')],
        relations=[knowledge_relation_read(item) for item in relations if json.loads(item.evidence_json or '[]')],
        counts={status: sum(row.status == status for row in [*candidates, *relations]) for status in {'candidate', 'confirmed', 'rejected', 'conflict', 'unresolved', 'new', 'known', 'alias'}},
    )


@router.get('/papers/{paper_id}/knowledge', response_model=KnowledgePaperRead)
def paper_knowledge(paper_id: str, session: Session = Depends(get_db)) -> KnowledgePaperRead:
    return _paper_payload(session, paper_id)


@router.get('/papers/{paper_id}/knowledge/audit', response_model=KnowledgeAuditRead)
def paper_knowledge_audit(paper_id: str, session: Session = Depends(get_db)) -> KnowledgeAuditRead:
    paper = require_paper(session, paper_id)
    return KnowledgeAuditRead(**audit_paper_knowledge(paper).model_dump())


@router.get('/knowledge/entities')
def entities(
    entity_type: str | None = Query(None), query: str | None = Query(None), status: str = Query('active'),
    paper_ids: str | None = Query(None), session: Session = Depends(get_db),
) -> dict:
    ids = {value.strip() for value in (paper_ids or '').split(',') if value.strip()}
    candidates = session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.status != 'rejected')).all()
    relations = session.scalars(select(KnowledgeRelation).where(KnowledgeRelation.status != 'rejected')).all()
    by_candidate = {row.id:row for row in candidates}
    rows = session.scalars(select(KnowledgeEntity).where(KnowledgeEntity.status == status).order_by(KnowledgeEntity.entity_type, KnowledgeEntity.name)).all()
    items = []
    for row in rows:
        if entity_type and row.entity_type != entity_type:
            continue
        aliases = json.loads(row.aliases_json or '[]')
        if query and normalize_name(query) not in normalize_name(' '.join([row.name, *aliases, row.description or ''])):
            continue
        local = [c for c in candidates if c.entity_id == row.id and (not ids or c.paper_id in ids)]
        if paper_ids is not None and not local:
            continue
        rels = [r for r in relations if (not ids or r.paper_id in ids) and any(by_candidate.get(cid) and by_candidate[cid].entity_id == row.id for cid in (r.source_candidate_id,r.target_candidate_id))]
        contexts=[json.loads(c.conflict_json or '{}').get('_steward_context', {}) for c in local]
        contextual=[c for c,context in zip(local,contexts) if context.get('verdict') in {'incidental','incorrect'}]
        reasons=[context.get('reason') for context in contexts if context.get('verdict') in {'incidental','incorrect'} and context.get('reason')]
        items.append({'id':row.id, 'entity_type':row.entity_type, 'name':row.name, 'normalized_name':row.normalized_name, 'aliases':aliases, 'description':row.description, 'status':row.status, 'paper_count':len({c.paper_id for c in local}), 'relation_count':len(rels),
            'contextual_paper_count':len({c.paper_id for c in contextual}), 'context_only':bool(local) and len(contextual)==len(local), 'context_summary':reasons[0] if reasons else None})
    return {'items':items}


@router.get('/knowledge/overview')
def knowledge_overview(
    paper_ids: str | None = Query(None),
    session: Session = Depends(get_db),
) -> dict:
    """Return the lightweight graph payload used by the field map.

    Full paper detail includes chunks, notes and evidence and is intentionally
    loaded lazily by the page. The map only needs stored candidates and
    relations, so keeping this projection separate avoids making a 30-paper
    field feel blocked on PDF-sized responses.
    """
    ids = {item.strip() for item in (paper_ids or '').split(',') if item.strip()}
    candidates_statement = select(KnowledgeCandidate).order_by(KnowledgeCandidate.created_at, KnowledgeCandidate.id)
    relations_statement = select(KnowledgeRelation).order_by(KnowledgeRelation.created_at, KnowledgeRelation.id)
    if ids:
        candidates_statement = candidates_statement.where(KnowledgeCandidate.paper_id.in_(ids))
        relations_statement = relations_statement.where(KnowledgeRelation.paper_id.in_(ids))
    candidates = session.scalars(candidates_statement).all()
    relations = session.scalars(relations_statement).all()
    return {
        'candidates': [knowledge_candidate_read(row).model_dump() for row in candidates if json.loads(row.evidence_json or '[]')],
        'relations': [knowledge_relation_read(row).model_dump() for row in relations if json.loads(row.evidence_json or '[]')],
    }


@router.get('/knowledge/entities/{entity_id}', response_model=KnowledgeEntityDetailRead)
def entity_detail(entity_id: str, session: Session = Depends(get_db)) -> KnowledgeEntityDetailRead:
    return curation.dossier(session, curation.entity_for(session, entity_id))


@router.patch('/knowledge/entities/{entity_id}', response_model=KnowledgeEntityDetailRead)
def edit_entity(entity_id: str, payload: KnowledgeEntityUpdate, session: Session = Depends(get_db)):
    entity = curation.entity_for(session, entity_id)
    curation.edit_entity(session, entity, payload)
    session.commit()
    return curation.dossier(session, entity)


@router.post('/knowledge/entities/{entity_id}/merge-preview')
def preview_merge(entity_id: str, payload: KnowledgeEntityMerge, session: Session = Depends(get_db)):
    return curation.merge_preview(session, curation.entity_for(session, entity_id), curation.entity_for(session, payload.target_id))


@router.post('/knowledge/entities/{entity_id}/merge', response_model=KnowledgeEntityDetailRead)
def merge_entities(entity_id: str, payload: KnowledgeEntityMerge, session: Session = Depends(get_db)):
    source, target = curation.entity_for(session, entity_id), curation.entity_for(session, payload.target_id)
    curation.merge_entity(session, source, target)
    session.commit()
    return curation.dossier(session, target)


@router.get('/knowledge/relations')
def relations(status: str = Query('confirmed'), session: Session = Depends(get_db)) -> dict:
    statement = select(KnowledgeRelation).order_by(KnowledgeRelation.created_at)
    if status != 'all':
        statement = statement.where(KnowledgeRelation.status == status)
    rows = session.scalars(statement).all()
    return {'items': [knowledge_relation_read(row).model_dump() for row in rows]}


def _candidate(session: Session, candidate_id: str) -> KnowledgeCandidate:
    from ..services.knowledge_identity import archived_row
    candidate = archived_row(session, KnowledgeCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, '未找到这条知识候选')
    return candidate


@router.post('/papers/{paper_id}/knowledge/review', response_model=KnowledgePaperRead)
def batch_review(paper_id: str, payload: CandidateBatchDecision, session: Session = Depends(get_db)):
    require_paper(session, paper_id)
    rows = [_candidate(session, cid) for cid in dict.fromkeys(payload.candidate_ids)]
    if any(row.paper_id != paper_id for row in rows):
        raise HTTPException(422, '只能一起审阅当前论文中的对象')
    # One transaction; an invalid item cannot leave a partially accepted batch.
    for row in rows:
        if payload.decision == 'confirm':
            confirm_candidate(session, row)
        else:
            reject_candidate(session, row)
            for edge in session.scalars(select(KnowledgeRelation).where(
                (KnowledgeRelation.source_candidate_id == row.id) | (KnowledgeRelation.target_candidate_id == row.id),
                KnowledgeRelation.status == 'confirmed')).all():
                before = curation.snapshot(edge)
                edge.status = 'unresolved'
                curation.record(session, edge, 'endpoint_rejected', before)
    session.flush()
    curation.refresh_paper_status(session, paper_id)
    session.commit()
    return _paper_payload(session, paper_id)


@router.post('/knowledge/candidates/{candidate_id}/confirm', response_model=KnowledgeCandidateRead)
def confirm(candidate_id: str, payload: CandidateDecision | None = None, session: Session = Depends(get_db)) -> KnowledgeCandidateRead:
    candidate = _candidate(session, candidate_id)
    confirm_candidate(session, candidate, name=payload.name if payload else None, description=payload.description if payload else None)
    paper = require_paper(session, candidate.paper_id)
    rows = session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.paper_id == paper.id)).all()
    rels = session.scalars(select(KnowledgeRelation).where(KnowledgeRelation.paper_id == paper.id)).all()
    paper.knowledge_status = paper_knowledge_status(rows, rels)
    session.commit()
    return knowledge_candidate_read(candidate)


@router.post('/knowledge/candidates/{candidate_id}/edit-confirm', response_model=KnowledgeCandidateRead)
def edit_confirm(candidate_id: str, payload: CandidateDecision, session: Session = Depends(get_db)) -> KnowledgeCandidateRead:
    return confirm(candidate_id, payload, session)


@router.post('/knowledge/candidates/{candidate_id}/reject', response_model=KnowledgeCandidateRead)
def reject(candidate_id: str, session: Session = Depends(get_db)) -> KnowledgeCandidateRead:
    candidate = _candidate(session, candidate_id)
    reject_candidate(session, candidate)
    for relation in session.scalars(select(KnowledgeRelation).where(
        (KnowledgeRelation.source_candidate_id == candidate.id) | (KnowledgeRelation.target_candidate_id == candidate.id)
    )).all():
        if relation.status == 'confirmed':
            before = curation.snapshot(relation)
            relation.status = 'unresolved'
            curation.record(session, relation, 'endpoint_rejected', before)
    session.flush()
    paper = require_paper(session, candidate.paper_id)
    rows = session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.paper_id == paper.id)).all()
    rels = session.scalars(select(KnowledgeRelation).where(KnowledgeRelation.paper_id == paper.id)).all()
    paper.knowledge_status = paper_knowledge_status(rows, rels)
    session.commit()
    return knowledge_candidate_read(candidate)


def _relation(session: Session, relation_id: str) -> KnowledgeRelation:
    from ..services.knowledge_identity import archived_row
    row = archived_row(session, KnowledgeRelation, relation_id)
    if row is None:
        raise HTTPException(404, '未找到这条关系')
    return row


@router.post('/knowledge/relations/{relation_id}/confirm', response_model=KnowledgeRelationRead)
def confirm_relation(relation_id: str, session: Session = Depends(get_db)):
    row = _relation(session, relation_id)
    curation.review_relation(session, row, 'confirm')
    session.commit()
    return knowledge_relation_read(row)


@router.post('/knowledge/relations/{relation_id}/reject', response_model=KnowledgeRelationRead)
def reject_relation(relation_id: str, session: Session = Depends(get_db)):
    row = _relation(session, relation_id)
    curation.review_relation(session, row, 'reject')
    session.commit()
    return knowledge_relation_read(row)


@router.post('/knowledge/relations/{relation_id}/restore', response_model=KnowledgeRelationRead)
def restore_relation(relation_id: str, session: Session = Depends(get_db)):
    row = _relation(session, relation_id)
    curation.review_relation(session, row, 'restore')
    session.commit()
    return knowledge_relation_read(row)


@router.patch('/knowledge/relations/{relation_id}', response_model=KnowledgeRelationRead)
def edit_relation(relation_id: str, payload: KnowledgeRelationUpdate, session: Session = Depends(get_db)):
    row = _relation(session, relation_id)
    curation.edit_relation(session, row, payload)
    session.commit()
    return knowledge_relation_read(row)


@router.post('/papers/{paper_id}/knowledge/relations', response_model=KnowledgeRelationRead, status_code=201)
def create_relation(paper_id: str, payload: KnowledgeRelationCreate, session: Session = Depends(get_db)):
    paper = require_paper(session, paper_id)
    from ..services.knowledge import _valid_evidence
    evidence = _valid_evidence(paper, [item.model_dump() for item in payload.evidence])
    if not evidence:
        raise HTTPException(422, '请提供这篇论文中的原句作为关系证据')
    row = KnowledgeRelation(id='kr-' + uuid.uuid4().hex[:24], paper_id=paper_id, relation=payload.relation, source_name='', source_normalized_name='', target_name='', target_normalized_name='', status='candidate', confidence=1, run_id='manual', evidence_json=json.dumps(evidence, ensure_ascii=False))
    curation.edit_relation(session, row, payload, record_change=False)
    duplicate = session.scalar(select(KnowledgeRelation).where(KnowledgeRelation.paper_id == paper_id, KnowledgeRelation.source_candidate_id == row.source_candidate_id, KnowledgeRelation.target_candidate_id == row.target_candidate_id, KnowledgeRelation.relation == row.relation, KnowledgeRelation.status != 'rejected'))
    if duplicate:
        raise HTTPException(409, '这篇论文中已存在相同关系，请直接维护已有记录')
    session.add(row)
    curation.record(session, row, 'create_relation', {})
    session.flush()
    curation.refresh_paper_status(session, paper_id)
    session.commit()
    return knowledge_relation_read(row)


@router.post('/knowledge/relations/{relation_id}/resolve', response_model=KnowledgeRelationRead)
def resolve_relation_endpoint(relation_id: str, payload: KnowledgeRelationResolution, session: Session = Depends(get_db)) -> KnowledgeRelationRead:
    relation = _relation(session, relation_id)
    try:
        before = curation.snapshot(relation)
        resolve_relation(session, relation, target_name=payload.target_name, target_type=payload.target_type)
        curation.record(session, relation, 'resolve_relation', before)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    paper = require_paper(session, relation.paper_id)
    candidates = session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.paper_id == relation.paper_id)).all()
    relations = session.scalars(select(KnowledgeRelation).where(KnowledgeRelation.paper_id == relation.paper_id)).all()
    paper.knowledge_status = paper_knowledge_status(candidates, relations)
    session.commit()
    return knowledge_relation_read(relation)


@router.post('/papers/{paper_id}/knowledge/paragraph', response_model=KnowledgePaperRead, status_code=202)
def extract_paragraph(paper_id: str, payload: dict, request: Request, session: Session = Depends(get_db)) -> KnowledgePaperRead:
    paper = require_paper(session, paper_id)
    paragraph_id = payload.get('paragraph_id') if isinstance(payload, dict) else None
    paragraph = next((item for item in paragraphs_for(paper) if item['id'] == paragraph_id), None)
    by_id = {item.id:item for item in paper.chunks}
    source_chunks = [by_id[paragraph_id]] if paragraph_id in by_id else []
    if paragraph is not None:
        refs = paragraph.get('refs') or paragraph.get('anchors') or []
        chunk_ids = dict.fromkeys(ref.get('chunk_id') for ref in refs if isinstance(ref, dict))
        source_chunks = [by_id[cid] for cid in chunk_ids if cid in by_id]
    if not source_chunks:
        raise HTTPException(404, '未找到要识别的段落')
    provider = get_model_provider()
    if provider.mode != 'remote' or not provider.configured:
        raise HTTPException(409, '请先在设置中选择可用的模型连接，再识别本段')
    result = provider.analyze(source_chunks)
    from ..services.knowledge import persist_candidates
    persist_candidates(session, paper, result.knowledge_candidates, result.knowledge_relations, run_id=f'paragraph-{uuid.uuid4().hex[:12]}')
    session.commit()
    return _paper_payload(session, paper_id)
