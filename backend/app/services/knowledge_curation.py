"""Canonical identity, review decisions and source-aware dossier projections."""
from __future__ import annotations

import json
import uuid
from urllib.parse import quote_plus

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import KnowledgeCandidate, KnowledgeChange, KnowledgeEntity, KnowledgeRelation, Paper
from .knowledge import _valid_evidence, normalize_name, paper_knowledge_status

ACCEPTED = {'confirmed', 'known', 'alias'}


def unpack(raw: str | None):
    return json.loads(raw or '[]')


def snapshot(row) -> dict:
    return {col.name: getattr(row, col.name) for col in row.__table__.columns if col.name not in {'created_at', 'updated_at'}}


def record(session: Session, row, action: str, before: dict) -> None:
    kind = 'entity' if isinstance(row, KnowledgeEntity) else 'candidate' if isinstance(row, KnowledgeCandidate) else 'relation'
    session.add(KnowledgeChange(id='kh-' + uuid.uuid4().hex, subject_type=kind, subject_id=row.id, action=action, before_json=json.dumps(before, ensure_ascii=False), after_json=json.dumps(snapshot(row), ensure_ascii=False)))


def entity_for(session: Session, entity_id: str) -> KnowledgeEntity:
    seen = set()
    while entity_id not in seen:
        seen.add(entity_id)
        entity = session.get(KnowledgeEntity, entity_id)
        if entity is None:
            raise HTTPException(404, '未找到这条知识对象')
        if not entity.merged_into_id:
            return entity
        entity_id = entity.merged_into_id
    raise HTTPException(409, '对象合并记录存在循环')


def unique_aliases(names: list[str], canonical: str) -> list[str]:
    seen = {normalize_name(canonical)}
    result = []
    for name in names:
        name = name.strip()
        key = normalize_name(name)
        if key and key not in seen:
            if len(name) > 300:
                raise HTTPException(422, '别名不能超过 300 个字符')
            seen.add(key)
            result.append(name)
    return result


def check_namespace(session: Session, kind: str, names: list[str], exclude: set[str]) -> None:
    wanted = {normalize_name(name) for name in names}
    if '' in wanted:
        raise HTTPException(422, '名称需要包含文字或数字')
    for other in session.scalars(select(KnowledgeEntity).where(KnowledgeEntity.entity_type == kind)).all():
        if other.id in exclude or other.merged_into_id:
            continue
        if wanted & {other.normalized_name, *(normalize_name(a) for a in unpack(other.aliases_json))}:
            raise HTTPException(409, f'名称或别名与「{other.name}」重复，请使用该对象或先合并重复项')


def edit_entity(session: Session, entity: KnowledgeEntity, payload) -> None:
    before = snapshot(entity)
    old_names = [entity.name] if normalize_name(entity.name) != normalize_name(payload.name) else []
    aliases = unique_aliases([*payload.aliases, *old_names], payload.name)
    check_namespace(session, payload.entity_type, [payload.name, *aliases], {entity.id})
    # Retire keys from legacy redirect rows before reusing a released name.
    for row in session.scalars(select(KnowledgeEntity).where(KnowledgeEntity.entity_type == payload.entity_type, KnowledgeEntity.normalized_name == normalize_name(payload.name))).all():
        if row.id != entity.id and row.merged_into_id:
            row.normalized_name = 'merged ' + row.id
    session.flush()
    entity.name = payload.name
    entity.normalized_name = normalize_name(payload.name)
    entity.entity_type = payload.entity_type
    entity.aliases_json = json.dumps(aliases, ensure_ascii=False)
    entity.description = (payload.description or '').strip() or None
    entity.links_json = json.dumps([{**link.model_dump(), 'source':'user'} for link in payload.links], ensure_ascii=False)
    record(session, entity, 'edit_entity', before)
    session.flush()


def merge_preview(session: Session, source: KnowledgeEntity, target: KnowledgeEntity) -> dict:
    if source.id == target.id:
        raise HTTPException(409, '请选择另一个对象')
    if source.entity_type != target.entity_type:
        raise HTTPException(409, '只能合并相同分类的对象；同名的数据集与评测应分别维护')
    aliases = unique_aliases([*unpack(target.aliases_json), source.name, *unpack(source.aliases_json)], target.name)
    check_namespace(session, target.entity_type, [target.name, *aliases], {source.id, target.id})
    candidates = session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.entity_id == source.id)).all()
    ids = [row.id for row in candidates]
    relations = session.scalars(select(KnowledgeRelation).where(or_(KnowledgeRelation.source_candidate_id.in_(ids), KnowledgeRelation.target_candidate_id.in_(ids)))).all()
    to_review = []
    for row in relations:
        a, b = endpoint(session, row, row.source_candidate_id), endpoint(session, row, row.target_candidate_id)
        if row.status != 'rejected' and a and b and a.entity_id in {source.id, target.id} and b.entity_id in {source.id, target.id}:
            to_review.append({'id':row.id, 'paper_id':row.paper_id, 'relation':row.relation, 'description':row.description})
    return {'source_id':source.id, 'source_name':source.name, 'source_description':source.description, 'target_id':target.id, 'target_name':target.name, 'target_description':target.description, 'candidate_count':len(candidates), 'paper_count':len({row.paper_id for row in candidates}), 'relation_count':len(relations), 'aliases':aliases, 'relations_to_review':to_review}


def merge_entity(session: Session, source: KnowledgeEntity, target: KnowledgeEntity) -> None:
    preview = merge_preview(session, source, target)
    before = {'source':snapshot(source), 'target':snapshot(target)}
    candidates = session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.entity_id == source.id)).all()
    for candidate in candidates:
        candidate.entity_id = target.id
        candidate.entity = target
    target.aliases_json = json.dumps(preview['aliases'], ensure_ascii=False)
    target.description = target.description or source.description
    links = [*unpack(target.links_json), *unpack(source.links_json)]
    target.links_json = json.dumps(list({link['url']:link for link in reversed(links)}.values())[::-1], ensure_ascii=False)
    source.status = 'merged'
    source.merged_into_id = target.id
    source.normalized_name = 'merged ' + source.id
    session.flush()
    for relation in session.scalars(select(KnowledgeRelation)).all():
        a = session.get(KnowledgeCandidate, relation.source_candidate_id) if relation.source_candidate_id else None
        b = session.get(KnowledgeCandidate, relation.target_candidate_id) if relation.target_candidate_id else None
        if a and b and a.entity_id == b.entity_id == target.id and relation.status != 'rejected':
            original = snapshot(relation)
            relation.status = 'conflict'
            record(session, relation, 'merge_relation_conflict', original)
            refresh_paper_status(session, relation.paper_id)
    record(session, target, 'merge_entity', before)
    record(session, source, 'merged_into', before['source'])


def refresh_paper_status(session: Session, paper_id: str) -> None:
    candidates = session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.paper_id == paper_id)).all()
    relations = session.scalars(select(KnowledgeRelation).where(KnowledgeRelation.paper_id == paper_id)).all()
    paper = session.get(Paper, paper_id)
    if paper:
        paper.knowledge_status = paper_knowledge_status(candidates, relations)


def endpoint(session: Session, relation: KnowledgeRelation, cid: str | None) -> KnowledgeCandidate | None:
    from .knowledge_identity import archived_row
    row = archived_row(session, KnowledgeCandidate, cid) if cid else None
    if row and row.paper_id == relation.paper_id:
        return row
    return None


def confirmable(session: Session, relation: KnowledgeRelation) -> bool:
    from .knowledge_identity import effective_kind, relation_endpoint_types
    ends = [endpoint(session, relation, cid) for cid in (relation.source_candidate_id, relation.target_candidate_id)]
    return bool(all(row and row.status in ACCEPTED and row.entity_id and row.entity and row.entity.status == 'active' for row in ends)
                and ends[0].entity_id != ends[1].entity_id
                and all(effective_kind(row) in relation_endpoint_types(relation.relation, target=bool(index))
                    for index, row in enumerate(ends))
                and _valid_evidence(relation.paper, unpack(relation.evidence_json)))


def review_relation(session: Session, relation: KnowledgeRelation, decision: str) -> None:
    before = snapshot(relation)
    if decision == 'confirm':
        if not confirmable(session, relation):
            raise HTTPException(409, '请先确认两个不同且类型符合关系语义的论文内对象，并检查这篇论文中的原文证据；被忽略的对象不能用于确认关系')
        relation.status = 'confirmed'
    elif decision == 'reject':
        relation.status = 'rejected'
    else:
        relation.status = 'candidate' if all(endpoint(session, relation, cid) for cid in (relation.source_candidate_id, relation.target_candidate_id)) else 'unresolved'
    record(session, relation, decision + '_relation', before)
    refresh_paper_status(session, relation.paper_id)


def edit_relation(session: Session, relation: KnowledgeRelation, payload, *, record_change: bool = True) -> None:
    from .knowledge_identity import effective_kind, relation_endpoint_types
    ends = [endpoint(session, relation, cid) for cid in (payload.source_candidate_id, payload.target_candidate_id)]
    if not all(ends):
        raise HTTPException(422, '关系两端必须来自证据所属的同一篇论文')
    a, b = ends
    if a.id == b.id or (a.entity_id and a.entity_id == b.entity_id):
        raise HTTPException(422, '关系需要连接两个不同的对象')
    if any(row.status == 'rejected' for row in ends):
        raise HTTPException(409, '请先恢复被忽略的对象')
    if any(effective_kind(row) not in relation_endpoint_types(payload.relation, target=bool(index))
            for index, row in enumerate(ends)):
        raise HTTPException(422, '关系两端的对象类型不符合该关系的语义')
    before = snapshot(relation)
    relation.source_candidate_id, relation.target_candidate_id = a.id, b.id
    relation.source_name, relation.target_name = a.name, b.name
    relation.source_normalized_name, relation.target_normalized_name = a.normalized_name, b.normalized_name
    relation.relation = payload.relation
    relation.description = (payload.description or '').strip() or None
    relation.status = 'candidate'
    if record_change:
        record(session, relation, 'edit_relation', before)
    refresh_paper_status(session, relation.paper_id)


def dossier(session: Session, entity: KnowledgeEntity):
    from .serialization import knowledge_entity_detail_read
    # Only explicit canonical identity qualifies an edge. A matching string is
    # not enough to tell a benchmark from a same-name dataset.
    candidates = session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.entity_id == entity.id, KnowledgeCandidate.status != 'rejected').order_by(KnowledgeCandidate.created_at, KnowledgeCandidate.id)).all()
    ids = {row.id for row in candidates}
    relations = session.scalars(select(KnowledgeRelation).where(or_(KnowledgeRelation.source_candidate_id.in_(ids), KnowledgeRelation.target_candidate_id.in_(ids))).order_by(KnowledgeRelation.created_at, KnowledgeRelation.id)).all()
    active_relations = [row for row in relations if row.status != 'rejected']
    pids = {row.paper_id for row in [*candidates, *active_relations]}
    paper_rows = {row.id:row for row in session.scalars(select(Paper).where(Paper.id.in_(pids))).all()}
    evidence = {}
    for row in [*candidates, *active_relations]:
        for item in unpack(row.evidence_json):
            evidence[(row.paper_id, item.get('chunk_id'), item.get('quote'))] = {**item, 'paper_id':row.paper_id, 'paper_title':paper_rows[row.paper_id].title}
    papers = []
    for pid in sorted(pids):
        rows = [row for row in candidates if row.paper_id == pid]
        rels = [row for row in active_relations if row.paper_id == pid]
        papers.append({'paper_id':pid, 'title':paper_rows[pid].title, 'role':rows[0].role if rows else 'related', 'status':'confirmed' if any(row.status in ACCEPTED for row in [*rows, *rels]) else 'candidate', 'evidence_count':sum(e['paper_id'] == pid for e in evidence.values())})
    known = {'react':('ReAct paper','https://arxiv.org/abs/2210.03629','paper'), 'hotpotqa':('HotPotQA','https://hotpotqa.github.io/','official'), 'fever':('FEVER','https://fever.ai/','official'), 'alfworld':('ALFWorld','https://alfworld.github.io/','official'), 'webshop':('WebShop','https://webshop-pnlp.github.io/','official')}
    links = unpack(entity.links_json)
    links_maintained = session.scalar(select(KnowledgeChange.id).where(KnowledgeChange.subject_id == entity.id, KnowledgeChange.subject_type == 'entity', KnowledgeChange.action == 'edit_entity').limit(1)) is not None
    if not links and not links_maintained and entity.normalized_name in known:
        label, url, kind = known[entity.normalized_name]
        links = [{'label':label, 'url':url, 'kind':kind, 'source':'curated'}]
    links = [*links, {'kind':'search', 'label':f'搜索 {entity.name}', 'url':f'https://duckduckgo.com/?q={quote_plus(entity.name)}', 'source':'search'}]
    detail = knowledge_entity_detail_read(entity, candidates=candidates, papers=papers, relations=relations, evidence=list(evidence.values()), links=links)
    changes = session.scalars(select(KnowledgeChange).where(KnowledgeChange.subject_id.in_([entity.id, *[row.id for row in relations]])).order_by(KnowledgeChange.created_at.desc(), KnowledgeChange.id.desc())).all()
    detail.history = [{'id':row.id, 'subject_type':row.subject_type, 'subject_id':row.subject_id, 'action':row.action, 'before':json.loads(row.before_json), 'after':json.loads(row.after_json), 'created_at':row.created_at.isoformat()} for row in changes]
    return detail
