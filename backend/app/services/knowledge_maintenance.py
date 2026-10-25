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
from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import (
    CollectionPaper,
    KnowledgeCandidate,
    KnowledgeChange,
    KnowledgeEntity,
    KnowledgeMaintenanceIssue,
    KnowledgeMaintenanceRun,
    KnowledgeRelation,
    Paper,
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


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_snapshot(row) -> dict:
    return curation.snapshot(row)


def _paper_ids(session: Session, scope_type: str = "library", scope_id: str | None = None, ids: Iterable[str] = ()) -> list[str]:
    wanted = {str(item) for item in ids if str(item).strip()}
    if scope_type == "papers":
        return sorted(wanted)
    statement = select(Paper.id)
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


def _subject_rows(session: Session, issue: KnowledgeMaintenanceIssue) -> list[Any]:
    ids = _json(issue.subject_ids_json, [])
    rows: list[Any] = []
    for model in (KnowledgeEntity, KnowledgeCandidate, KnowledgeRelation):
        rows.extend(session.scalars(select(model).where(model.id.in_(ids))).all())
    return rows


def _refresh_run_counts(session: Session, run: KnowledgeMaintenanceRun) -> None:
    issues = list(session.scalars(select(KnowledgeMaintenanceIssue).where(KnowledgeMaintenanceIssue.run_id == run.id)).all())
    run.safe_count = sum(bool(row.auto_eligible and row.status == "proposed") for row in issues)
    run.review_count = sum(row.status in {"proposed", "needs_review"} and not row.auto_eligible for row in issues)
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
