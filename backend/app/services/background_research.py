"""Finite, checkpointed research using spare subscription quota."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import logging
from pathlib import Path
import threading
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from ..models import Collection, IntelligenceTask, KnowledgeMaintenanceIssue, KnowledgeMaintenanceRun, ResearchControl, ResearchRevision, ResearchScope, ResearchTask
from ..providers.base import ProviderError
from ..providers.priority import background_call, check_background
from ..research_schemas import ResearchSettings
from .research_materials import dumps, snapshot, verify_article, verify_synthesis
from .research_policy import quota_decision
from .research_findings import list_findings, publish_findings, verify_findings, act, history
from . import knowledge_maintenance as maintenance

PROMPTS = Path(__file__).resolve().parents[3] / 'prompts'
ACTIVE = ('queued', 'paused', 'running')


def stamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def task_read(task):
    return {'id': task.id, 'collection_id': task.collection_id, 'kind': task.kind, 'status': task.status, 'stage': task.stage,
            'calls': task.calls, 'error': task.error, 'created_at': stamp(task.created_at),
            'updated_at': stamp(task.updated_at), 'usage': json.loads(task.usage_json)}


def record_call(task, provider, stage, *, completed, code=None, message=None):
    usage = json.loads(task.usage_json)
    if completed:
        for key in ('input_tokens', 'output_tokens'):
            usage[key] = usage.get(key, 0) + (getattr(provider, 'last_usage', {}).get(key) or 0)
        usage['total_tokens'] = usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
    events = usage.setdefault('events', [])
    events.append({'stage': stage, 'at': time.time(), 'code': code or 'saved', 'message': message})
    usage['events'] = events[-20:]
    task.usage_json = dumps(usage)


def revision_read(revision, full=True):
    result = {key: getattr(revision, key) for key in ('id', 'number', 'title', 'dek', 'changes', 'model')}
    result['created_at'] = stamp(revision.created_at)
    if full:
        result.update(markdown=revision.markdown, sources=json.loads(revision.sources_json),
                      coverage=json.loads(revision.coverage_json))
    return result


class BackgroundResearchWorker:
    def __init__(self, database, profiles):
        self.database, self.profiles = database, profiles
        self._stop, self._wake = threading.Event(), threading.Event()
        self._thread = None
        self._run_lock = threading.Lock()
        self._mutation = threading.RLock()
        self._reason, self._retry_at = 'disabled', 0
        self._quota, self._quota_at = [], 0
        self._next_scan = 0
        self._next_maintenance_scan = 0

    def settings(self, payload=None):
        with self._mutation, self.database.sessions() as db:
            row = db.get(ResearchControl, 1)
            if payload is not None:
                if row is None:
                    row = ResearchControl(id=1, settings_json=payload.model_dump_json())
                    db.add(row)
                else:
                    row.settings_json = payload.model_dump_json()
                db.commit()
                self.profiles.priority.cancel()
                self._wake.set()
            return ResearchSettings.model_validate_json(row.settings_json) if row else ResearchSettings()

    def scope(self, collection_id, payload=None):
        with self._mutation, self.database.sessions() as db:
            if db.get(Collection, collection_id) is None:
                raise HTTPException(404, '专题不存在')
            row = db.get(ResearchScope, collection_id)
            if payload is not None:
                if row is None:
                    row = ResearchScope(collection_id=collection_id, enabled=payload.enabled, focus=payload.focus.strip(),
                                        work_types_json=dumps(payload.work_types))
                    db.add(row)
                else:
                    row.enabled, row.focus = payload.enabled, payload.focus.strip()
                    row.work_types_json = dumps(payload.work_types)
                db.commit()
                self.profiles.priority.cancel()
                self._next_scan = 0
                self._wake.set()
            return {'enabled': row.enabled if row else False, 'focus': row.focus if row else '',
                    'work_types': json.loads(row.work_types_json) if row else ['essay']}

    def collection(self, collection_id, revision_id=None):
        scope = self.scope(collection_id)
        with self.database.sessions() as db:
            revisions = db.scalars(select(ResearchRevision).where(ResearchRevision.collection_id == collection_id)
                                  .order_by(ResearchRevision.number.desc())).all()
            chosen = next((r for r in revisions if r.id == revision_id), None) if revision_id else (revisions[0] if revisions else None)
            if revision_id and chosen is None:
                raise HTTPException(404, '文章版本不存在')
            task = db.scalar(select(ResearchTask).where(ResearchTask.collection_id == collection_id, ResearchTask.kind == 'essay')
                             .order_by(ResearchTask.created_at.desc(), ResearchTask.id.desc()).limit(1))
            return {'scope': scope, 'revision': revision_read(chosen) if chosen else None,
                    'revisions': [revision_read(r, False) for r in revisions],
                    'task': task_read(task) if task else None}

    def findings(self, collection_id):
        scope = self.scope(collection_id)
        with self.database.sessions() as db:
            items = list_findings(db, collection_id)
            task = db.scalar(select(ResearchTask).where(ResearchTask.collection_id == collection_id,
                ResearchTask.kind == 'findings').order_by(ResearchTask.created_at.desc(), ResearchTask.id.desc()).limit(1))
            now = datetime.now(timezone.utc)
            due = sum(i['kind'] == 'review' and i['status'] not in ('dismissed', 'done') and
                      bool(i['due_at']) and datetime.fromisoformat(i['due_at']) <= now for i in items)
            return {'scope': scope, 'items': items, 'task': task_read(task) if task else None, 'due_count': due}

    def finding_action(self, finding_id, action):
        with self._mutation, self.database.sessions() as db:
            return act(db, finding_id, action)

    def finding_history(self, finding_id):
        with self.database.sessions() as db:
            return history(db, finding_id)

    def status(self):
        with self.database.sessions() as db:
            tasks = db.scalars(select(ResearchTask).order_by(ResearchTask.updated_at.desc()).limit(30)).all()
            scopes = db.scalars(select(ResearchScope).where(ResearchScope.enabled == True)).all()
            maintenance_run = db.scalar(select(KnowledgeMaintenanceRun).order_by(KnowledgeMaintenanceRun.updated_at.desc()).limit(1))
        return {'settings': self.settings().model_dump(), 'reason': self._reason,
                'quota': self._quota, 'quota_checked_at': self._quota_at or None,
                'tasks': [task_read(t) for t in tasks], 'scope_ids': [s.collection_id for s in scopes],
                'maintenance': maintenance.serialize_run(maintenance_run) if maintenance_run else None}

    def refresh_quota(self):
        state = self.profiles.codex.status(refresh=True)
        self._quota_at, self._quota = time.time(), state.get('limits', [])
        return {'quota': self._quota, 'checked_at': self._quota_at,
                'available': bool(state.get('authenticated') and not state.get('error_code'))}

    def enqueue(self, collection_id, kind='essay'):
        if kind not in ('essay', 'findings'):
            raise HTTPException(422, '未知研究任务类型')
        with self._mutation:
            scope = self.scope(collection_id)
            if not scope['enabled']:
                raise HTTPException(409, '请先为这个专题开启后台研究')
            if (kind == 'essay' and 'essay' not in scope['work_types']) or (kind == 'findings' and not set(scope['work_types']) - {'essay'}):
                raise HTTPException(409, '请先在研究设置中选择这类任务')
            with self.database.sessions() as db:
                material, fingerprint = snapshot(db, collection_id, scope['focus'], kind=kind, work_types=scope['work_types'])
                if not material['sources']:
                    raise HTTPException(409, '专题还没有可读取的论文原文，请先导入 PDF')
                if len(material['papers']) > 40:
                    raise HTTPException(409, '请将研究范围缩小至 40 篇以内，以便充分研读')
                previous = db.scalar(select(ResearchTask).where(ResearchTask.collection_id == collection_id,
                    ResearchTask.fingerprint == fingerprint))
                if previous and previous.status == 'completed' and kind == 'essay':
                    current = db.scalar(select(ResearchRevision).where(ResearchRevision.collection_id == collection_id)
                        .order_by(ResearchRevision.number.desc()).limit(1))
                    if current and current.task_id != previous.id:
                        previous.fingerprint = hashlib.sha256((fingerprint + previous.id).encode()).hexdigest()
                        db.flush()
                        previous = None
                if previous and previous.status != 'superseded':
                    return task_read(previous)
                for old in db.scalars(select(ResearchTask).where(ResearchTask.collection_id == collection_id,
                                                               ResearchTask.kind == kind,
                                                               ResearchTask.status.in_(ACTIVE))):
                    old.status = 'superseded'
                if previous:
                    task = previous
                    task.status, task.attempts, task.error = 'queued', 0, None
                else:
                    task = ResearchTask(id='research-' + uuid.uuid4().hex, collection_id=collection_id,
                        kind=kind, stage='discover' if kind == 'findings' else 'synthesis',
                        fingerprint=fingerprint, material_json=dumps(material))
                    db.add(task)
                db.commit()
                self.profiles.priority.cancel()
                self._wake.set()
                return task_read(task)

    def action(self, task_id, action):
        with self._mutation, self.database.sessions() as db:
            task = db.get(ResearchTask, task_id)
            if task is None:
                raise HTTPException(404, '研究任务不存在')
            if action == 'cancel' and task.status in ACTIVE:
                task.status = 'cancelled'
                self.profiles.priority.cancel()
            elif action == 'retry' and task.status in ('failed', 'cancelled'):
                task.status, task.attempts, task.error = 'queued', 0, None
                self._retry_at = 0
                self._wake.set()
            else:
                raise HTTPException(409, '当前任务状态不支持这项操作')
            db.commit()
            return task_read(task)

    def start(self):
        with self.database.sessions() as db:
            for task in db.scalars(select(ResearchTask).where(ResearchTask.status == 'running')):
                task.status = 'paused'
                task.error = None
            for run in db.scalars(select(KnowledgeMaintenanceRun).where(KnowledgeMaintenanceRun.status == 'running')):
                run.status = 'queued'
                run.error_message = '服务重启后保留本地体检结果，等待额度允许时继续'
            db.commit()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='lira-background-research', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.profiles.priority.cancel()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def wake(self):
        self._wake.set()

    def maintenance_action(self, run_id: str, action: str):
        """Pause or resume one persisted maintenance batch without spawning a new worker."""
        if action not in {'cancel', 'retry'}:
            raise HTTPException(404, '维护操作不存在')
        with self._mutation, self.database.sessions() as db:
            run = db.get(KnowledgeMaintenanceRun, run_id)
            if run is None:
                raise HTTPException(404, '维护批次不存在')
            if action == 'cancel':
                if run.status not in {'queued', 'running', 'partial'}:
                    raise HTTPException(409, '当前维护批次不能暂停')
                run.status = 'cancelled'
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = '已由研究者暂停，原有体检结果仍保留'
                self.profiles.priority.cancel()
            else:
                if run.status not in {'failed', 'cancelled', 'partial'}:
                    raise HTTPException(409, '当前维护批次不能重试')
                run.status = 'queued'
                run.started_at = None
                run.finished_at = None
                run.error_message = None
                usage = json.loads(run.usage_json or '{}')
                events = usage.setdefault('events', [])
                events.append({'stage': 'maintenance', 'at': time.time(), 'code': 'retry'})
                usage['events'] = events[-20:]
                run.usage_json = dumps(usage)
                self._retry_at = 0
            db.commit()
        self._wake.set()
        return maintenance.serialize_run(run)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.process_next()
            except Exception:
                # Exception text can contain model output; never put it in logs.
                logging.getLogger(__name__).error('Background research tick failed; persisted work retained')
                self._reason = 'service_error'
                self._retry_at = time.time() + 60
            self._wake.wait(3)
            self._wake.clear()

    def _eligible(self, settings, running=False, include_maintenance=False):
        if not settings.enabled:
            self._reason = 'disabled'
            return False
        profiles = self.profiles.public()['profiles']
        if not any(p['id'] == settings.profile_id and p.get('provider_kind') == 'codex' for p in profiles):
            self._reason = 'profile_required'
            return False
        if not self.profiles.priority.idle(settings.idle_seconds):
            self._reason = 'reading'
            return False
        with self.database.sessions() as db:
            explicit = db.scalar(select(IntelligenceTask.id).where(IntelligenceTask.status.in_(['queued', 'running'])).limit(1))
            if explicit:
                self._reason = 'foreground_queue'
                return False
            jobs = db.scalars(select(ResearchTask)).all()
            times = [t for job in jobs for t in json.loads(job.usage_json).get('call_times', []) if t > time.time()-3600]
            if include_maintenance:
                runs = db.scalars(select(KnowledgeMaintenanceRun)).all()
                times.extend(t for run in runs for t in json.loads(run.usage_json).get('call_times', []) if t > time.time()-3600)
            if len(times) >= settings.calls_per_hour:
                self._reason = 'hourly_budget'
                return False
        if time.time() < self._retry_at:
            self._reason = 'cooldown'
            return False
        # Official read is a non-generating RPC. A failed read never falls back to paid API.
        state = self.profiles.codex.status(refresh=True)
        self._quota_at = time.time()
        self._quota = state.get('limits', [])
        if not state.get('authenticated') or state.get('error_code'):
            self._reason = 'account_unavailable'
            self._retry_at = time.time() + 60
            return False
        decision = quota_decision(self._quota, age=0, running=running,
            start_remaining=settings.start_remaining, stop_remaining=settings.stop_remaining,
            long_reserve=settings.long_reserve)
        self._reason = decision['reason']
        if not decision['allowed']:
            self._retry_at = time.time() + 60
        return decision['allowed']

    def _maybe_enqueue_maintenance(self, settings):
        if not settings.maintenance_enabled or time.time() < self._next_maintenance_scan:
            return None
        self._next_maintenance_scan = time.time() + 60
        with self.database.sessions() as db:
            current = None
            candidates = db.scalars(select(KnowledgeMaintenanceRun).where(
                KnowledgeMaintenanceRun.status.in_(['queued', 'running', 'partial'])
            ).order_by(KnowledgeMaintenanceRun.created_at, KnowledgeMaintenanceRun.id)).all()
            for item in candidates:
                if item.status in {'queued', 'running'}:
                    current = item
                    break
                usage = json.loads(item.usage_json or '{}')
                processed = {str(value) for value in usage.get('processed_issue_ids', []) if str(value)}
                pending = db.scalar(select(KnowledgeMaintenanceIssue.id).where(
                    KnowledgeMaintenanceIssue.run_id == item.id,
                    KnowledgeMaintenanceIssue.status == 'proposed',
                    ~KnowledgeMaintenanceIssue.id.in_(processed) if processed else True,
                ).limit(1))
                if pending:
                    current = item
                    break
            latest = db.scalar(select(KnowledgeMaintenanceRun).order_by(KnowledgeMaintenanceRun.created_at.desc()).limit(1))
            if current is not None:
                return current.id
            if latest and latest.status != 'partial' and latest.created_at and (time.time() - latest.created_at.replace(tzinfo=timezone.utc).timestamp()) < settings.maintenance_interval_minutes * 60:
                return None
            try:
                if settings.maintenance_scope == 'enabled_collections':
                    scopes = db.scalars(select(ResearchScope).where(ResearchScope.enabled == True)).all()
                    for scope in scopes:
                        maintenance.prepare_run(db, scope_type='collection', scope_id=scope.collection_id, allow_external=False)
                else:
                    maintenance.prepare_run(db, scope_type='library', allow_external=False)
                db.commit()
            except HTTPException:
                db.rollback()
        return None

    def _process_maintenance(self, settings):
        self._maybe_enqueue_maintenance(settings)
        with self.database.sessions() as db:
            research_ready = db.scalar(select(ResearchTask.id).where(ResearchTask.status.in_(['queued', 'running', 'paused'])).limit(1))
            if research_ready:
                self._reason = 'research_queue'
                return False
            runs = db.scalars(select(KnowledgeMaintenanceRun).where(
                KnowledgeMaintenanceRun.status.in_(['queued', 'partial'])
            ).order_by(KnowledgeMaintenanceRun.created_at, KnowledgeMaintenanceRun.id)).all()
            run = None
            for item in runs:
                if item.status == 'queued':
                    run = item
                    break
                usage = json.loads(item.usage_json or '{}')
                processed = {str(value) for value in usage.get('processed_issue_ids', []) if str(value)}
                pending = db.scalar(select(KnowledgeMaintenanceIssue.id).where(
                    KnowledgeMaintenanceIssue.run_id == item.id,
                    KnowledgeMaintenanceIssue.status == 'proposed',
                    ~KnowledgeMaintenanceIssue.id.in_(processed) if processed else True,
                ).limit(1))
                if pending:
                    run = item
                    break
        if run is None:
            return False
        if not self._eligible(settings, running=True, include_maintenance=True):
            return False
        self._reason = 'maintenance_working'
        try:
            provider = self.profiles.subscription_provider(settings.profile_id)
            with background_call(self.profiles.priority):
                if not self.profiles.priority.idle(settings.idle_seconds) or not self.settings().enabled:
                    self._reason = 'maintenance_reading'
                    return False
                with self.database.sessions() as db:
                    current = db.get(KnowledgeMaintenanceRun, run.id)
                    if current is None or current.status not in {'queued', 'partial'}:
                        return False
                    maintenance.execute_run(db, current, provider, max_calls=settings.maintenance_calls_per_run)
                    db.commit()
                    if current.status == 'partial':
                        self._reason = 'maintenance_error' if current.error_message and '调用上限' not in current.error_message else 'maintenance_partial'
                        if self._reason == 'maintenance_error':
                            self._retry_at = time.time() + 60
                    else:
                        self._reason = 'up_to_date'
            return True
        except ProviderError as error:
            with self.database.sessions() as db:
                current = db.get(KnowledgeMaintenanceRun, run.id)
                if current:
                    current.status = 'partial'
                    current.error_message = str(error)
                    current.finished_at = datetime.now(timezone.utc)
                    db.commit()
            self._reason = 'maintenance_error'
            self._retry_at = time.time() + 60
            return False

    def process_next(self):
        if not self._run_lock.acquire(blocking=False):
            return False
        try:
            # No generation can be running while this lock is free. Recover
            # jobs left by a failed checkpoint commit, not just process exits.
            with self._mutation, self.database.sessions() as db:
                stranded = db.scalars(select(ResearchTask).where(ResearchTask.status == 'running')).all()
                for job in stranded:
                    job.attempts += 1
                    job.status = 'paused' if job.attempts < 2 else 'failed'
                    job.error = '上一步保存未完成，已有文章与检查点已保留'
                if stranded:
                    db.commit()
            settings = self.settings()
            if not settings.enabled:
                self._reason = 'disabled'
                return False
            with self.database.sessions() as db:
                task = db.scalar(select(ResearchTask).join(ResearchScope,
                    ResearchScope.collection_id == ResearchTask.collection_id).where(
                    ResearchTask.status.in_(['queued', 'paused']), ResearchScope.enabled == True)
                    .order_by(ResearchTask.updated_at, ResearchTask.id).limit(1))
            if task is None:
                if time.time() >= self._next_scan:
                    self._next_scan = time.time() + 60
                    with self.database.sessions() as db:
                        scopes = db.scalars(select(ResearchScope).where(ResearchScope.enabled == True)).all()
                    for scope in scopes:
                        types = json.loads(scope.work_types_json)
                        for kind in (['essay'] if 'essay' in types else []) + (['findings'] if set(types) - {'essay'} else []):
                            try:
                                self.enqueue(scope.collection_id, kind=kind)
                            except HTTPException:
                                pass
                if time.time() - self._quota_at >= 60 and self.profiles.priority.idle(settings.idle_seconds):
                    self._eligible(settings)
                if settings.maintenance_enabled:
                    if self._process_maintenance(settings):
                        return True
                    if self._reason in {'reading', 'foreground_queue', 'hourly_budget', 'account_unavailable',
                                        'quota_unknown', 'quota_stale', 'quota_reserve', 'cooldown',
                                        'maintenance_reading', 'maintenance_error'}:
                        return False
                self._reason = 'up_to_date'
                return False
            with self.database.sessions() as db:
                scope = db.get(ResearchScope, task.collection_id)
                types = json.loads(scope.work_types_json)
                _, current_fingerprint = snapshot(db, task.collection_id, scope.focus, kind=task.kind, work_types=types)
                disabled = task.kind == 'essay' and 'essay' not in types or task.kind == 'findings' and not set(types) - {'essay'}
                if disabled or current_fingerprint != task.fingerprint:
                    stored = db.get(ResearchTask, task.id)
                    stored.status = 'superseded'
                    db.commit()
                    self._next_scan = 0
                    return False
            if not self._eligible(settings, running=task.stage not in ('synthesis', 'discover')):
                return False
            self._step(task.id, settings)
            return True
        finally:
            self._run_lock.release()

    def _step(self, task_id, settings):
        with self._mutation, self.database.sessions() as db:
            task = db.get(ResearchTask, task_id)
            if task is None or task.status not in ACTIVE:
                return
            previous_error = task.error
            task.status, task.error = 'running', None
            task.calls += 1
            usage = json.loads(task.usage_json)
            usage.setdefault('call_times', []).append(time.time())
            task.usage_json = dumps(usage)
            db.commit()
            material, checkpoint, stage = json.loads(task.material_json), json.loads(task.checkpoint_json), task.stage
            previous = db.scalar(select(ResearchRevision).where(ResearchRevision.collection_id == task.collection_id)
                .order_by(ResearchRevision.number.desc()).limit(1))
            previous_text = previous.markdown if previous else None
            existing = list_findings(db, task.collection_id) if task.kind == 'findings' else []
            prior_context = [{**{k: i[k] for k in ('id', 'kind', 'title', 'status')}, 'body': i['body'][:1500],
                              'paper_ids': sorted({s['paper_id'] for s in i['sources']})} for i in existing]
        self._reason = 'working'
        provider = None
        generation_completed = False
        try:
            provider = self.profiles.subscription_provider(settings.profile_id)
            system = (PROMPTS / f'research_{stage}.txt').read_text(encoding='utf-8')
            if stage == 'discover':
                context = {'material': material, 'existing_findings': prior_context}
            elif stage == 'assess':
                context = {'topic': material['collection'], 'focus': material['focus'], 'work_types': material['work_types'],
                    'papers': material['papers'], 'candidates': checkpoint['discover'],
                    'sources': checkpoint['sources'], 'existing_findings': prior_context, 'coverage': material['coverage']}
            elif stage == 'synthesis':
                context = {'material': material, 'previous_article': previous_text}
            elif stage == 'draft':
                context = {'topic': material['collection'], 'focus': material['focus'],
                    'papers': material['papers'], 'synthesis': checkpoint['synthesis'],
                    'sources': checkpoint['sources']}
            else:
                context = {'topic': material['collection'], 'focus': material['focus'],
                    'papers': material['papers'], 'synthesis': checkpoint['synthesis'],
                    'sources': checkpoint['sources'], 'draft': checkpoint['draft'], 'coverage': material['coverage']}
            if previous_error:
                context['previous_validation_error'] = previous_error
            with background_call(self.profiles.priority):
                # Close the race between eligibility and registering cancellation.
                if not self.profiles.priority.idle(settings.idle_seconds) or not self.settings().enabled:
                    raise ProviderError('让出通道', 409, code='background_preempted')
                if self._thread is threading.current_thread() and self._stop.is_set():
                    raise ProviderError('服务已停止', 409, code='background_preempted')
                with self.database.sessions() as db:
                    latest = db.get(ResearchTask, task_id)
                    scope = db.get(ResearchScope, task.collection_id)
                    if not latest or latest.status != 'running' or not scope or not scope.enabled:
                        raise ProviderError('让出通道', 409, code='background_preempted')
                result = provider._complete(system, dumps(context), json_output=True,
                    max_output_tokens=9500 if stage == 'synthesis' else 7500)
                generation_completed = True
                check_background()
            data = json.loads(result)
            if not isinstance(data, dict):
                raise ValueError('研究结果格式无效')
            if stage in ('discover', 'assess'):
                verified = verify_findings(data, {**material, 'sources': checkpoint['sources']} if stage == 'assess' else material, existing)
                checkpoint[stage] = data
                if stage == 'discover':
                    ids = {s['id'] for item in verified for s in item['sources']}
                    checkpoint['sources'] = [s for s in material['sources'] if s['id'] in ids]
            elif stage == 'synthesis':
                checkpoint['sources'] = verify_synthesis(data, material)
                checkpoint['synthesis'] = data
            else:
                verify_article(data, checkpoint['sources'])
                checkpoint[stage] = data
            with self._mutation, self.database.sessions() as db:
                task = db.get(ResearchTask, task_id)
                if task is None or task.status != 'running':
                    return
                scope = db.get(ResearchScope, task.collection_id)
                control = self.settings()
                if not scope or not scope.enabled or not control.enabled or control.profile_id != settings.profile_id:
                    task.status = 'paused'
                    db.commit()
                    return
                types = json.loads(scope.work_types_json)
                _, fingerprint = snapshot(db, task.collection_id, scope.focus, kind=task.kind, work_types=types)
                disabled = task.kind == 'essay' and 'essay' not in types or task.kind == 'findings' and not set(types) - {'essay'}
                if disabled or fingerprint != task.fingerprint:
                    task.status = 'superseded'
                    db.commit()
                    return
                task.checkpoint_json = dumps(checkpoint)
                task.attempts = 0
                task.status = 'queued'
                record_call(task, provider, stage, completed=True)
                if stage == 'assess':
                    publish_findings(db, task, verified, getattr(provider, 'model', 'unknown'))
                    task.status, task.stage = 'completed', 'published'
                    self._reason = 'up_to_date'
                elif stage == 'review':
                    ids = verify_article(data, checkpoint['sources'])
                    # One immutable citation record per source; quote matching is checked above.
                    unique = {s['id']: s for s in checkpoint['sources'] if s['id'] in ids}
                    number = (db.scalar(select(ResearchRevision.number).where(
                        ResearchRevision.collection_id == task.collection_id).order_by(ResearchRevision.number.desc()).limit(1)) or 0) + 1
                    db.add(ResearchRevision(id='essay-' + uuid.uuid4().hex, collection_id=task.collection_id,
                        task_id=task.id, number=number, title=data['title'][:500], dek=data['dek'][:2000],
                        markdown=data['markdown'], changes=data['changes'][:5000],
                        sources_json=dumps(list(unique.values())), coverage_json=dumps(material['coverage']),
                        model=getattr(provider, 'model', 'unknown')))
                    task.status, task.stage = 'completed', 'published'
                    self._reason = 'up_to_date'
                else:
                    task.stage = {'discover': 'assess', 'synthesis': 'draft', 'draft': 'review'}[stage]
                db.commit()
        except (ProviderError, ValueError, KeyError, TypeError) as error:
            with self._mutation, self.database.sessions() as db:
                task = db.get(ResearchTask, task_id)
                if task is None or task.status != 'running':
                    return
                if isinstance(error, ProviderError) and error.code == 'background_preempted':
                    task.status, task.error = 'paused', None
                    self._reason = 'reading'
                else:
                    task.attempts += 1
                    task.status = 'failed' if task.attempts >= 2 else 'queued'
                    task.error = str(error) if isinstance(error, ProviderError) or (task.kind == 'findings' and isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError)) else '研究结果未通过原文或格式校验；已保留上一版'
                    self._reason = 'task_error'
                    self._retry_at = time.time() + 60
                code = error.code if isinstance(error, ProviderError) else 'validation'
                record_call(task, provider, stage, completed=generation_completed, code=code,
                            message=task.error or '已让出阅读通道')
                db.commit()
