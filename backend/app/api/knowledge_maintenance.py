"""Persistent knowledge-network health checks and reversible repair actions."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..maintenance_schemas import MaintenanceRunCreate
from ..models import KnowledgeMaintenanceIssue, KnowledgeMaintenanceRun
from ..providers import get_model_provider
from ..services import knowledge_maintenance as maintenance

router = APIRouter()


def _issue(session: Session, issue_id: str) -> KnowledgeMaintenanceIssue:
    row = session.get(KnowledgeMaintenanceIssue, issue_id)
    if row is None:
        raise HTTPException(404, "维护问题不存在")
    return row


def _detail(session: Session, run: KnowledgeMaintenanceRun) -> dict:
    run.issues = list(session.scalars(select(KnowledgeMaintenanceIssue).where(
        KnowledgeMaintenanceIssue.run_id == run.id
    ).order_by(KnowledgeMaintenanceIssue.severity.desc(), KnowledgeMaintenanceIssue.auto_eligible.desc(), KnowledgeMaintenanceIssue.created_at)).all())
    return {**maintenance.serialize_run(run), "issues": [maintenance.serialize_issue(issue) for issue in run.issues]}


@router.post("/knowledge/maintenance/runs")
def create_run(payload: MaintenanceRunCreate, request: Request, session: Session = Depends(get_db)):
    run = maintenance.prepare_run(
        session,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        paper_ids=payload.paper_ids,
        allow_external=payload.allow_external,
        force=payload.force,
    )
    session.commit()
    # The worker is the only component allowed to perform model calls. Wake it
    # after persistence so the response always contains the local audit.
    worker = getattr(request.app.state, "research_worker", None)
    if worker is not None and hasattr(worker, "wake"):
        worker.wake()
    return _detail(session, run)


@router.get("/knowledge/maintenance/runs")
def list_runs(limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_db)):
    rows = session.scalars(select(KnowledgeMaintenanceRun).order_by(KnowledgeMaintenanceRun.created_at.desc()).limit(limit)).all()
    return {"items": [maintenance.serialize_run(row) for row in rows]}


@router.get("/knowledge/maintenance/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_db)):
    run = session.get(KnowledgeMaintenanceRun, run_id)
    if run is None:
        raise HTTPException(404, "维护批次不存在")
    return _detail(session, run)


@router.post("/knowledge/maintenance/runs/{run_id}/apply-safe")
def apply_safe(run_id: str, session: Session = Depends(get_db)):
    run = session.get(KnowledgeMaintenanceRun, run_id)
    if run is None:
        raise HTTPException(404, "维护批次不存在")
    results = []
    for issue in list(session.scalars(select(KnowledgeMaintenanceIssue).where(
        KnowledgeMaintenanceIssue.run_id == run.id,
        KnowledgeMaintenanceIssue.status.in_(["proposed", "needs_review"]),
        KnowledgeMaintenanceIssue.auto_eligible == True,
    )).all()):
        try:
            maintenance.apply_issue(session, issue)
            results.append({"id": issue.id, "status": issue.status})
            session.commit()
        except HTTPException as error:
            session.rollback()
            results.append({"id": issue.id, "status": "skipped", "detail": error.detail})
            run = session.get(KnowledgeMaintenanceRun, run_id)
    run = session.get(KnowledgeMaintenanceRun, run_id)
    session.commit()
    return {"run": _detail(session, run), "results": results}


@router.post("/knowledge/maintenance/issues/{issue_id}/apply")
def apply_issue(issue_id: str, session: Session = Depends(get_db)):
    issue = _issue(session, issue_id)
    updated = maintenance.apply_issue(session, issue, force=True)
    session.commit()
    run = session.get(KnowledgeMaintenanceRun, updated.run_id)
    return {"issue": maintenance.serialize_issue(updated), "run": maintenance.serialize_run(run)}


@router.post("/knowledge/maintenance/issues/{issue_id}/reject")
def reject_issue(issue_id: str, session: Session = Depends(get_db)):
    issue = _issue(session, issue_id)
    if issue.status not in {"proposed", "needs_review"}:
        raise HTTPException(409, "这条维护问题当前不能忽略")
    issue.status = "rejected"
    session.commit()
    run = session.get(KnowledgeMaintenanceRun, issue.run_id)
    return {"issue": maintenance.serialize_issue(issue), "run": maintenance.serialize_run(run)}


@router.post("/knowledge/maintenance/issues/{issue_id}/undo")
def undo_issue(issue_id: str, session: Session = Depends(get_db)):
    issue = _issue(session, issue_id)
    updated = maintenance.undo_issue(session, issue)
    session.commit()
    run = session.get(KnowledgeMaintenanceRun, updated.run_id)
    return {"issue": maintenance.serialize_issue(updated), "run": maintenance.serialize_run(run)}
