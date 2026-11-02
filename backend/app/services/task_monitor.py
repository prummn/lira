"""Small task summaries for polling; never load analysis reports or source text."""
from datetime import timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import IntelligenceTask, Paper


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
