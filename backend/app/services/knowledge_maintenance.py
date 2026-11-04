"""Evidence-first health checks and reversible maintenance proposals.

The service deliberately separates finding a problem from changing the graph.
Deterministic findings can be created without a model; model proposals are
validated by the same evidence and fingerprint gates before they are stored or
applied.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Collection,
    CollectionPaper,
    KnowledgeCandidate,
    KnowledgeChange,
    KnowledgeEntity,
    KnowledgeMaintenanceIssue,
    KnowledgeMaintenanceRun,
    KnowledgeRelation,
    Paper,
    PaperChunk,
)
from . import knowledge_curation as curation
from .knowledge import _valid_evidence, normalize_name
from .knowledge_identity import archived_row, effective_kind, reconcile_paper

SAFE_ACTIONS = {
    "reconcile_paper",
    "repair_evidence",
    "restore_relation",
}
REVIEW_ACTIONS = {
    "merge_entities",
    "split_entity",
    "rewrite_relation",
    "create_entity",
}
HUMAN_ACTIONS = {
    "confirm_candidate",
    "reject_candidate",
    "edit_entity",
    "edit_relation",
    "confirm_relation",
    "reject_relation",
    "restore_relation",
    "resolve_relation",
}


def _json(raw: str | None, fallback: Any):
    try:
        value = json.loads(raw or "")
        return value
    except (TypeError, json.JSONDecodeError):
        return fallback


def _json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_snapshot(row) -> dict:
    return curation.snapshot(row)


def _paper_ids(session: Session, scope_type: str = "library", scope_id: str | None = None, ids: Iterable[str] = ()) -> list[str]:
    wanted = {str(item) for item in ids if str(item).strip()}
    statement = select(Paper.id).where(Paper.is_demo == False)
    if scope_type == "papers":
        statement = statement.where(Paper.id.in_(wanted))
    if scope_type == "collection":
        statement = statement.join(CollectionPaper, CollectionPaper.paper_id == Paper.id).where(CollectionPaper.collection_id == scope_id)
    return sorted(session.scalars(statement).all())


def _paper_map(session: Session, paper_ids: Iterable[str]) -> dict[str, Paper]:
    ids = list(dict.fromkeys(paper_ids))
    if not ids:
        return {}
    return {row.id: row for row in session.scalars(select(Paper).where(Paper.id.in_(ids))).all()}


def _valid_rows(session: Session, paper_ids: Iterable[str]):
    ids = list(dict.fromkeys(paper_ids))
    if not ids:
        return [], []
    candidates = session.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.paper_id.in_(ids))).all()
    relations = session.scalars(select(KnowledgeRelation).where(KnowledgeRelation.paper_id.in_(ids))).all()
    return candidates, relations


def _valid_quote_count(row, papers: dict[str, Paper]) -> tuple[int, int]:
    paper = papers.get(row.paper_id)
    if paper is None:
        return 0, len(_json(row.evidence_json, []))
    raw = _json(row.evidence_json, [])
    return len(_valid_evidence(paper, raw)), len(raw) if isinstance(raw, list) else 0


def _evidence_needs_repair(row, papers: dict[str, Paper]) -> tuple[bool, list[dict]]:
    paper = papers.get(row.paper_id)
    raw = _json(row.evidence_json, [])
    if paper is None or not isinstance(raw, list):
        return False, []
    valid = _valid_evidence(paper, raw)
    if not valid or len(valid) != len(raw):
        return False, valid
    fields = ("chunk_id", "page", "section", "quote", "bbox", "page_width", "page_height")
    return any(any(item.get(field) != canonical.get(field) for field in fields) for item, canonical in zip(raw, valid)), valid


def _evidence_for(row, papers: dict[str, Paper], limit: int = 8) -> list[dict]:
    paper = papers.get(row.paper_id)
    title = paper.title if paper else row.paper_id
    evidence = _json(row.evidence_json, [])
    if not isinstance(evidence, list):
        return []
    return [{**item, "paper_id": row.paper_id, "paper_title": title}
            for item in evidence[:limit] if isinstance(item, dict) and item.get("quote")]


def scope_fingerprint(session: Session, paper_ids: Iterable[str]) -> str:
    ids = sorted(set(paper_ids))
    candidates, relations = _valid_rows(session, ids)
    entities = session.scalars(select(KnowledgeEntity).where(KnowledgeEntity.status == "active")).all()
    payload = {
        "papers": [
            {"id": paper.id, "updated_at": paper.updated_at.isoformat() if paper.updated_at else None}
            for paper in _paper_map(session, ids).values()
        ],
        "candidates": sorted((_row_snapshot(row) for row in candidates), key=lambda item: item.get("id", "")),
        "relations": sorted((_row_snapshot(row) for row in relations), key=lambda item: item.get("id", "")),
        "entities": sorted((_row_snapshot(row) for row in entities), key=lambda item: item.get("id", "")),
    }
    return hashlib.sha256(_dump(payload).encode("utf-8")).hexdigest()


def subjects_fingerprint(session: Session, subject_ids: Iterable[str], paper_ids: Iterable[str] = ()) -> str:
    values: list[dict] = []
    ids = set(subject_ids)
    for model in (KnowledgeEntity, KnowledgeCandidate, KnowledgeRelation):
        values.extend(_row_snapshot(row) for row in session.scalars(select(model).where(model.id.in_(ids))).all())
    if paper_ids:
        values.extend(_row_snapshot(row) for row in session.scalars(select(Paper).where(Paper.id.in_(set(paper_ids)))).all())
    encoded = _dump(sorted(values, key=lambda item: (str(item.get("id")), str(item.get("paper_id")))))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _human_changed(session: Session, subject_ids: Iterable[str]) -> bool:
    ids = list(subject_ids)
    if not ids:
        return False
    return session.scalar(select(KnowledgeChange.id).where(
        KnowledgeChange.subject_id.in_(ids), KnowledgeChange.action.in_(HUMAN_ACTIONS)
    ).limit(1)) is not None


def collect_deterministic_findings(session: Session, paper_ids: Iterable[str]) -> list[dict]:
    """Return source-grounded findings without contacting a provider."""
    ids = sorted(set(paper_ids))
    papers = _paper_map(session, ids)
    candidates, relations = _valid_rows(session, ids)
    findings: list[dict] = []

    by_candidate_key: dict[tuple[str, str, str], list[KnowledgeCandidate]] = defaultdict(list)
    for row in candidates:
        if row.status == "rejected":
            continue
        by_candidate_key[(row.paper_id, effective_kind(row), row.normalized_name)].append(row)
    for key, rows in by_candidate_key.items():
        if len(rows) < 2:
            continue
        subject_ids = [row.id for row in rows]
        evidence = [item for row in rows for item in _evidence_for(row, papers, 2)]
        findings.append({
            "kind": "identity", "severity": "warning", "subject_ids": subject_ids,
            "paper_ids": [key[0]], "evidence": evidence,
            "summary": f"同一篇论文中存在 {len(rows)} 条相同对象记录",
            "reasoning": "对象分类和规范化名称完全一致，可以先按论文内身份规则合并并保留全部证据。",
            "proposed_action": {"type": "reconcile_paper", "paper_id": key[0]},
            "confidence": 1.0, "confidence_basis": {"deterministic": True, "exact_identity": True},
            "auto_eligible": not _human_changed(session, subject_ids),
        })

    relation_groups: dict[tuple, list[KnowledgeRelation]] = defaultdict(list)
    for row in relations:
        if row.status == "rejected":
            continue
        relation_groups[(row.paper_id, row.relation, row.source_candidate_id, row.target_candidate_id)].append(row)
    for key, rows in relation_groups.items():
        if len(rows) < 2:
            continue
        subject_ids = [row.id for row in rows]
        findings.append({
            "kind": "relation", "severity": "warning", "subject_ids": subject_ids,
            "paper_ids": [key[0]], "evidence": [item for row in rows for item in _evidence_for(row, papers, 2)],
            "summary": "同一条关系被重复保存",
            "reasoning": "关系谓词和两个论文内端点完全一致，合并可以减少重复边并保留每条原文证据。",
            "proposed_action": {"type": "reconcile_paper", "paper_id": key[0]},
            "confidence": 1.0, "confidence_basis": {"deterministic": True, "same_relation_key": True},
            "auto_eligible": not _human_changed(session, subject_ids),
        })

    by_paper = {paper_id: paper for paper_id, paper in papers.items()}
    for row in [*candidates, *relations]:
        valid_count, raw_count = _valid_quote_count(row, by_paper)
        needs_repair, canonical_evidence = _evidence_needs_repair(row, by_paper)
        if raw_count and valid_count == raw_count and not needs_repair:
            continue
        if raw_count and valid_count:
            findings.append({
                "kind": "evidence", "severity": "warning", "subject_ids": [row.id],
                "paper_ids": [row.paper_id], "evidence": _evidence_for(row, papers),
                "summary": "部分证据定位已过期，但原句仍可在论文中验证",
                "reasoning": "原文引用仍存在，只需要按当前 chunk 的页码和坐标重新规范化定位。",
                "proposed_action": {"type": "repair_evidence", "subject_type": "relation" if isinstance(row, KnowledgeRelation) else "candidate", "subject_id": row.id},
                "confidence": 1.0, "confidence_basis": {"deterministic": True, "valid_quote_count": valid_count, "raw_quote_count": raw_count},
                "auto_eligible": not _human_changed(session, [row.id]),
            })
        elif raw_count:
            findings.append({
                "kind": "evidence", "severity": "critical", "subject_ids": [row.id],
                "paper_ids": [row.paper_id], "evidence": _evidence_for(row, papers),
                "summary": "知识对象包含无法在当前论文中核验的证据",
                "reasoning": "引用缺少有效原文，系统不会自动替换或删除它，需要重新摄取或人工确认。",
                "proposed_action": {"type": "review_evidence", "subject_id": row.id},
                "confidence": 1.0, "confidence_basis": {"deterministic": True, "valid_quote_count": 0, "raw_quote_count": raw_count},
                "auto_eligible": False,
            })

    by_id = {row.id: row for row in candidates}
    for row in relations:
        ends = [by_id.get(row.source_candidate_id), by_id.get(row.target_candidate_id)]
        if row.status == "rejected":
            continue
        missing = [end is None for end in ends]
        rejected = [end is not None and end.status == "rejected" for end in ends]
        if not (any(missing) or any(rejected)):
            continue
        findings.append({
            "kind": "relation", "severity": "critical" if any(rejected) else "warning", "subject_ids": [row.id],
            "paper_ids": [row.paper_id], "evidence": _evidence_for(row, papers),
            "summary": "关系端点悬空或已被忽略",
            "reasoning": "关系不能稳定指向两个有效的论文内对象；先尝试论文内确定性重连，否则保留为待审关系。",
            "proposed_action": {"type": "reconcile_paper", "paper_id": row.paper_id},
            "confidence": 0.96 if any(missing) and not any(rejected) else 1.0,
            "confidence_basis": {"deterministic": True, "missing_endpoint": any(missing), "rejected_endpoint": any(rejected)},
            "auto_eligible": any(missing) and not any(rejected) and not _human_changed(session, [row.id]),
        })

    entities = session.scalars(select(KnowledgeEntity).where(KnowledgeEntity.status == "active")).all()
    alias_owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entity in entities:
        for alias in _json(entity.aliases_json, []):
            key = (entity.entity_type, normalize_name(alias))
            if key[1]:
                alias_owners[key].add(entity.id)
    for (kind, alias), owners in alias_owners.items():
        if len(owners) < 2 or len(alias) < 4:
            continue
        findings.append({
            "kind": "identity", "severity": "warning", "subject_ids": sorted(owners), "paper_ids": [], "evidence": [],
            "summary": f"{kind} 分类中的别名 {alias} 指向多个对象",
            "reasoning": "该别名可能造成跨论文误连，系统不会根据它自动合并，需要确认对象语义。",
            "proposed_action": {"type": "review_alias_collision", "alias": alias, "entity_ids": sorted(owners)},
            "confidence": 1.0, "confidence_basis": {"deterministic": True, "ambiguous_alias": True}, "auto_eligible": False,
        })

    return findings


def confidence_gate(session: Session, finding: dict, *, source_fingerprint: str | None = None) -> dict:
    action = (finding.get("proposed_action") or {}).get("type")
    evidence = finding.get("evidence") if isinstance(finding.get("evidence"), list) else []
    subjects = [str(item) for item in finding.get("subject_ids", [])]
    basis = dict(finding.get("confidence_basis") or {})
    deterministic = bool(basis.get("deterministic"))
    valid_quotes = len({(item.get("paper_id"), item.get("chunk_id"), item.get("quote")) for item in evidence if item.get("quote")})
    allowed = action in SAFE_ACTIONS
    human = _human_changed(session, subjects)
    rejected = any(
        (row := session.get(model, subject)) is not None and getattr(row, "status", None) == "rejected"
        for model in (KnowledgeCandidate, KnowledgeRelation)
        for subject in subjects
    )
    strong = deterministic or (float(finding.get("confidence") or 0) >= 0.94 and valid_quotes >= 2 and not basis.get("conflict"))
    eligible = bool(allowed and strong and not human and not rejected and (source_fingerprint is None or finding.get("source_fingerprint") in {None, source_fingerprint}))
    if not allowed:
        reason = "该动作涉及语义合并、拆分或关系改写，需要人工确认"
    elif human:
        reason = "对象存在人工修改，自动修复不能覆盖研究者决定"
    elif rejected:
        reason = "对象或关系已被忽略，不能自动恢复"
    elif not strong:
        reason = "证据数量或一致性不足，暂存为待审建议"
    else:
        reason = "动作属于安全范围，原文证据和当前记录均未发生冲突"
    return {"auto_eligible": eligible, "confidence_basis": {**basis, "valid_evidence_count": valid_quotes, "human_change": human, "rejected_subject": rejected, "reason": reason}}


def make_issue(session: Session, run: KnowledgeMaintenanceRun, finding: dict) -> KnowledgeMaintenanceIssue:
    gate = confidence_gate(session, finding, source_fingerprint=run.source_fingerprint)
    subject_ids = list(dict.fromkeys(finding.get("subject_ids", [])))
    paper_ids = list(dict.fromkeys(finding.get("paper_ids", [])))
    issue_fingerprint = subjects_fingerprint(session, subject_ids, paper_ids) if subject_ids or paper_ids else run.source_fingerprint
    issue = KnowledgeMaintenanceIssue(
        id="kmi-" + uuid.uuid4().hex[:24], run_id=run.id, kind=finding["kind"],
        severity=finding.get("severity", "info"), status="proposed" if not gate["auto_eligible"] else "proposed",
        confidence=max(0.0, min(1.0, float(finding.get("confidence") or 0))),
        confidence_basis_json=_dump(gate["confidence_basis"]), auto_eligible=gate["auto_eligible"],
        subject_ids_json=_dump(subject_ids),
        evidence_json=_dump(finding.get("evidence", [])), external_leads_json=_dump(finding.get("external_leads", [])),
        summary=str(finding.get("summary") or "知识网络存在待检查问题"),
        reasoning=str(finding.get("reasoning") or "请根据原文证据确认"),
        proposed_action_json=_dump(finding.get("proposed_action") or {}),
        source_fingerprint=issue_fingerprint,
    )
    session.add(issue)
    return issue


def build_model_bundle(session: Session, finding: dict) -> dict:
    """Assemble one bounded one-hop neighborhood for a provider call."""
    subject_ids = [str(item) for item in finding.get("subject_ids", [])][:20]
    rows = _subject_rows_from_ids(session, subject_ids)
    paper_ids = set(finding.get("paper_ids", []))
    paper_ids.update(row.paper_id for row in rows if hasattr(row, "paper_id"))
    papers = _paper_map(session, paper_ids)
    candidate_ids = {row.id for row in rows if isinstance(row, KnowledgeCandidate)}
    for relation in session.scalars(select(KnowledgeRelation).where(
        or_(KnowledgeRelation.source_candidate_id.in_(candidate_ids), KnowledgeRelation.target_candidate_id.in_(candidate_ids))
    ).limit(20)).all() if candidate_ids else []:
        rows.append(relation)
        paper_ids.add(relation.paper_id)
    chunks = []
    seen_chunks = set()
    for row in rows:
        paper = papers.get(getattr(row, "paper_id", None))
        if paper is None:
            continue
        for evidence in _json(row.evidence_json, [])[:4]:
            chunk = next((item for item in paper.chunks if item.id == evidence.get("chunk_id")), None)
            if chunk is not None and chunk.id not in seen_chunks:
                seen_chunks.add(chunk.id)
                chunks.append({"chunk_id": chunk.id, "paper_id": paper.id, "page": chunk.page, "section": chunk.section, "content": chunk.content[:4000]})
    if len(chunks) < 12:
        for paper in papers.values():
            for chunk in paper.chunks:
                if chunk.id in seen_chunks:
                    continue
                seen_chunks.add(chunk.id)
                chunks.append({"chunk_id": chunk.id, "paper_id": paper.id, "page": chunk.page, "section": chunk.section, "content": chunk.content[:4000]})
                if len(chunks) >= 12:
                    break
            if len(chunks) >= 12:
                break
    return {
        "subject_ids": subject_ids,
        "finding": {key: finding.get(key) for key in ("kind", "summary", "reasoning", "proposed_action")},
        "subjects": [_subject_payload(row) for row in rows[:20]],
        "chunks": chunks,
    }


def _subject_rows_from_ids(session: Session, ids: Iterable[str]) -> list[Any]:
    values = list(dict.fromkeys(str(item) for item in ids))
    rows: list[Any] = []
    for model in (KnowledgeEntity, KnowledgeCandidate, KnowledgeRelation):
        rows.extend(session.scalars(select(model).where(model.id.in_(values))).all())
    return rows


def _subject_payload(row) -> dict:
    payload = {key: value for key, value in _row_snapshot(row).items() if key in {
        "id", "paper_id", "entity_id", "entity_type", "name", "normalized_name", "aliases_json", "role", "status",
        "relation", "source_name", "source_normalized_name", "target_name", "target_normalized_name",
        "source_candidate_id", "target_candidate_id", "description", "confidence",
    }}
    if "aliases_json" in payload:
        payload["aliases"] = _json(payload.pop("aliases_json"), [])
    payload.pop("evidence_json", None)
    return payload


def store_model_proposals(session: Session, run: KnowledgeMaintenanceRun, finding: dict, result: dict) -> list[KnowledgeMaintenanceIssue]:
    """Validate provider proposals and turn them into reviewable issues."""
    proposals = result.get("issues", []) if isinstance(result, dict) else []
    if not isinstance(proposals, list):
        return []
    bundle = build_model_bundle(session, finding)
    chunks = {item["chunk_id"]: item for item in bundle["chunks"]}
    papers = _paper_map(session, {item["paper_id"] for item in bundle["chunks"]})
    existing = {
        (issue.kind, tuple(_json(issue.subject_ids_json, [])), _json(issue.proposed_action_json, {}).get("type"))
        for issue in run.issues
    }
    stored = []
    for proposal in proposals[:12]:
        if not isinstance(proposal, dict):
            continue
        citations = []
        for citation in proposal.get("citations", []) if isinstance(proposal.get("citations"), list) else []:
            chunk = chunks.get(citation.get("chunk_id")) if isinstance(citation, dict) else None
            if chunk is None:
                continue
            paper = papers.get(chunk["paper_id"])
            if paper is None:
                continue
            valid = _valid_evidence(paper, [{"chunk_id": chunk["chunk_id"], "quote": citation.get("quote")}])
            citations.extend([{**item, "paper_id": paper.id, "paper_title": paper.title} for item in valid])
        action = proposal.get("action") if isinstance(proposal.get("action"), dict) else {}
        action_type = action.get("type")
        if action_type not in SAFE_ACTIONS | REVIEW_ACTIONS | {"review_evidence", "review_alias_collision"}:
            action = {"type": "review_structure"}
        subjects = [str(item) for item in proposal.get("subject_ids", [])]
        kind = proposal.get("kind") if proposal.get("kind") in {"identity", "relation", "evidence", "coverage", "importance", "structure"} else finding.get("kind", "structure")
        key = (kind, tuple(subjects), action.get("type"))
        if key in existing:
            continue
        model_finding = {
            "kind": kind, "severity": "warning", "subject_ids": subjects,
            "paper_ids": list({item["paper_id"] for item in citations}), "evidence": citations,
            "summary": proposal.get("summary") or finding.get("summary") or "模型发现待检查问题",
            "reasoning": proposal.get("reasoning") or "模型建议需要根据原文证据复核",
            "proposed_action": action, "confidence": proposal.get("confidence", 0),
            "confidence_basis": proposal.get("confidence_factors") if isinstance(proposal.get("confidence_factors"), dict) else {},
            "external_leads": [{"query": query, "source": "model", "status": "unfetched"} for query in proposal.get("external_queries", []) if isinstance(query, str)],
        }
        stored.append(make_issue(session, run, model_finding))
        existing.add(key)
    session.flush()
    _refresh_run_counts(session, run)
    return stored


def _subject_rows(session: Session, issue: KnowledgeMaintenanceIssue) -> list[Any]:
    ids = _json(issue.subject_ids_json, [])
    rows: list[Any] = []
    for model in (KnowledgeEntity, KnowledgeCandidate, KnowledgeRelation):
        rows.extend(session.scalars(select(model).where(model.id.in_(ids))).all())
    return rows


def _refresh_run_counts(session: Session, run: KnowledgeMaintenanceRun) -> None:
    # Test queries do not autoflush in this local-first session factory. Flush
    # newly created issues before deriving the counts returned to the UI.
    session.flush()
    issues = list(session.scalars(select(KnowledgeMaintenanceIssue).where(KnowledgeMaintenanceIssue.run_id == run.id)).all())
    run.safe_count = sum(bool(row.auto_eligible and row.status == "proposed") for row in issues)
    run.review_count = sum(row.status in {"proposed", "needs_review"} and not row.auto_eligible
        and not (row.status == 'proposed' and _json(row.proposed_action_json, {}).get('type') == 'curate_paper') for row in issues)
    run.conflict_count = sum(row.severity == "critical" for row in issues if row.status not in {"rejected", "undone"})
    run.applied_count = sum(row.status in {"auto_applied", "accepted"} for row in issues)


def _repair_evidence(session: Session, issue: KnowledgeMaintenanceIssue, action: dict) -> list[str]:
    model = KnowledgeRelation if action.get("subject_type") == "relation" else KnowledgeCandidate
    row = archived_row(session, model, str(action.get("subject_id")))
    if row is None:
        raise HTTPException(409, "证据对象已不存在，无法自动修复")
    paper = session.get(Paper, row.paper_id)
    valid = _valid_evidence(paper, _json(row.evidence_json, [])) if paper else []
    if not valid:
        raise HTTPException(409, "当前论文中没有可验证的原文证据")
    before = _row_snapshot(row)
    row.evidence_json = _dump(valid)
    curation.record(session, row, "maintenance_repair_evidence", before)
    session.flush()
    return [change.id for change in session.scalars(select(KnowledgeChange).where(KnowledgeChange.subject_id == row.id, KnowledgeChange.action == "maintenance_repair_evidence")).all()]


def apply_issue(session: Session, issue: KnowledgeMaintenanceIssue, *, force: bool = False) -> KnowledgeMaintenanceIssue:
    if issue.status not in {"proposed", "needs_review"}:
        raise HTTPException(409, "这条维护建议当前不能应用")
    action = _json(issue.proposed_action_json, {})
    action_type = action.get("type")
    if not issue.auto_eligible and not force:
        raise HTTPException(409, "这条建议需要人工确认后才能应用")
    subjects = _json(issue.subject_ids_json, [])
    subject_rows = _subject_rows(session, issue)
    paper_ids = [action["paper_id"]] if action.get("paper_id") else [row.paper_id for row in subject_rows if hasattr(row, "paper_id")]
    current = subjects_fingerprint(session, subjects, paper_ids)
    if current != issue.source_fingerprint and not force:
        issue.status = "stale"
        raise HTTPException(409, "知识网络已发生变化，请重新运行体检")
    before_changes = {row.id for row in session.scalars(select(KnowledgeChange)).all()}
    if action_type == "reconcile_paper":
        paper = session.get(Paper, action.get("paper_id"))
        if paper is None:
            raise HTTPException(404, "论文不存在，无法重建关系")
        reconcile_paper(session, paper)
    elif action_type == "repair_evidence":
        _repair_evidence(session, issue, action)
    elif action_type == "restore_relation":
        relation = archived_row(session, KnowledgeRelation, action.get("relation_id"))
        if relation is None or not curation.confirmable(session, relation):
            raise HTTPException(409, "关系仍缺少两个可确认端点或有效证据")
        before = _row_snapshot(relation)
        relation.status = "confirmed"
        curation.record(session, relation, "maintenance_restore_relation", before)
    else:
        raise HTTPException(409, "该动作只能人工审阅，不能自动应用")
    session.flush()
    changes = [row.id for row in session.scalars(select(KnowledgeChange)).all() if row.id not in before_changes]
    issue.applied_change_ids_json = _dump(changes)
    issue.status = "auto_applied" if issue.auto_eligible and not force else "accepted"
    issue.updated_at = _now()
    run = session.get(KnowledgeMaintenanceRun, issue.run_id)
    if run:
        _refresh_run_counts(session, run)
    session.flush()
    return issue


def _restore_change(session: Session, change: KnowledgeChange) -> None:
    snapshots = _json(change.before_json, {})
    if change.action == "merge_entity" and isinstance(snapshots, dict) and "source" in snapshots:
        for item in (snapshots.get("source"), snapshots.get("target")):
            if not isinstance(item, dict):
                continue
            row = session.get(KnowledgeEntity, item.get("id"))
            if row is None:
                row = KnowledgeEntity(**{key: value for key, value in item.items() if key in {column.name for column in KnowledgeEntity.__table__.columns} and key not in {"created_at", "updated_at"}})
                session.add(row)
            else:
                for key, value in item.items():
                    if key in {column.name for column in KnowledgeEntity.__table__.columns}:
                        setattr(row, key, value)
        return
    model = KnowledgeEntity if change.subject_type == "entity" else KnowledgeCandidate if change.subject_type == "candidate" else KnowledgeRelation
    item = snapshots if isinstance(snapshots, dict) else {}
    row = session.get(model, change.subject_id)
    if row is None and change.action == "duplicate_archived" and item.get("id"):
        values = {key: value for key, value in item.items() if key in {column.name for column in model.__table__.columns} and key not in {"created_at", "updated_at"}}
        row = model(**values)
        session.add(row)
    if row is not None:
        for key, value in item.items():
            if key in {column.name for column in model.__table__.columns}:
                setattr(row, key, value)


def undo_issue(session: Session, issue: KnowledgeMaintenanceIssue) -> KnowledgeMaintenanceIssue:
    if issue.status not in {"auto_applied", "accepted"}:
        raise HTTPException(409, "这条维护建议没有可撤销的应用记录")
    change_ids = _json(issue.applied_change_ids_json, [])
    if _json(issue.proposed_action_json, {}).get('type') == 'curate_paper':
        from .knowledge_steward import undo_changes
        undo_changes(session, change_ids)
        issue.status = 'undone'
        issue.updated_at = _now()
        run = session.get(KnowledgeMaintenanceRun, issue.run_id)
        if run:
            _refresh_run_counts(session, run)
        return issue
    changes = list(session.scalars(select(KnowledgeChange).where(KnowledgeChange.id.in_(change_ids))).all())
    if not changes:
        raise HTTPException(409, "找不到这条建议的变更快照")
    for row in _subject_rows(session, issue):
        if row is not None and row.id and row.id in _json(issue.subject_ids_json, []):
            current = _row_snapshot(row)
            if current.get("updated_at") is not None:
                pass
    for change in sorted(changes, key=lambda item: (item.created_at or _now(), item.id), reverse=True):
        _restore_change(session, change)
    issue.status = "undone"
    issue.updated_at = _now()
    run = session.get(KnowledgeMaintenanceRun, issue.run_id)
    if run:
        _refresh_run_counts(session, run)
    session.flush()
    return issue


def serialize_issue(issue: KnowledgeMaintenanceIssue) -> dict:
    return {
        "id": issue.id, "run_id": issue.run_id, "kind": issue.kind, "severity": issue.severity,
        "status": issue.status, "confidence": issue.confidence, "confidence_basis": _json(issue.confidence_basis_json, {}),
        "auto_eligible": issue.auto_eligible, "subject_ids": _json(issue.subject_ids_json, []),
        "evidence": _json(issue.evidence_json, []), "external_leads": _json(issue.external_leads_json, []),
        "summary": issue.summary, "reasoning": issue.reasoning, "proposed_action": _json(issue.proposed_action_json, {}),
        "source_fingerprint": issue.source_fingerprint, "applied_change_ids": _json(issue.applied_change_ids_json, []),
        "created_at": issue.created_at, "updated_at": issue.updated_at,
    }


def serialize_run(run: KnowledgeMaintenanceRun) -> dict:
    return {
        "id": run.id, "scope_type": run.scope_type, "scope_id": run.scope_id, "status": run.status,
        "allow_external": run.allow_external, "model_name": run.model_name, "prompt_version": run.prompt_version,
        "source_fingerprint": run.source_fingerprint, "started_at": run.started_at, "finished_at": run.finished_at,
        "error_message": run.error_message, "safe_count": run.safe_count, "review_count": run.review_count,
        "conflict_count": run.conflict_count, "applied_count": run.applied_count, "usage": _json(run.usage_json, {}),
    }


def backlog(session: Session, *, scope_type='library', scope_id=None, paper_ids=()) -> dict:
    """Current scope work across batches, counted once per paper, without PDFs."""
    selected = _paper_ids(session, scope_type, scope_id, paper_ids)
    papers = session.execute(select(Paper.id, Paper.title).where(
        Paper.id.in_(selected), Paper.id.in_(select(PaperChunk.paper_id).distinct()))).all()
    ids = {p.id for p in papers}
    counts = {key: defaultdict(int) for key in ('objects', 'relations')}
    for key, model in (('objects', KnowledgeCandidate), ('relations', KnowledgeRelation)):
        for pid, count in session.execute(select(model.paper_id, func.count()).where(
                model.paper_id.in_(ids), ~model.status.in_(['confirmed','known','alias','rejected']),
                model.evidence_json != '[]').group_by(model.paper_id)):
            counts[key][pid] = count
    work = defaultdict(list)
    for issue, run in session.execute(select(KnowledgeMaintenanceIssue, KnowledgeMaintenanceRun).join(
            KnowledgeMaintenanceRun, KnowledgeMaintenanceRun.id == KnowledgeMaintenanceIssue.run_id)
            .order_by(KnowledgeMaintenanceIssue.created_at.desc())):
        action = _json(issue.proposed_action_json, {})
        if action.get('type') == 'curate_paper' and action.get('paper_id') in ids:
            work[action['paper_id']].append((issue, run))
    items, checked = [], 0
    rank = {'running': 0, 'queued': 1, 'retry_wait': 2, 'failed': 3, 'untracked': 4, 'needs_review': 5}
    for paper in papers:
        pending_objects, pending_relations = counts['objects'][paper.id], counts['relations'][paper.id]
        state, job_id, error, success = None, None, None, False
        for issue, run in work[paper.id]:
            if issue.status in {'accepted','auto_applied'}:
                success = True
            if issue.status == 'proposed' and run.status in {'queued','running','partial'}:
                usage = _json(run.usage_json, {})
                candidate = ('running' if run.status == 'running' and issue.id in
                    {*usage.get('active_issue_ids', []), usage.get('active_issue_id')} else 'retry_wait'
                    if usage.get('retry_at', {}).get(issue.id, 0) > _now().timestamp() else 'queued')
                if state is None or rank[candidate] < rank[state]:
                    state, job_id = candidate, run.id
                    # A batch error may belong to a different paper. Only show
                    # it on an issue that actually has a recorded failed attempt.
                    error = run.error_message if usage.get('attempts', {}).get(issue.id, 0) else None
            elif issue.status == 'needs_review' and run.status != 'cancelled' and state is None and not success:
                state, job_id, error = 'failed', run.id, issue.reasoning
        checked += int(success)
        if state is None:
            state = 'needs_review' if success and (pending_objects or pending_relations) else 'untracked' if not success else None
        if state is not None:
            items.append(dict(paper_id=paper.id, title=paper.title, status=state, run_id=job_id,
                pending_objects=pending_objects, pending_relations=pending_relations, error=error))
    items.sort(key=lambda item: (rank[item['status']], item['title'].casefold()))
    return dict(pending_papers=sum(i['status'] != 'needs_review' for i in items),
        review_papers=sum(i['status'] == 'needs_review' for i in items), checked_papers=checked,
        pending_objects=sum(counts['objects'].values()), pending_relations=sum(counts['relations'].values()), items=items)


def prepare_run(session: Session, *, scope_type: str = "library", scope_id: str | None = None,
                paper_ids: Iterable[str] = (), allow_external: bool = False, force: bool = False) -> KnowledgeMaintenanceRun:
    selected = _paper_ids(session, scope_type, scope_id, paper_ids)
    if not selected:
        raise HTTPException(409, "当前范围没有可体检的论文")
    if scope_type == "collection" and not session.get(Collection, scope_id):
        raise HTTPException(404, "专题不存在")
    if not force and scope_type == 'papers':
        # Queued jobs read the latest snapshot; another extraction must not
        # create a second owner of the same pending paper work.
        active = session.scalars(select(KnowledgeMaintenanceRun).where(
            KnowledgeMaintenanceRun.scope_type == 'papers',
            KnowledgeMaintenanceRun.status.in_(['queued','partial']))
            .order_by(KnowledgeMaintenanceRun.created_at)).all()
        for previous_run in active:
            wanted = {_json(i.proposed_action_json, {}).get('paper_id')
                      for i in pending_audit_issues(session, previous_run)}
            if wanted == set(selected):
                return previous_run
    fingerprint = scope_fingerprint(session, selected)
    if not force:
        existing = session.scalar(select(KnowledgeMaintenanceRun).where(
            KnowledgeMaintenanceRun.scope_type == scope_type,
            KnowledgeMaintenanceRun.scope_id == scope_id,
            KnowledgeMaintenanceRun.source_fingerprint == fingerprint,
            KnowledgeMaintenanceRun.status.in_(["queued", "running", "complete", "partial"]),
        ).order_by(KnowledgeMaintenanceRun.created_at.desc()))
        from .knowledge_steward import VERSION
        if existing is not None and _json(existing.usage_json, {}).get('curation_version') == VERSION:
            return existing
    run = KnowledgeMaintenanceRun(
        id="kmr-" + uuid.uuid4().hex[:24], scope_type=scope_type, scope_id=scope_id,
        status="queued", allow_external=allow_external, source_fingerprint=fingerprint,
        usage_json=_dump({"paper_count": len(selected), "call_times": [], "events": []}),
    )
    session.add(run)
    session.flush()
    audit_ids = []
    from .knowledge_steward import VERSION, fingerprint as paper_fingerprint
    # One body-text audit per changed paper. Local findings remain diagnostic
    # context, rather than consuming one model call per dangling relation.
    for paper in _paper_map(session, selected).values():
        current = paper_fingerprint(paper)
        previous = session.scalars(select(KnowledgeMaintenanceIssue).where(
            KnowledgeMaintenanceIssue.status.in_(['accepted', 'auto_applied']))).all()
        if not force and any((action := _json(item.proposed_action_json, {})).get('type') == 'curate_paper'
                and action.get('paper_id') == paper.id and action.get('version') == VERSION
                and action.get('result_fingerprint') == current for item in previous):
            continue
        finding = {'kind': 'coverage', 'summary': paper.title, 'reasoning': '阅读正文，补全核心对象、核验关系并连接已有知识',
            'paper_ids': [paper.id], 'subject_ids': [], 'confidence': 0,
            'proposed_action': {'type': 'curate_paper', 'paper_id': paper.id, 'version': VERSION}}
        issue = make_issue(session, run, finding)
        audit_ids.append(issue.id)
    run.usage_json = _dump({**_json(run.usage_json, {}), 'audit_issue_ids': audit_ids, 'forced': force, 'curation_version': VERSION})
    _refresh_run_counts(session, run)
    session.flush()
    return run


def enqueue_after_analysis(session: Session, paper: Paper) -> None:
    from ..models import ResearchControl
    control = session.get(ResearchControl, 1)
    settings = _json(control.settings_json, {}) if control else {}
    if settings.get('enabled') and settings.get('maintenance_enabled') and paper.chunks:
        session.flush()
        prepare_run(session, scope_type='papers', paper_ids=[paper.id], allow_external=True)


def _upgrade_run(session: Session, run: KnowledgeMaintenanceRun) -> None:
    usage = _json(run.usage_json, {})
    from .knowledge_steward import VERSION
    if usage.get('curation_version') != VERSION:
        legacy = list(session.scalars(select(KnowledgeMaintenanceIssue).where(KnowledgeMaintenanceIssue.run_id == run.id)))
        selected = _paper_ids(session, run.scope_type, run.scope_id) if run.scope_type != 'papers' else sorted({
            action['paper_id'] for item in legacy if (action := _json(item.proposed_action_json, {})).get('paper_id')})
        ids = []
        if not selected:
            run.status = 'failed'
            run.error_message = '旧整理批次未保存论文范围，请从当前专题重新发起整理；旧记录已保留'
            run.finished_at = _now()
            return
        for paper in _paper_map(session, selected).values():
            issue = make_issue(session, run, {'kind':'coverage','summary':paper.title,
                'reasoning':'按正文重新检查核心对象与关系','paper_ids':[paper.id],
                'proposed_action':{'type':'curate_paper','paper_id':paper.id,'version':VERSION}})
            ids.append(issue.id)
        for item in legacy:
            if item.id in usage.get('audit_issue_ids', []) and item.status == 'proposed':
                item.status = 'stale'
                item.reasoning = '已由逐篇正文整理接替；原始检查记录保留'
        usage.update(curation_version=VERSION, audit_issue_ids=ids, processed_issue_ids=[])
        run.usage_json = _dump(usage)
        session.flush()


def pending_audit_issues(session: Session, run: KnowledgeMaintenanceRun) -> list[KnowledgeMaintenanceIssue]:
    usage = _json(run.usage_json, {})
    processed = set(usage.get('processed_issue_ids', []))
    rows = list(session.scalars(select(KnowledgeMaintenanceIssue).where(
        KnowledgeMaintenanceIssue.run_id == run.id).order_by(KnowledgeMaintenanceIssue.created_at, KnowledgeMaintenanceIssue.id)).all())
    original = set(usage.get('audit_issue_ids', [])) if 'audit_issue_ids' in usage else {
        row.id for row in rows if _json(row.confidence_basis_json, {}).get('deterministic')}
    return [row for row in rows if row.id in original and row.id not in processed and row.status == 'proposed']


def ready_audit_issues(session: Session, run: KnowledgeMaintenanceRun) -> list[KnowledgeMaintenanceIssue]:
    retry = _json(run.usage_json, {}).get('retry_at', {})
    return [item for item in pending_audit_issues(session, run) if retry.get(item.id, 0) <= _now().timestamp()]


def skip_demo_audits(session: Session, run: KnowledgeMaintenanceRun) -> None:
    """Retire hidden examples left in older batches without deleting records."""
    usage = _json(run.usage_json, {})
    processed = set(usage.get('processed_issue_ids', []))
    for issue in pending_audit_issues(session, run):
        action = _json(issue.proposed_action_json, {})
        paper = session.get(Paper, action.get('paper_id')) if action.get('type') == 'curate_paper' else None
        if paper is not None and paper.is_demo:
            issue.status, issue.reasoning = 'stale', '示例论文不参与自动知识整理，原记录已保留'
            processed.add(issue.id)
    usage['processed_issue_ids'] = sorted(processed)
    run.usage_json = _dump(usage)
    session.flush()


def execute_run(session: Session, run: KnowledgeMaintenanceRun, provider=None, *, max_calls: int | None = None,
                issue_id=None, checkpoint_lock=None, preflight_call=None) -> KnowledgeMaintenanceRun:
    """Serialize checkpoints, releasing the lock only during model generation.

    An issue lease belongs to the worker, not this session. Different papers in
    one batch can run together; refreshed usage merges their independent results.
    """
    from contextlib import nullcontext
    with checkpoint_lock if checkpoint_lock is not None else nullcontext():
        if checkpoint_lock is not None:
            session.rollback()
            session.expire_all()
            if run.status not in {'queued', 'partial', 'running'}:
                return run
        result = _execute_run(session, run, provider, max_calls=max_calls, issue_id=issue_id,
                              checkpoint_lock=checkpoint_lock, preflight_call=preflight_call)
        if checkpoint_lock is not None:
            session.commit()
        return result


def _execute_run(session, run, provider, *, max_calls, issue_id, checkpoint_lock, preflight_call):
    """Run the model stage for a prepared batch; local findings always survive."""
    from ..providers.base import ProviderError

    _upgrade_run(session, run)
    if run.status == 'failed':
        session.flush()
        return run
    usage = _json(run.usage_json, {})
    if not usage.get('forced'):
        prior = session.scalar(select(KnowledgeMaintenanceRun).where(
            KnowledgeMaintenanceRun.id != run.id,
            KnowledgeMaintenanceRun.scope_type == run.scope_type,
            KnowledgeMaintenanceRun.scope_id == run.scope_id,
            KnowledgeMaintenanceRun.source_fingerprint == run.source_fingerprint,
            KnowledgeMaintenanceRun.allow_external == run.allow_external,
            KnowledgeMaintenanceRun.status == 'complete').order_by(KnowledgeMaintenanceRun.created_at).limit(1))
        if prior and _json(prior.usage_json, {}).get('curation_version') == usage.get('curation_version'):
            run.status, run.finished_at = 'cancelled', _now()
            run.error_message = '同一知识快照已完成体检，保留本批记录并跳过重复调用'
            run.usage_json = _dump({**usage, 'duplicate_of': prior.id})
            session.flush()
            return run
    run.status = "running"
    run.started_at = run.started_at or _now()
    run.error_message = None
    session.flush()
    if checkpoint_lock is not None:
        session.commit()
    all_issues = pending_audit_issues(session, run)
    usage = _json(run.usage_json, {"call_times": [], "events": [], "processed_issue_ids": []})
    processed = {str(item) for item in usage.get("processed_issue_ids", []) if str(item)}
    issues = [issue for issue in all_issues if issue.status == "proposed" and issue.id not in processed]
    attempts = usage.get('attempts', {})
    retry_at = usage.get('retry_at', {})
    issues.sort(key=lambda item: (attempts.get(item.id, 0), retry_at.get(item.id, 0), item.id))
    issues = [item for item in issues if retry_at.get(item.id, 0) <= _now().timestamp()]
    if issue_id is not None:
        issues = [item for item in issues if item.id == issue_id]
    if provider is None or getattr(provider, "mode", "extractive") != "remote" or not getattr(provider, "configured", False):
        run.status = "partial"
        run.error_message = "当前没有可用的远程模型，已保留程序化体检结果"
        run.finished_at = _now()
        _refresh_run_counts(session, run)
        session.flush()
        return run
    errors = []
    calls = 0
    for issue in issues:
        if max_calls is not None and calls >= max_calls:
            break
        finding = {
            "kind": issue.kind, "summary": issue.summary, "reasoning": issue.reasoning,
            "subject_ids": _json(issue.subject_ids_json, []), "paper_ids": [],
            "proposed_action": _json(issue.proposed_action_json, {}),
        }
        action = finding['proposed_action']
        paper = session.get(Paper, action.get('paper_id')) if action.get('type') == 'curate_paper' else None
        if action.get('type') == 'curate_paper' and (paper is None or paper.is_demo or not paper.chunks):
            issue.status = 'stale'
            processed.add(issue.id)
            continue
        if paper is not None:
            from .knowledge_steward import VERSION, build_bundle, fingerprint as paper_fingerprint
            current_fingerprint = paper_fingerprint(paper)
            completed = session.scalars(select(KnowledgeMaintenanceIssue).where(
                KnowledgeMaintenanceIssue.id != issue.id,
                KnowledgeMaintenanceIssue.status.in_(['accepted','auto_applied']))).all()
            prior_issue = next((item for item in completed if
                (done := _json(item.proposed_action_json, {})).get('type') == 'curate_paper'
                and done.get('paper_id') == paper.id and done.get('version') == VERSION
                and done.get('result_fingerprint') == current_fingerprint), None) if not usage.get('forced') else None
            if prior_issue is not None:
                issue.status = 'accepted'
                issue.reasoning = '该论文的当前知识快照已检查，复用已有结果，未重复调用模型'
                issue.proposed_action_json = _dump({**action, 'result_fingerprint': current_fingerprint,
                                                   'reused_issue_id': prior_issue.id})
                processed.add(issue.id)
                usage.setdefault('auto_actions', 0)
                usage['processed_issue_ids'] = sorted(processed)
                run.usage_json = _dump(usage)
                session.flush()
                continue
            from .publication_metadata import enrich_publication
            if checkpoint_lock is not None:
                # A paper preparing bibliographic context owns this batch too.
                # Another finishing paper must not mark its owner as paused.
                usage['active_issue_ids'] = sorted(set(usage.get('active_issue_ids', [])) | {issue.id})
                usage['active_issue_id'] = usage['active_issue_ids'][0]
                run.usage_json = _dump(usage)
                session.commit()
            metadata = enrich_publication(session, paper, allow_external=run.allow_external,
                                          checkpoint_lock=checkpoint_lock)
            # Bibliographic lookups can release the checkpoint lock, just like
            # model generation. Other papers may have advanced this batch.
            usage = _json(run.usage_json, {})
            processed = set(usage.get('processed_issue_ids', []))
            attempts, retry_at = usage.get('attempts', {}), usage.get('retry_at', {})
            bundle = build_bundle(session, paper)
        else:
            bundle = build_model_bundle(session, finding)
        # Count attempts before generation: a rejected response or cancellation
        # can still consume quota. The caller commits partial runs on failure.
        if preflight_call is not None:
            preflight_call()
        calls += 1
        usage['active_issue_ids'] = sorted(set(usage.get('active_issue_ids', [])) | {issue.id})
        usage['active_issue_id'] = usage['active_issue_ids'][0]
        usage["call_times"] = [*usage.get("call_times", []), _now().timestamp()]
        run.usage_json = _dump(usage)
        # The provider may run for minutes. Persist its attempt, then release
        # SQLite's write lock so reading, notes and foreground Q&A keep working.
        session.commit()
        try:
            if checkpoint_lock is not None:
                checkpoint_lock.release()
            try:
                result = provider.audit_knowledge_bundle(bundle)
            finally:
                if checkpoint_lock is not None:
                    checkpoint_lock.acquire()
                # Another paper can finish while this request is in flight.
                # Merge from the persisted checkpoint, never the old snapshot.
                session.expire_all()
                usage = _json(run.usage_json, {})
                processed = set(usage.get('processed_issue_ids', []))
                attempts, retry_at = usage.get('attempts', {}), usage.get('retry_at', {})
                usage['active_issue_ids'] = [key for key in usage.get('active_issue_ids', []) if key != issue.id]
                usage['active_issue_id'] = next(iter(usage['active_issue_ids']), None)
            from ..providers.priority import check_background
            check_background()
            if run.status != 'running':
                run.usage_json = _dump(usage)
                session.commit()
                return run
            if paper is not None:
                from .knowledge_steward import apply_batch
                report = apply_batch(session, paper, result, bundle)
                report['publication'] = metadata
                issue.proposed_action_json = _dump({**action, 'result_fingerprint': report['result_fingerprint']})
                issue.applied_change_ids_json = _dump(report['change_ids'])
                issue.summary = report['summary'] or paper.title
                issue.reasoning = '已核对正文；仅写入原文支持、端点有效且未覆盖人工决定的变更'
                issue.auto_eligible = True
                issue.status = 'auto_applied' if report['change_ids'] else 'accepted'
                usage['paper_audits'] = [*usage.get('paper_audits', []), report]
                usage['auto_actions'] = usage.get('auto_actions', 0) + sum(report.get(k,0) for k in ('objects_confirmed','objects_rejected','objects_contextualized','relations_confirmed','relations_rejected','aliases_linked'))
            else:
                store_model_proposals(session, run, finding, result)
            processed.add(issue.id)
            usage.setdefault('issue_errors', {}).pop(issue.id, None)
            run.model_name = result.get("model_version") or getattr(provider, 'response_model', None) or getattr(provider, 'model', None) or run.model_name
            run.prompt_version = result.get("prompt_version") or bundle.get('version') or run.prompt_version
            usage["events"] = [*usage.get("events", []), {"stage": "maintenance", "at": _now().timestamp(), "code": "saved"}][-20:]
            usage["input_tokens"] = usage.get("input_tokens", 0) + int(getattr(provider, "last_usage", {}).get("input_tokens") or 0)
            usage["output_tokens"] = usage.get("output_tokens", 0) + int(getattr(provider, "last_usage", {}).get("output_tokens") or 0)
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            usage["processed_issue_ids"] = sorted(processed)
            run.usage_json = _dump(usage)
            session.commit()
        except ProviderError as error:
            usage['input_tokens'] = usage.get('input_tokens', 0) + int(getattr(provider, 'last_usage', {}).get('input_tokens') or 0)
            usage['output_tokens'] = usage.get('output_tokens', 0) + int(getattr(provider, 'last_usage', {}).get('output_tokens') or 0)
            usage['total_tokens'] = usage['input_tokens'] + usage['output_tokens']
            attempts[issue.id] = attempts.get(issue.id, 0) + int(error.code != 'background_preempted')
            retry_at[issue.id] = _now().timestamp() + (5 if error.code == 'background_preempted' else 60)
            usage['attempts'], usage['retry_at'] = attempts, retry_at
            usage.setdefault('issue_errors', {})[issue.id] = str(error)
            if attempts[issue.id] >= 2:
                processed.add(issue.id)
                issue.status = 'needs_review'
                issue.reasoning = str(error)
                usage['processed_issue_ids'] = sorted(processed)
            usage["events"] = [*usage.get("events", []), {"stage": "maintenance", "at": _now().timestamp(), "code": error.code}][-20:]
            run.usage_json = _dump(usage)
            errors.append(str(error))
            break
    remaining = any(issue.status == "proposed" and issue.id not in processed for issue in all_issues)
    failed = any(item.status == 'needs_review' for item in all_issues)
    if run.status != 'cancelled':
        run.status = ('running' if usage.get('active_issue_ids') else 'failed' if failed and not remaining
                      else 'partial' if errors or remaining else 'complete')
    outstanding_error = next(iter(usage.get('issue_errors', {}).values()), None)
    run.error_message = errors[0] if errors else outstanding_error or ("部分论文等待重试退避，已有整理已保存" if remaining and not issues else "本轮达到后台维护调用上限，可稍后继续" if remaining else None)
    run.finished_at = _now()
    _refresh_run_counts(session, run)
    session.flush()
    return run
