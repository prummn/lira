"""Durable parallel paper tasks; claim locks never span network calls."""
from __future__ import annotations
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..db import Database
from ..models import IntelligenceTask, Paper, PaperChunk
from ..providers import get_model_provider
from ..providers.base import ProviderError
from ..providers.priority import scheduled_work
from ..providers.harness import AnalysisCancelled, analysis_fingerprint, analyze_full_paper
from .analysis import persist_analysis_result
from .knowledge import paper_knowledge_status, persist_candidates
from .serialization import find_paper, json_object
from .source_sections import prepare_source_sections, source_digest, pdf_matches
from .reading_workflow import AnalysisDeferred, require_background_quota

ACTIVE_STATUSES = ('queued', 'running')


def publish_reviewed_partial(report: dict, analysis) -> bool:
    """Publish valid scientific corrections/deletions, never an interrupted attempt."""
    science = report.get('science_review') or {}
    if (not analysis.citations or not any(analysis.card.values())
        or report.get('coverage', {}).get('complete') is not True
        or report.get('fact_coverage', {}).get('complete') is not True
        or not science.get('scheduled_items')
        or science.get('checked_items') != science.get('scheduled_items')
        or science.get('deferred_items') or science.get('pending_items')
        or science.get('invalid_response_batches') or science.get('no_supported_card')):
        return False
    rejected = science.get('rejected_items', 0)
    cardinality = science.get('card_invalid_entries', 0)
    drops = science.get('cardinality_drops', [])
    tldr_rejected = any(path.startswith('tldr[') and reason == 'science_support'
        for outcome in science.get('results', [])
        for path, reason in outcome.get('rejection_reasons', {}).items())
    if cardinality and (cardinality not in (1, 2) or not tldr_rejected
        or len(drops) != 1 or drops[0].get('field') != 'tldr'
        or drops[0].get('reason') != 'science_rejection'
        or drops[0].get('surviving_entries') != cardinality):
        return False
    return (rejected > 0 and report.get('invalid_entries') == rejected + cardinality
        and all(item.get('resolved') is True or
            (item.get('phase') == 'science_review' and item.get('reason') == 'science_support')
            for item in report.get('rejections', [])))


def queue_tasks(session: Session, paper_ids: list[str], provider, force: bool = False, *, reading_first: bool = False) -> list[IntelligenceTask]:
    if provider.mode != 'remote' or not provider.configured:
        raise ProviderError('请先配置远端模型，再开始智能分析', 409)
    ids = list(dict.fromkeys(paper_ids))
    papers = {paper.id: paper for paper in session.scalars(select(Paper).where(Paper.id.in_(ids))).all()}
    if len(papers) != len(ids):
        raise ProviderError('未找到请求中的论文，未创建分析任务', 404)
    tasks = []
    for paper_id in ids:
        paper = papers[paper_id]
        existing = session.scalar(select(IntelligenceTask).where(IntelligenceTask.paper_id == paper_id, IntelligenceTask.status.in_(ACTIVE_STATUSES)))
        if existing:
            if not reading_first:
                report = json_object(existing.report_json)
                if report.get('workflow', {}).get('kind') == 'reading_first':
                    report['workflow']['analysis_requested'] = True
                    report['workflow'].pop('retry_after', None)
                    report['workflow']['profile_id'] = getattr(provider, 'profile_id', None)
                    existing.report_json = json.dumps(report, ensure_ascii=False)
                    if existing.status == 'queued':
                        existing.phase = 'queued'
            tasks.append(existing)
            continue
        if not force and paper.intelligence_status == 'completed' and json_object(paper.intelligence_report_json).get('result_fingerprint') == analysis_fingerprint(provider, list(paper.chunks)):
            latest = session.scalar(select(IntelligenceTask).where(IntelligenceTask.paper_id == paper_id, IntelligenceTask.status == 'completed').order_by(IntelligenceTask.created_at.desc()))
            if latest:
                tasks.append(latest)
                continue
        task = IntelligenceTask(id='task-' + uuid.uuid4().hex, paper_id=paper_id, status='queued', phase='queued')
        if reading_first:
            task.phase = 'prepare_reading'
            task.report_json = json.dumps({'workflow': {'kind': 'reading_first',
                'profile_id': getattr(provider, 'profile_id', None), 'analysis_requested': False}})
        # The partial unique index closes the race between simultaneous enqueue requests.
        try:
            with session.begin_nested():
                session.add(task)
                session.flush()
        except IntegrityError:
            existing = session.scalar(select(IntelligenceTask).where(IntelligenceTask.paper_id == paper_id, IntelligenceTask.status.in_(ACTIVE_STATUSES)))
            if existing is None:
                raise
            tasks.append(existing)
            continue
        paper.intelligence_status = 'queued'
        tasks.append(task)
    session.commit()
    return tasks


def cancel_task(session: Session, task_id: str) -> IntelligenceTask:
    task = session.get(IntelligenceTask, task_id)
    if task is None:
        raise ProviderError('未找到这个分析任务', 404)
    if task.status in ACTIVE_STATUSES:
        # First write uses a conditional transition; a concurrently completed result is preserved.
        changed = session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id, IntelligenceTask.status.in_(ACTIVE_STATUSES)).values(status='cancelled', phase='cancelled', updated_at=datetime.now(timezone.utc))).rowcount
        if changed:
            session.execute(update(Paper).where(Paper.id == task.paper_id).values(intelligence_status='cancelled'))
        session.commit()
        session.refresh(task)
    return task


def recover_interrupted(database: Database) -> None:
    with database.sessions() as session:
        tasks = session.scalars(select(IntelligenceTask).where(IntelligenceTask.status == 'running')).all()
        for task in tasks:
            task.status, task.phase, task.error = 'queued', 'recovered', None
            task.run_token = None
            paper = session.get(Paper, task.paper_id)
            if paper:
                paper.intelligence_status = 'queued'
        session.commit()


class IntelligenceWorker:
    def __init__(self, database: Database, provider_factory=None, *, profiles=None, research_worker=None) -> None:
        self.database = database
        self.provider_factory = provider_factory or get_model_provider
        self.profiles, self.research_worker = profiles, research_worker
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        from .worker_pool import WorkerPool
        self._pool = WorkerPool('paper-intelligence', lambda: self.process_next(wait=True),
            profiles.worker_parallelism if profiles else lambda: 4)
        self._preparation_pool = WorkerPool('paper-preparation',
            lambda: self.process_next(prepare_only=True, wait=True), lambda: 1, maximum=1)

    def start(self) -> None:
        if not self._pool.can_start() or not self._preparation_pool.can_start():
            return
        recover_interrupted(self.database)
        self._stop.clear()
        self._pool.start()
        self._preparation_pool.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._pool.stop()
        self._preparation_pool.stop()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def wake(self) -> None:
        self._wake.set()
        self._pool.wake()
        self._preparation_pool.wake()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.process_next():
                self._wake.wait(timeout=1)
                self._wake.clear()

    def _cancelled(self, task_id: str, lease: str) -> bool:
        if self._stop.is_set() and threading.current_thread() in [*self._pool.threads, *self._preparation_pool.threads]:
            return True
        with self.database.sessions() as session:
            task = session.get(IntelligenceTask, task_id)
            return task is None or task.status != 'running' or task.run_token != lease

    def _progress(self, task_id: str, lease: str, phase: str, completed: int, total: int, report: dict) -> None:
        with self.database.sessions() as session:
            current = session.get(IntelligenceTask, task_id)
            plan = json_object(current.report_json).get('workflow') if current else None
            if plan:
                report = {**report, 'workflow': plan}
            # A cancellation arriving during HTTP still retains the completed call's billed usage.
            session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id, IntelligenceTask.run_token == lease, IntelligenceTask.status.in_(('running', 'cancelled'))).values(report_json=json.dumps(report, ensure_ascii=False), updated_at=datetime.now(timezone.utc)))
            session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id, IntelligenceTask.run_token == lease, IntelligenceTask.status == 'running').values(phase=phase, completed_steps=completed, total_steps=total))
            session.commit()

    def process_next(self, provider=None, *, task_id: str | None = None, wait: bool = False, prepare_only=False) -> bool:
        if not self._lock.acquire(blocking=wait):
            return False
        claim_locked = True
        try:
            chosen = provider or self.provider_factory()
            with self.database.sessions() as session:
                statement = select(IntelligenceTask).where(IntelligenceTask.status == 'queued')
                if task_id:
                    statement = statement.where(IntelligenceTask.id == task_id)
                from .reading_workflow import waiting_for_translation, workflow
                candidates = session.scalars(statement.order_by(IntelligenceTask.created_at, IntelligenceTask.id)).all()
                task = None
                for candidate in candidates:
                    if waiting_for_translation(session, candidate):
                        continue
                    plan = workflow(candidate)
                    if prepare_only and not (plan.get('kind') == 'reading_first' and
                            not plan.get('analysis_requested') and not plan.get('translation_job_id')
                            and candidate.phase == 'prepare_reading'):
                        continue
                    selected = chosen
                    if plan.get('profile_id') and self.profiles is not None and provider is None:
                        try:
                            selected = self.profiles.provider(plan['profile_id'])
                        except ProviderError:
                            candidate.phase = 'awaiting_connection'
                            continue
                    if selected.mode == 'remote' and selected.configured:
                        task, chosen = candidate, selected
                        break
                if task is None:
                    session.commit()
                    return False
                task_id, paper_id = task.id, task.paper_id
                lease = uuid.uuid4().hex
                changed = session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id, IntelligenceTask.status == 'queued').values(status='running', phase='structure', run_token=lease, error=None, updated_at=datetime.now(timezone.utc))).rowcount
                if not changed:
                    return False
                session.execute(update(Paper).where(Paper.id == paper_id).values(intelligence_status='running'))
                source_chunks = session.scalars(select(PaperChunk).where(PaperChunk.paper_id == paper_id).order_by(PaperChunk.page, PaperChunk.id)).all()
                # Detached value snapshots remain usable after the source transaction closes.
                chunks = [PaperChunk(id=item.id, paper_id=paper_id, page=item.page, section=item.section, content=item.content, bbox_json=item.bbox_json, page_width=item.page_width, page_height=item.page_height) for item in source_chunks]
                pdf_path, pdf_sha256 = task.paper.pdf_path, task.paper.sha256
                previous_report = json_object(task.paper.intelligence_report_json)
                previous_digest = previous_report.get('analyzed_source_digest')
                previous_stale = previous_report.get('source_structure_stale') is True
                session.commit()
            self._lock.release()
            claim_locked = False
            try:
                section_plan = prepare_source_sections(pdf_path, pdf_sha256, chunks)
                if self._cancelled(task_id, lease):
                    return True
                structure_report = {**section_plan.report, 'planned_changed_chunks': len(section_plan.changes),
                    'changed_chunks': 0, 'applied': False,
                    'retained_card_uses_previous_structure': previous_stale or bool(previous_digest and previous_digest != section_plan.source_digest)}
                self._progress(task_id, lease, 'structure', 0, 0, {'source_structure': structure_report})
                if section_plan.report.get('failure_code') == 'pdf_changed':
                    raise ProviderError('原始 PDF 与已存储原文不一致，请重新核对文件；已有结果已保留')
                with self.database.sessions() as session:
                    # Acquire a conditional write lease before touching derived source metadata.
                    eligible = session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id,
                        IntelligenceTask.run_token == lease, IntelligenceTask.status == 'running').values(updated_at=datetime.now(timezone.utc))).rowcount
                    if not eligible:
                        return True
                    paper = find_paper(session, paper_id)
                    if (paper is None or paper.pdf_path != pdf_path or paper.sha256 != pdf_sha256
                            or source_digest(paper.chunks) != section_plan.source_digest
                            or (section_plan.report['available'] and not pdf_matches(pdf_path, pdf_sha256))):
                        raise ProviderError('论文原文在章节识别期间发生变化，请重试；已有结果已保留')
                    for chunk in paper.chunks:
                        if chunk.id in section_plan.changes:
                            chunk.section = section_plan.changes[chunk.id]
                    for evidence in paper.evidence:
                        if evidence.chunk_id in section_plan.changes:
                            evidence.section = section_plan.changes[evidence.chunk_id]
                    if section_plan.changes and paper.analysis:
                        current_previous_report = json_object(paper.intelligence_report_json)
                        current_previous_report['source_structure_stale'] = True
                        paper.intelligence_report_json = json.dumps(current_previous_report, ensure_ascii=False)
                    session.commit()
                for chunk in chunks:
                    if chunk.id in section_plan.changes:
                        chunk.section = section_plan.changes[chunk.id]
                current_digest = source_digest(chunks)
                structure_report.update(applied=True, changed_chunks=len(section_plan.changes),
                    retained_card_uses_previous_structure=previous_stale or bool(section_plan.changes)
                    or bool(previous_digest and previous_digest != current_digest))
                self._progress(task_id, lease, 'structure', 0, 0, {'source_structure': structure_report})
                from .reading_workflow import prepare_translation
                if prepare_translation(self, task_id, lease, chosen):
                    return True
                if prepare_only:
                    with self.database.sessions() as session:
                        session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id,
                            IntelligenceTask.run_token == lease, IntelligenceTask.status == 'running')
                            .values(status='queued', phase='queued', run_token=None))
                        session.commit()
                    self._pool.wake()
                    return True
                def progress(phase, completed, total, report):
                    self._progress(task_id, lease, phase, completed, total,
                                   {**report, 'source_structure': structure_report})
                def check_cancelled():
                    if self._cancelled(task_id, lease):
                        raise AnalysisCancelled()
                with self.database.sessions() as session:
                    plan = workflow(session.get(IntelligenceTask, task_id))
                automatic_official = (plan.get('kind') == 'reading_first' and not plan.get('analysis_requested')
                    and chosen.name == 'CodexSubscriptionProvider' and self.research_worker is not None)
                with scheduled_work(3, check_cancelled,
                        (lambda: require_background_quota(self.research_worker)) if automatic_official else None):
                    result = analyze_full_paper(self.database, chosen, chunks, progress=progress,
                        cancelled=lambda: self._cancelled(task_id, lease))
                result.report['source_structure'] = structure_report
                result.report['analyzed_source_digest'] = current_digest
                result.report['source_structure_stale'] = False
                with self.database.sessions() as session:
                    # Acquire the write lock through a conditional transition before replacing ready data.
                    status = 'partial' if result.report['partial'] else 'completed'
                    changed = session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id, IntelligenceTask.run_token == lease, IntelligenceTask.status == 'running').values(status=status, phase='complete', error=None, updated_at=datetime.now(timezone.utc))).rowcount
                    if not changed:
                        return True
                    paper = find_paper(session, paper_id)
                    if (paper is None or paper.pdf_path != pdf_path or paper.sha256 != pdf_sha256
                            or source_digest(paper.chunks) != current_digest
                            or (section_plan.report['available'] and not pdf_matches(pdf_path, pdf_sha256))):
                        raise ProviderError('论文原文在分析期间发生变化，请重试；已有结果已保留')
                    plan = json_object(session.get(IntelligenceTask, task_id).report_json).get('workflow')
                    if plan:
                        result.report['workflow'] = plan
                    retained = bool(result.report['partial'] and not publish_reviewed_partial(result.report, result.analysis) and paper.analysis
                        and paper.analysis.mode == 'remote' and paper.analysis_status == 'ready')
                    result.report['retained_previous_card'] = retained
                    structure_report['retained_card_uses_previous_structure'] = bool(retained and structure_report['retained_card_uses_previous_structure'])
                    session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id,
                        IntelligenceTask.run_token == lease).values(report_json=json.dumps(result.report, ensure_ascii=False)))
                    report_published = not retained
                    if not retained:
                        persist_analysis_result(session, paper, chosen, result.analysis)
                    elif result.analysis.knowledge_candidates or result.analysis.knowledge_relations:
                        # A partial card may be retained for safety, while
                        # independently validated knowledge candidates remain
                        # useful and reviewable.
                        candidates, relations = persist_candidates(
                            session, paper, result.analysis.knowledge_candidates,
                            result.analysis.knowledge_relations,
                            run_id=f"{result.analysis.prompt_version or 'analysis'}-{uuid.uuid4().hex[:12]}",
                        )
                        report_published = True
                    if report_published:
                        paper.intelligence_report_json = json.dumps(result.report, ensure_ascii=False)
                        paper.intelligence_analyzed_at = datetime.now(timezone.utc)
                    paper.intelligence_status = status
                    from .knowledge_maintenance import enqueue_after_analysis
                    enqueue_after_analysis(session, paper)
                    session.commit()
            except AnalysisCancelled:
                # User cancellation already persists its state. Shutdown leaves running state for recovery.
                pass
            except AnalysisDeferred as error:
                with self.database.sessions() as session:
                    task = session.get(IntelligenceTask, task_id)
                    if task and task.run_token == lease and task.status == 'running':
                        report = json_object(task.report_json)
                        report.setdefault('workflow', {})['retry_after'] = time.time()+30
                        report['workflow']['waiting_reason'] = error.code
                        task.report_json = json.dumps(report, ensure_ascii=False)
                        task.status, task.phase, task.run_token = 'queued', 'awaiting_quota', None
                        task.paper.intelligence_status = 'queued'
                        session.commit()
            except Exception as error:
                if isinstance(error, ProviderError) and (error.retryable or error.code in ('rate_limit', 'local_capacity')):
                    with self.database.sessions() as session:
                        task = session.get(IntelligenceTask, task_id)
                        if task and task.run_token == lease and task.status == 'running':
                            report = json_object(task.report_json)
                            plan = report.setdefault('workflow', {})
                            count = min(8, plan.get('defer_count', 0) + 1)
                            plan.update(defer_count=count, waiting_reason=error.code,
                                retry_after=time.time() + max(error.retry_after or 0, min(300, 5 * 2 ** count)))
                            task.report_json = json.dumps(report, ensure_ascii=False)
                            task.status, task.phase, task.run_token = 'queued', 'awaiting_quota', None
                            task.paper.intelligence_status = 'queued'
                            session.commit()
                    return True
                safe = str(error) if isinstance(error, ProviderError) else '智能分析暂时失败，请重试；原文和已有结果已保留'
                with self.database.sessions() as session:
                    changed = session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id, IntelligenceTask.run_token == lease, IntelligenceTask.status == 'running').values(status='failed', phase='failed', error=safe, updated_at=datetime.now(timezone.utc))).rowcount
                    if changed:
                        session.execute(update(Paper).where(Paper.id == paper_id).values(intelligence_status='failed'))
                        from .knowledge_maintenance import enqueue_after_analysis
                        failed_paper = session.get(Paper, paper_id)
                        if failed_paper:
                            enqueue_after_analysis(session, failed_paper)
                    session.commit()
            return True
        finally:
            if claim_locked:
                self._lock.release()
