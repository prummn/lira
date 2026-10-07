"""Task lifecycle endpoints remain separate from read-only library retrieval."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import IntelligenceTask, Paper
from ..providers import get_model_provider
from ..schemas import IntelligenceTaskCreate, IntelligenceTaskList, TaskRead
from ..services.intelligence import cancel_task, queue_tasks
from ..services.serialization import task_read

router = APIRouter(prefix='/intelligence')


@router.post('/tasks', response_model=IntelligenceTaskList)
def create_tasks(payload: IntelligenceTaskCreate, request: Request, session: Session = Depends(get_db)) -> IntelligenceTaskList:
    tasks = queue_tasks(session, payload.paper_ids, get_model_provider(), payload.force)
    result = IntelligenceTaskList(tasks=[task_read(task) for task in tasks])
    request.app.state.intelligence_worker.wake()
    return result


@router.get('/tasks', response_model=IntelligenceTaskList)
def list_tasks(paper_id: str | None = None, limit: int = Query(100, ge=1, le=1000), session: Session = Depends(get_db)) -> IntelligenceTaskList:
    statement = select(IntelligenceTask)
    if paper_id:
        statement = statement.where(IntelligenceTask.paper_id == paper_id)
    tasks = session.scalars(statement.order_by(IntelligenceTask.created_at.desc(), IntelligenceTask.id).limit(limit)).all()
    return IntelligenceTaskList(tasks=[task_read(task) for task in tasks])


@router.post('/tasks/{task_id}/cancel', response_model=TaskRead)
def cancel(task_id: str, session: Session = Depends(get_db)) -> TaskRead:
    return task_read(cancel_task(session, task_id))


@router.get('/overview')
def overview(session: Session = Depends(get_db)) -> dict:
    counts = {status: count for status, count in session.execute(select(Paper.intelligence_status, func.count(Paper.id)).group_by(Paper.intelligence_status))}
    return {'total': sum(counts.values()), **{status: counts.get(status, 0) for status in ('unanalyzed', 'queued', 'running', 'completed', 'partial', 'failed', 'cancelled')}}
