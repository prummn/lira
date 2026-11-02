"""Durable reading preparation over existing analysis and translation tasks."""
from datetime import datetime, timezone
import json
import time

from fastapi import HTTPException

from ..models import IntelligenceTask, Paper, TranslationJob
from ..providers.base import ProviderError


class AnalysisDeferred(ProviderError):
    def __init__(self, reason):
        super().__init__('分析已排队，等待后台可用额度；已有检查点已保留', 409,
            code=reason, diagnostics={'request_sent': False})


def require_background_quota(worker):
    """Only automatic official analysis observes the background quota reserve."""
    from .research_policy import quota_decision
    state = worker.profiles.codex.status()
    worker._capture_quota(state)
    if not state.get('authenticated') or state.get('error_code'):
        raise AnalysisDeferred('account_unavailable')
    if worker._quota_error_code and not worker._quota_using_recent:
        raise AnalysisDeferred('quota_unavailable')
    settings = worker.settings()
    decision = quota_decision(worker._quota, age=max(0, time.time()-worker._quota_at),
        running=True, stop_remaining=settings.stop_remaining, long_reserve=settings.long_reserve)
    if not decision['allowed']:
        raise AnalysisDeferred(decision['reason'])


def workflow(task):
    return json.loads(task.report_json or '{}').get('workflow', {}) if task else {}


def waiting_for_translation(db, task):
    plan = workflow(task)
    if plan.get('retry_after', 0) > time.time():
        return True
    if plan.get('analysis_requested') or not plan.get('translation_job_id'):
        return False
    job = db.get(TranslationJob, plan['translation_job_id'])
    # Paused, failed and cancelled preparation never deadlocks the analysis.
    return bool(job and job.status in ('queued', 'running'))


def prepare_translation(worker, task_id, lease, provider):
    """Called after local structure preparation; never performs generation."""
    if worker.research_worker is None:
        return False
    from .translation_queue import enqueue
    with worker.database.sessions() as db:
        task = db.get(IntelligenceTask, task_id)
        if task is None or task.run_token != lease or task.status != 'running':
            return True
        plan = workflow(task)
        if plan.get('kind') != 'reading_first' or plan.get('analysis_requested'):
            return False
        if not plan.get('translation_job_id'):
            try:
                job = enqueue(worker.research_worker, db, task.paper_id, 'full', [], provider=provider)
                plan['translation_job_id'] = job['id']
            except HTTPException as error:
                if error.status_code != 409:
                    raise
                plan['preparation_note'] = str(error.detail)
                plan['translation_outcome'] = 'unavailable'
        report = json.loads(task.report_json or '{}')
        report['workflow'] = plan
        task.report_json = json.dumps(report, ensure_ascii=False)
        if waiting_for_translation(db, task):
            task.status, task.phase, task.run_token = 'queued', 'awaiting_translation', None
            db.get(Paper, task.paper_id).intelligence_status = 'queued'
            task.updated_at = datetime.now(timezone.utc)
            db.commit()
            return True
        job = db.get(TranslationJob, plan['translation_job_id']) if plan.get('translation_job_id') else None
        if job:
            plan['translation_outcome'] = job.status
            report['workflow'] = plan
            task.report_json = json.dumps(report, ensure_ascii=False)
        db.commit()
    return False
