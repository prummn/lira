"""Small task summaries for polling; never load analysis reports or source text."""
from datetime import timezone
import json
import time
from collections import defaultdict

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import Collection, IntelligenceTask, KnowledgeMaintenanceIssue, KnowledgeMaintenanceRun, Paper


def monitor_analysis_tasks(db: Session) -> list[dict]:
    task = IntelligenceTask
    active_statuses = ('queued', 'running')
    columns = (task.id, task.paper_id, Paper.title.label('paper_title'), task.status,
               task.phase, task.completed_steps, task.total_steps, task.error,
               task.created_at, task.updated_at)
    base = select(*columns).join(Paper, Paper.id == task.paper_id)
    active = db.execute(base.where(task.status.in_(active_statuses)).order_by(
        case((task.status == 'running', 0), else_=1), task.created_at, task.id)).mappings().all()
    latest = select(task.id, func.row_number().over(
        partition_by=task.paper_id, order_by=(task.created_at.desc(), task.id.desc())
    ).label('attempt')).subquery()
    recent = db.execute(base.join(latest, latest.c.id == task.id).where(
        latest.c.attempt == 1, task.status.not_in(active_statuses),
        task.paper_id.not_in([row['paper_id'] for row in active]),
        task.paper_id.not_in(select(task.paper_id).where(task.status.in_(active_statuses)))
    ).order_by(task.updated_at.desc(), task.created_at.desc(), task.id.desc()).limit(10)).mappings().all()
    # SQLite returns naive timestamps; these task records are stored in UTC.
    return [{**row, **{key: row[key].replace(tzinfo=timezone.utc).isoformat()
                      for key in ('created_at', 'updated_at')}} for row in [*active, *recent]]


def monitor_maintenance_tasks(db: Session, *, reason='queued', enabled=True, maintenance_enabled=True) -> list[dict]:
    """Keep every active batch visible, with small persisted paper checkpoints."""
    run = KnowledgeMaintenanceRun
    candidates = db.scalars(select(run).where(run.status.in_(['queued','running','partial']))
        .order_by(run.created_at, run.id)).all()
    # Read only status/action fields; evidence and model reports do not belong
    # in a five-second monitor response.
    def checkpoints(rows):
        grouped = defaultdict(list)
        if rows:
            for row in db.execute(select(KnowledgeMaintenanceIssue.run_id, KnowledgeMaintenanceIssue.id,
                    KnowledgeMaintenanceIssue.status, KnowledgeMaintenanceIssue.proposed_action_json).where(
                    KnowledgeMaintenanceIssue.run_id.in_([r.id for r in rows]))).mappings():
                grouped[row['run_id']].append(row)
        return grouped
    issues = checkpoints(candidates)
    def audits(row):
        usage = json.loads(row.usage_json or '{}')
        original = usage.get('audit_issue_ids')
        return [i for i in issues[row.id] if i['id'] in original] if original is not None else [
            i for i in issues[row.id] if json.loads(i['proposed_action_json']).get('type') == 'curate_paper']
    def pending(row):
        processed = set(json.loads(row.usage_json or '{}').get('processed_issue_ids', []))
        return [i for i in audits(row) if i['status'] == 'proposed' and i['id'] not in processed]
    active = [r for r in candidates if r.status != 'partial' or pending(r)]
    recent = db.scalars(select(run).where(run.id.not_in([r.id for r in active]))
        .order_by(run.updated_at.desc(),run.created_at.desc(),run.id.desc()).limit(10)).all()
    issues.update(checkpoints(recent))
    rows = [*active, *recent]
    collection_names = dict(db.execute(select(Collection.id, Collection.name).where(
        Collection.id.in_([r.scope_id for r in rows if r.scope_type == 'collection']))).all())
    source_ids = {json.loads(i['proposed_action_json']).get('paper_id') for r in rows for i in audits(r)}
    paper_names = dict(db.execute(select(Paper.id, Paper.title).where(Paper.id.in_(source_ids))).all())
    result = []
    for row in rows:
        usage = json.loads(row.usage_json or '{}')
        work = audits(row)
        waiting = pending(row)
        processed = set(usage.get('processed_issue_ids', []))
        current = next((i for i in waiting if i['id'] == usage.get('active_issue_id')), None) if row.status == 'running' else None
        paper_id = json.loads(current['proposed_action_json']).get('paper_id') if current else None
        scoped_ids = {json.loads(i['proposed_action_json']).get('paper_id') for i in work} - {None}
        scope_title = collection_names.get(row.scope_id)
        if row.scope_type == 'papers' and len(scoped_ids) == 1:
            scope_title = paper_names.get(next(iter(scoped_ids)))
        deferred = waiting and all(usage.get('retry_at', {}).get(i['id'], 0) > time.time() for i in waiting)
        waiting_reason = ('working' if current else 'disabled' if not enabled else 'maintenance_disabled'
            if not maintenance_enabled else 'retry_wait' if deferred else reason)
        result.append(dict(id=row.id, scope_type=row.scope_type, scope_id=row.scope_id,
            scope_title=scope_title, status=row.status,
            paper_count=max(usage.get('paper_count',0),len(scoped_ids)), total=len(work),
            completed=sum(i['status'] in ('accepted','auto_applied','stale') or (
                i['id'] in processed and i['status'] != 'needs_review') for i in work),
            pending=len(waiting), failed=sum(i['status']=='needs_review' for i in work),
            active_paper_id=paper_id, active_paper_title=paper_names.get(paper_id),
            reason=waiting_reason if row.status in ('queued','running') or waiting else None,
            error=row.error_message, model_name=row.model_name,
            created_at=row.created_at.replace(tzinfo=timezone.utc).isoformat(),
            updated_at=row.updated_at.replace(tzinfo=timezone.utc).isoformat()))
    return result
