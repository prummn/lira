"""Persistent single-worker task orchestration; network calls hold no DB session."""
from __future__ import annotations
import json
import threading
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..db import Database
from ..models import IntelligenceTask, Paper, PaperChunk
from ..providers import get_model_provider
from ..providers.base import ProviderError
from ..providers.harness import AnalysisCancelled, analysis_fingerprint, analyze_full_paper
from .analysis import persist_analysis_result
from .serialization import find_paper, json_object
from .source_sections import prepare_source_sections, source_digest, pdf_matches

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


def queue_tasks(session: Session, paper_ids: list[str], provider, force: bool = False) -> list[IntelligenceTask]:
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
            tasks.append(existing)
            continue
        if not force and paper.intelligence_status == 'completed' and json_object(paper.intelligence_report_json).get('result_fingerprint') == analysis_fingerprint(provider, list(paper.chunks)):
            latest = session.scalar(select(IntelligenceTask).where(IntelligenceTask.paper_id == paper_id, IntelligenceTask.status == 'completed').order_by(IntelligenceTask.created_at.desc()))
            if latest:
                tasks.append(latest)
                continue
        task = IntelligenceTask(id='task-' + uuid.uuid4().hex, paper_id=paper_id, status='queued', phase='queued')
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
    def __init__(self, database: Database) -> None:
        self.database = database
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        recover_interrupted(self.database)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='paper-intelligence', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.process_next():
                self._wake.wait(timeout=1)
                self._wake.clear()

    def _cancelled(self, task_id: str, lease: str) -> bool:
        if self._stop.is_set() and threading.current_thread() is self._thread:
            return True
        with self.database.sessions() as session:
            task = session.get(IntelligenceTask, task_id)
            return task is None or task.status != 'running' or task.run_token != lease

    def _progress(self, task_id: str, lease: str, phase: str, completed: int, total: int, report: dict) -> None:
        with self.database.sessions() as session:
            # A cancellation arriving during HTTP still retains the completed call's billed usage.
            session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id, IntelligenceTask.run_token == lease, IntelligenceTask.status.in_(('running', 'cancelled'))).values(report_json=json.dumps(report, ensure_ascii=False), updated_at=datetime.now(timezone.utc)))
            session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id, IntelligenceTask.run_token == lease, IntelligenceTask.status == 'running').values(phase=phase, completed_steps=completed, total_steps=total))
            session.commit()

    def process_next(self, provider=None, *, task_id: str | None = None, wait: bool = False) -> bool:
        if not self._lock.acquire(blocking=wait):
            return False
        try:
            chosen = provider or get_model_provider()
            if chosen.mode != 'remote' or not chosen.configured:
                return False
            with self.database.sessions() as session:
                statement = select(IntelligenceTask).where(IntelligenceTask.status == 'queued')
                if task_id:
                    statement = statement.where(IntelligenceTask.id == task_id)
                task = session.scalar(statement.order_by(IntelligenceTask.created_at, IntelligenceTask.id).limit(1))
                if task is None:
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
                def progress(phase, completed, total, report):
                    self._progress(task_id, lease, phase, completed, total,
                                   {**report, 'source_structure': structure_report})
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
                            or analysis_fingerprint(chosen, list(paper.chunks)) != result.report['result_fingerprint']
                            or (section_plan.report['available'] and not pdf_matches(pdf_path, pdf_sha256))):
                        raise ProviderError('论文原文在分析期间发生变化，请重试；已有结果已保留')
                    retained = bool(result.report['partial'] and not publish_reviewed_partial(result.report, result.analysis) and paper.analysis
                        and paper.analysis.mode == 'remote' and paper.analysis_status == 'ready')
                    result.report['retained_previous_card'] = retained
                    structure_report['retained_card_uses_previous_structure'] = bool(retained and structure_report['retained_card_uses_previous_structure'])
                    session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id,
                        IntelligenceTask.run_token == lease).values(report_json=json.dumps(result.report, ensure_ascii=False)))
                    if not retained:
                        persist_analysis_result(session, paper, chosen, result.analysis)
                        paper.intelligence_report_json = json.dumps(result.report, ensure_ascii=False)
                        paper.intelligence_analyzed_at = datetime.now(timezone.utc)
                    paper.intelligence_status = status
                    session.commit()
            except AnalysisCancelled:
                # User cancellation already persists its state. Shutdown leaves running state for recovery.
                pass
            except Exception as error:
                safe = str(error) if isinstance(error, ProviderError) else '智能分析暂时失败，请重试；原文和已有结果已保留'
                with self.database.sessions() as session:
                    changed = session.execute(update(IntelligenceTask).where(IntelligenceTask.id == task_id, IntelligenceTask.run_token == lease, IntelligenceTask.status == 'running').values(status='failed', phase='failed', error=safe, updated_at=datetime.now(timezone.utc))).rowcount
                    if changed:
                        session.execute(update(Paper).where(Paper.id == paper_id).values(intelligence_status='failed'))
                    session.commit()
            return True
        finally:
            self._lock.release()
