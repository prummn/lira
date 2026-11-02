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
from sqlalchemy import case, select

from ..models import Collection, IntelligenceTask, KnowledgeMaintenanceIssue, KnowledgeMaintenanceRun, ResearchControl, ResearchRevision, ResearchScope, ResearchTask, TranslationJob
from ..providers.base import ProviderError
from ..providers.priority import background_call, check_background
from ..research_schemas import ResearchSettings
from .research_materials import dumps, snapshot, snapshot_fingerprint, verify_article, verify_synthesis
from .research_policy import quota_decision, observe_budget
from .research_findings import list_findings, publish_findings, verify_findings, act, history
from . import knowledge_maintenance as maintenance
from . import research_agenda as agenda
from . import research_reading as reading

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
        self._retry_reason = 'cooldown'
        self._quota, self._quota_at = [], 0
        self._quota_error_code = None
        self._quota_attempted_at = 0
        self._quota_using_recent = False
        self._next_scan = 0
        self._next_maintenance_scan = 0
        self._next_reading_scan = 0
        self._budget = None
        self._translation_served = False
        self._research_served = False
        self._translation_claims = {}
        self._translation_urgent = set()
        from .worker_pool import WorkerPool
        self._translation_pool = WorkerPool('lira-translation', self.process_translation,
            self.profiles.worker_parallelism)

    def quota_policy(self, payload):
        # Merge under the same lock as full settings saves so quota edits never
        # overwrite a concurrent change to model routing or optional tasks.
        with self._mutation:
            current = self.settings().model_dump()
            current.update(payload.model_dump(exclude_unset=True))
            try:
                updated = ResearchSettings.model_validate(current)
            except ValueError:
                raise HTTPException(422, '启动阈值必须高于停止阈值') from None
            return self.settings(updated)

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
                self._retry_at = 0
                self._next_reading_scan = 0
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
                self._next_reading_scan = 0
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
                ResearchTask.kind.in_(['findings', 'investigation'])).order_by(ResearchTask.created_at.desc(), ResearchTask.id.desc()).limit(1))
            now = datetime.now(timezone.utc)
            due = sum(i['kind'] == 'review' and i['status'] not in ('dismissed', 'done') and
                      bool(i['due_at']) and datetime.fromisoformat(i['due_at']) <= now for i in items)
            return {'scope': scope, 'items': items, 'task': task_read(task) if task else None, 'due_count': due,
                    'agenda': agenda.agenda_state(db, collection_id, task_read)}

    def plan_research(self, collection_id):
        scope = self.scope(collection_id)
        if not scope['enabled'] or not self.settings().investigations_enabled:
            raise HTTPException(409, '请先开启专题研究与继续深入专题')
        with self._mutation, self.database.sessions() as db:
            task = agenda.enqueue_plan(db, collection_id, scope['focus'], scope['work_types'])
            if task is None:
                raise HTTPException(409, '先完成本轮基础线索整理，再规划后续问题')
            db.commit()
        self._wake.set()
        return task_read(task)

    def reading_questions(self, collection_id):
        scope = self.scope(collection_id)
        if not scope['enabled'] or 'reading' not in scope['work_types'] or not self.settings().investigations_enabled:
            raise HTTPException(409, '请先开启跟进阅读疑问与继续深入专题')
        with self._mutation, self.database.sessions() as db:
            tasks = reading.enqueue_reading(db, db.get(ResearchScope, collection_id))
            db.commit()
        self._wake.set()
        return {'tasks': [task_read(task) for task in tasks]}

    def _current_material(self, db, task, scope):
        types = json.loads(scope.work_types_json)
        material = json.loads(task.material_json)
        if material.get('origin'):
            return reading.current_material(db, scope, material)
        deep = task.kind in agenda.DEEP_KINDS
        current, fingerprint = snapshot(db, task.collection_id, scope.focus,
                                  kind='findings' if deep else task.kind, work_types=types)
        expected = material.get('_base_fingerprint') if deep else task.fingerprint
        disabled = (task.kind == 'essay' and 'essay' not in types or
                    task.kind != 'essay' and not set(types) - {'essay', 'reading'})
        basis = material
        if deep and task.kind == 'investigation':
            parent = db.get(ResearchTask, material.get('_plan_id')) if material.get('_plan_id') else None
            basis = json.loads(parent.material_json) if parent else material
        if disabled or expected != fingerprint and snapshot_fingerprint(basis) != fingerprint:
            return False
        if deep:
            full = material.get('_source_fingerprint')
            if full and full != agenda.source_fingerprint(db, [p['id'] for p in current['papers']]):
                return False
            if not full and not agenda.sources_match(db, material):
                return False
        return task.kind != 'investigation' or agenda.target_active(db, task.collection_id, material['investigation'])

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
            from .translation_queue import monitor_jobs
            from .task_monitor import monitor_analysis_tasks
            translation_jobs = monitor_jobs(db)
            analysis_tasks = monitor_analysis_tasks(db)
        return {'settings': self.settings().model_dump(), 'reason': self._reason,
                'quota': self._quota, 'quota_checked_at': self._quota_at or None,
                'quota_error_code': self._quota_error_code,
                'quota_attempted_at': self._quota_attempted_at or None,
                'quota_using_recent': bool(self._quota_using_recent and time.time()-self._quota_at <= 120),
                'tasks': [task_read(t) for t in tasks], 'scope_ids': [s.collection_id for s in scopes],
                'maintenance': maintenance.serialize_run(maintenance_run) if maintenance_run else None,
                'budget': self._budget, 'translation_jobs': translation_jobs, 'analysis_tasks': analysis_tasks,
                'scheduler': self.profiles.capacity_status()}

    def _observe_budget(self, state, settings):
        # Every profile uses the same official account manager. Hash identity so
        # email is neither exposed in status nor used as a model-profile key.
        identity = hashlib.sha256((state.get('email') or 'official-account').casefold().encode()).hexdigest()
        with self._mutation, self.database.sessions() as db:
            row = db.get(ResearchControl, 1)
            if row is None:
                row = ResearchControl(id=1, settings_json=settings.model_dump_json())
                db.add(row)
                db.flush()
            accounts = json.loads(row.budget_json)
            ledger, self._budget = observe_budget(accounts.get(identity, {}), state.get('limits', []),
                                                  reserve=settings.long_reserve)
            accounts[identity] = ledger
            encoded = dumps(accounts)
            if encoded != row.budget_json:
                row.budget_json = encoded
                db.commit()
        return self._budget

    def _capture_quota(self, state):
        self._quota = state.get('limits', [])
        self._quota_error_code = state.get('limits_error_code')
        self._quota_at = state.get('limits_checked_at') or (time.time() if self._quota and not self._quota_error_code else 0)
        self._quota_attempted_at = state.get('limits_attempted_at') or time.time()
        self._quota_using_recent = bool(self._quota_error_code in {'transport_timeout', 'transport_error', 'codex_account_error'}
            and self._quota and self._quota_at
            and time.time()-self._quota_at <= 120)

    def refresh_quota(self):
        state = self.profiles.codex.status(refresh=True)
        self._capture_quota(state)
        if state.get('authenticated') and not state.get('error_code'):
            self._observe_budget(state, self.settings())
            if (self._quota and not self._quota_error_code and
                    self._retry_reason in {'quota_timeout', 'quota_unavailable', 'quota_unknown', 'account_unavailable'}):
                self._retry_at = 0
                self._wake.set()
        return {'quota': self._quota, 'checked_at': self._quota_at,
                'quota_error_code': self._quota_error_code,
                'quota_attempted_at': self._quota_attempted_at or None,
                'quota_using_recent': self._quota_using_recent,
                'budget': self._budget,
                'available': bool(state.get('authenticated') and not state.get('error_code'))}

    def enqueue(self, collection_id, kind='essay'):
        if kind not in ('essay', 'findings'):
            raise HTTPException(422, '未知研究任务类型')
        with self._mutation:
            scope = self.scope(collection_id)
            if not scope['enabled']:
                raise HTTPException(409, '请先为这个专题开启后台研究')
            if (kind == 'essay' and 'essay' not in scope['work_types']) or (kind == 'findings' and not set(scope['work_types']) - {'essay', 'reading'}):
                raise HTTPException(409, '请先在研究设置中选择这类任务')
            with self.database.sessions() as db:
                material, fingerprint = snapshot(db, collection_id, scope['focus'], kind=kind, work_types=scope['work_types'])
                if not material['sources']:
                    raise HTTPException(409, '专题还没有可读取的论文原文，请先导入 PDF')
                if len(material['papers']) > 40:
                    raise HTTPException(409, '请将研究范围缩小至 40 篇以内，以便充分研读')
                previous = db.scalar(select(ResearchTask).where(ResearchTask.collection_id == collection_id,
                    ResearchTask.fingerprint == fingerprint))
                if previous is None:
                    previous = next((t for t in db.scalars(select(ResearchTask).where(
                        ResearchTask.collection_id == collection_id, ResearchTask.kind == kind))
                        if snapshot_fingerprint(json.loads(t.material_json)) == fingerprint), None)
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
        if not self._translation_pool.can_start():
            return
        if self._thread and self._thread.is_alive():
            if self._stop.is_set():
                raise RuntimeError('Background research is still draining its previous request')
            return
        with self.database.sessions() as db:
            from .translation_queue import recover
            recover(db)
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
        self._translation_pool.start()

    def stop(self):
        self._stop.set()
        self.profiles.priority.cancel()
        self._wake.set()
        self._translation_pool.stop()
        if self._thread:
            self._thread.join(timeout=10)

    def wake(self):
        self._wake.set()
        self._translation_pool.wake()

    def process_translation(self):
        from .translation_queue import process_next
        return process_next(self)[1]

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
                usage['attempts'], usage['retry_at'] = {}, {}
                for issue in run.issues:
                    if issue.status == 'needs_review' and json.loads(issue.proposed_action_json).get('type') == 'curate_paper':
                        issue.status = 'proposed'
                        usage['processed_issue_ids'] = [v for v in usage.get('processed_issue_ids', []) if v != issue.id]
                run.usage_json = dumps(usage)
                self._retry_at = 0
            db.commit()
        self._wake.set()
        return maintenance.serialize_run(run)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.process_next(translations=False)
            except Exception:
                # Exception text can contain model output; never put it in logs.
                logging.getLogger(__name__).error('Background research tick failed; persisted work retained')
                self._reason = 'service_error'
                self._retry_at = time.time() + 60
            self._wake.wait(3)
            self._wake.clear()

    def _eligible(self, settings, running=False, include_maintenance=False, allow_reading=False):
        if not settings.enabled:
            self._reason = 'disabled'
            return False
        profiles = self.profiles.public()['profiles']
        if not any(p['id'] == settings.profile_id and p.get('provider_kind') == 'codex' for p in profiles):
            self._reason = 'profile_required'
            return False
        if self.profiles.priority.foreground_busy():
            self._reason = 'foreground_queue'
            return False
        if not allow_reading and not self.profiles.priority.idle(settings.idle_seconds):
            self._reason = 'reading'
            return False
        with self.database.sessions() as db:
            explicit = db.scalar(select(IntelligenceTask.id).where(IntelligenceTask.status.in_(['queued', 'running'])).limit(1))
            if explicit and not allow_reading:
                self._reason = 'foreground_queue'
                return False
        if not self._remaining_calls(settings):
            self._reason = 'hourly_budget'
            return False
        if time.time() < self._retry_at:
            self._reason = self._retry_reason
            return False
        # Repeated pre-call gates share the official manager's 10-second cache.
        # A failed read never falls back to paid API; explicit refresh still bypasses cache.
        state = self.profiles.codex.status()
        self._capture_quota(state)
        if not state.get('authenticated') or state.get('error_code'):
            self._reason = 'account_unavailable'
            self._retry_reason = self._reason
            self._retry_at = time.time() + 60
            return False
        if self._quota_error_code and not self._quota_using_recent:
            self._reason = 'quota_timeout' if self._quota_error_code == 'transport_timeout' else 'quota_unavailable'
            self._retry_reason = self._reason
            self._retry_at = time.time() + 60
            return False
        decision = quota_decision(self._quota, age=max(0,time.time()-self._quota_at), running=running,
            start_remaining=settings.start_remaining, stop_remaining=settings.stop_remaining,
            long_reserve=settings.long_reserve)
        budget = self._observe_budget(state, settings)
        if decision['allowed'] and not budget['allowed']:
            decision = budget
        self._reason = decision['reason']
        if not decision['allowed']:
            self._retry_at = time.time() + 60
            self._retry_reason = decision['reason']
        else:
            self._retry_reason = 'cooldown'
        return decision['allowed']

    def _remaining_calls(self, settings):
        with self.database.sessions() as db:
            usage = list(db.scalars(select(ResearchTask.usage_json)).all())
            usage.extend(db.scalars(select(KnowledgeMaintenanceRun.usage_json)).all())
            usage.extend(db.scalars(select(TranslationJob.usage_json)).all())
        count = sum(t > time.time() - 3600 for raw in usage for t in json.loads(raw).get('call_times', []))
        return max(0, settings.calls_per_hour - count)

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
                pending = maintenance.ready_audit_issues(db, item)
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
                        maintenance.prepare_run(db, scope_type='collection', scope_id=scope.collection_id, allow_external=True)
                else:
                    maintenance.prepare_run(db, scope_type='library', allow_external=True)
                db.commit()
            except HTTPException:
                db.rollback()
        return None

    def _process_maintenance(self, settings):
        self._maybe_enqueue_maintenance(settings)
        with self.database.sessions() as db:
            research_ready = db.scalar(select(ResearchTask.id).join(ResearchScope,
                ResearchScope.collection_id == ResearchTask.collection_id).where(
                ResearchTask.status.in_(['queued', 'running', 'paused']), ResearchScope.enabled == True)
                .where(True if settings.investigations_enabled else ~ResearchTask.kind.in_(agenda.DEEP_KINDS)).limit(1))
            if research_ready and not self._research_served:
                self._reason = 'research_queue'
                return False
            runs = db.scalars(select(KnowledgeMaintenanceRun).where(
                KnowledgeMaintenanceRun.status.in_(['queued', 'partial'])
            ).order_by(KnowledgeMaintenanceRun.created_at, KnowledgeMaintenanceRun.id)).all()
            runs.sort(key=lambda item: not bool(json.loads(item.usage_json).get('call_times')))
            run = None
            for item in runs:
                if item.status == 'queued':
                    run = item
                    break
                pending = maintenance.ready_audit_issues(db, item)
                if pending:
                    run = item
                    break
        if run is None:
            return False
        started = bool(json.loads(run.usage_json).get('call_times'))
        if not self._eligible(settings, running=started, include_maintenance=True):
            return False
        did_work = False
        try:
            provider = self.profiles.subscription_provider(settings.profile_id)
            for step in range(min(1 if research_ready else settings.maintenance_calls_per_run, self._remaining_calls(settings))):
                # Commit each checkpoint before another quota read. This also
                # lets foreground work and settings changes stop a long batch.
                if step and not self._eligible(settings, running=True, include_maintenance=True):
                    return did_work
                self._reason = 'maintenance_working'
                with background_call(self.profiles.priority):
                    control = self.settings()
                    if (not self.profiles.priority.idle(settings.idle_seconds) or not control.enabled
                            or not control.maintenance_enabled or control.profile_id != settings.profile_id):
                        self._reason = 'maintenance_reading'
                        return did_work
                    with self.database.sessions() as db:
                        current = db.get(KnowledgeMaintenanceRun, run.id)
                        if current is None or current.status not in {'queued', 'partial'}:
                            return did_work
                        maintenance.execute_run(db, current, provider, max_calls=1)
                        db.commit()
                        did_work = True
                        self._research_served = False
                        if current.status == 'partial':
                            self._reason = 'maintenance_error' if current.error_message and '调用上限' not in current.error_message else 'maintenance_partial'
                            if self._reason == 'maintenance_error':
                                self._retry_at = time.time() + 60
                                break
                        else:
                            self._reason = 'up_to_date'
                            break
            return did_work
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

    def process_next(self, *, translations=True):
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
                unfinished = db.scalars(select(KnowledgeMaintenanceRun).where(KnowledgeMaintenanceRun.status == 'running')).all()
                for run in unfinished:
                    run.status = 'partial'
                    run.error_message = '上次整理中断，已完成的论文检查点保留，可继续'
                if stranded or unfinished:
                    db.commit()
            settings = self.settings()
            from .translation_queue import process_next as process_translation
            with self.database.sessions() as db:
                research_waiting = db.scalar(select(ResearchTask.id).join(ResearchScope,
                    ResearchScope.collection_id == ResearchTask.collection_id).where(
                    ResearchTask.status.in_(['queued','paused','running']), ResearchScope.enabled == True)
                    .where(True if settings.investigations_enabled else ~ResearchTask.kind.in_(agenda.DEEP_KINDS)).limit(1)) is not None
                maintenance_waiting = settings.maintenance_enabled and db.scalar(select(KnowledgeMaintenanceRun.id).where(
                    KnowledgeMaintenanceRun.status.in_(['queued','partial'])).limit(1)) is not None
            # Alternate with research when research can actually run. Reading
            # does not pause translation or hand a turn to blocked research.
            translation_pending, translated = process_translation(self,
                allow_idle=not ((research_waiting or maintenance_waiting) and self._translation_served
                    and self.profiles.priority.idle(settings.idle_seconds))) if translations else (False, False)
            if translation_pending:
                self._translation_served = translated and not self._translation_manual
                return translated
            self._translation_served = False
            if not settings.enabled:
                self._reason = 'disabled'
                return False
            # Reserve a serial checkpoint for knowledge work between research
            # stages; an endless essay/planning queue must not starve curation.
            if settings.maintenance_enabled and self._research_served:
                if self._process_maintenance(settings):
                    return True
            if settings.investigations_enabled and time.time() >= self._next_reading_scan:
                self._next_reading_scan = time.time() + 60
                with self._mutation, self.database.sessions() as db:
                    for scope in db.scalars(select(ResearchScope).where(ResearchScope.enabled == True)):
                        reading.enqueue_reading(db, scope)
                    db.commit()
            with self.database.sessions() as db:
                task = db.scalar(select(ResearchTask).join(ResearchScope,
                    ResearchScope.collection_id == ResearchTask.collection_id).where(
                    ResearchTask.status.in_(['queued', 'paused']), ResearchScope.enabled == True)
                    .where(True if settings.investigations_enabled else ~ResearchTask.kind.in_(agenda.DEEP_KINDS))
                    .order_by(case((ResearchTask.stage.in_(['assess', 'draft', 'review']), 0), else_=1),
                              case((ResearchTask.calls > 0, 0), else_=1),
                              case((ResearchTask.material_json.like('%"origin":%'), 0), else_=1),
                              ResearchTask.updated_at, ResearchTask.id).limit(1))
            if task is None:
                if time.time() >= self._next_scan:
                    self._next_scan = time.time() + 60
                    with self.database.sessions() as db:
                        scopes = db.scalars(select(ResearchScope).where(ResearchScope.enabled == True)).all()
                    for scope in scopes:
                        types = json.loads(scope.work_types_json)
                        for kind in (['essay'] if 'essay' in types else []) + (['findings'] if set(types) - {'essay', 'reading'} else []):
                            try:
                                self.enqueue(scope.collection_id, kind=kind)
                            except HTTPException:
                                pass
                        if settings.investigations_enabled:
                            with self._mutation, self.database.sessions() as db:
                                agenda.enqueue_plan(db, scope.collection_id, scope.focus, types)
                                db.commit()
                if settings.maintenance_enabled:
                    if self._process_maintenance(settings):
                        return True
                    if self._reason in {'reading', 'foreground_queue', 'hourly_budget', 'account_unavailable',
                                        'quota_unknown', 'quota_stale', 'quota_reserve', 'cooldown',
                                        'quota_timeout', 'quota_unavailable',
                                        'daily_budget',
                                        'maintenance_reading', 'maintenance_error'}:
                        return False
                if time.time() - self._quota_at >= 60 and self.profiles.priority.idle(settings.idle_seconds):
                    if not self._eligible(settings):
                        return False
                self._reason = 'up_to_date'
                return False
            if not self._eligible(settings, running=task.calls > 0 or task.stage not in ('synthesis', 'discover', 'plan')):
                return False
            with self.database.sessions() as db:
                scope = db.get(ResearchScope, task.collection_id)
                if not self._current_material(db, task, scope):
                    stored = db.get(ResearchTask, task.id)
                    stored.status = 'superseded'
                    db.commit()
                    self._next_scan = 0
                    return False
            self._step(task.id, settings)
            self._research_served = True
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
            existing = list_findings(db, task.collection_id) if task.kind != 'essay' else []
            prior_context = [{**{k: i[k] for k in ('id', 'kind', 'title', 'status')}, 'body': i['body'][:1500],
                              'paper_ids': sorted({s['paper_id'] for s in i['sources']})} for i in existing]
        self._reason = 'working'
        provider = None
        generation_completed = False
        data = None
        try:
            provider = self.profiles.subscription_provider(settings.profile_id)
            prompt_stage = 'investigate' if task.kind == 'investigation' and stage == 'discover' else stage
            if material.get('origin') and stage == 'discover':
                prompt_stage = 'reading'
            system = (PROMPTS / f'research_{prompt_stage}.txt').read_text(encoding='utf-8')
            if task.kind == 'investigation':
                system += '\n本项是定向深入研读，保留讲透机制所需篇幅，不把答案压成摘要。历史解释只是线索，须核对原文。'
                if material.get('origin'):
                    system += '\n本项是个人阅读疑问，只输出kind=reading；直接回答问题，不称为领域未知。'
                if stage == 'discover' and material.get('section_index'):
                    system += ('\n本项已经扩读，请根据实际覆盖回答，不得再次索取。' if checkpoint.get('expanded') else
                        '\n若关键上下文缺失，可返回 {"read_more":[{"paper_id":"目标论文id","sections":["目录中的准确章节名"],'
                        '"reason":"为什么需要"}]}；至多一次，每篇至多三节，最多四篇，新增至多64000字符。')
            if stage == 'plan':
                with self.database.sessions() as db:
                    context = agenda.plan_context(db, material, task.collection_id)
            elif stage == 'discover':
                context = {'material': material, 'existing_findings': prior_context}
            elif stage == 'assess':
                context = {'topic': material['collection'], 'focus': material['focus'], 'work_types': material['work_types'],
                    'papers': material['papers'], 'candidates': checkpoint['discover'],
                    'sources': checkpoint['sources'], 'existing_findings': prior_context, 'coverage': material['coverage']}
                if task.kind == 'investigation':
                    context['investigation'] = material['investigation']
                    context['origin'] = material.get('origin')
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
            if checkpoint.get('validation_stage') == stage:
                context['rejected_draft'] = checkpoint.get('validation_draft')
                system += '\n上次草稿未通过本地校验。rejected_draft保留了待修稿，请按previous_validation_error定点修正；引文须重新从本轮sources逐字摘取，不能沿用不匹配的改写。'
            with background_call(self.profiles.priority):
                # Close the race between eligibility and registering cancellation.
                if not self.profiles.priority.idle(settings.idle_seconds) or not self.settings().enabled:
                    raise ProviderError('让出通道', 409, code='background_preempted')
                if task.kind in agenda.DEEP_KINDS and not self.settings().investigations_enabled:
                    raise ProviderError('已暂停深入研究', 409, code='background_preempted')
                if self._thread is threading.current_thread() and self._stop.is_set():
                    raise ProviderError('服务已停止', 409, code='background_preempted')
                with self.database.sessions() as db:
                    latest = db.get(ResearchTask, task_id)
                    scope = db.get(ResearchScope, task.collection_id)
                    if not latest or latest.status != 'running' or not scope or not scope.enabled:
                        raise ProviderError('让出通道', 409, code='background_preempted')
                    if not self._current_material(db, latest, scope):
                        latest.status = 'superseded'
                        db.commit()
                        return
                result = provider._complete(system, dumps(context), json_output=True,
                    max_output_tokens=4000 if stage == 'plan' else 9500 if stage == 'synthesis' else 7500)
                generation_completed = True
                check_background()
            data = json.loads(result)
            if not isinstance(data, dict):
                raise ValueError('研究结果格式无效')
            checkpoint.pop('validation_draft', None)
            checkpoint.pop('validation_stage', None)
            expanded_material = None
            reused_answer = None
            if stage == 'discover' and material.get('origin') and 'answered_by' in data:
                with self.database.sessions() as db:
                    reused_answer = reading.answer_reference(db, task.collection_id, material, data)
                checkpoint.update(reused_answer=reused_answer, reuse_reason=data['reason'])
            elif stage == 'discover' and task.kind == 'investigation' and 'read_more' in data:
                if checkpoint.get('expanded'):
                    raise ValueError('本项扩读次数已用完，请基于现有材料回答')
                with self.database.sessions() as db:
                    expanded_material = agenda.expand_material(db, material, data['read_more'])
                checkpoint.update(expanded=True, read_requests=data['read_more'])
            elif stage == 'plan':
                briefs = agenda.validate_plan(data, material, existing)
                checkpoint['plan'] = briefs
            elif stage in ('discover', 'assess'):
                if task.kind == 'investigation' and len(data.get('findings', [])) > 2:
                    raise ValueError('定向研究每项至多保留两条结果')
                if task.kind == 'investigation':
                    agenda.bind_target(data, material)
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
                if not scope or not scope.enabled or not control.enabled or control.profile_id != settings.profile_id or (task.kind in agenda.DEEP_KINDS and not control.investigations_enabled):
                    task.status = 'paused'
                    db.commit()
                    return
                if not self._current_material(db, task, scope):
                    task.status = 'superseded'
                    record_call(task, provider, stage, completed=True, code='superseded',
                                message='材料或研究者的选择已变化，结果未发布')
                    db.commit()
                    return
                task.checkpoint_json = dumps(checkpoint)
                task.attempts = 0
                task.status = 'queued'
                record_call(task, provider, stage, completed=True)
                if reused_answer is not None:
                    reading.answer_reference(db, task.collection_id, material, data)
                    task.status, task.stage = 'completed', 'published'
                    self._reason = 'up_to_date'
                elif expanded_material is not None:
                    task.material_json = dumps(expanded_material)
                    task.stage = 'discover'
                elif stage == 'plan':
                    agenda.create_investigations(db, task, briefs)
                    task.status, task.stage = 'completed', 'planned'
                    self._reason = 'up_to_date'
                elif stage == 'assess':
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
                    task.error = str(error) if isinstance(error, ProviderError) or (task.kind != 'essay' and isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError)) else '研究结果未通过原文或格式校验；已保留上一版'
                    if isinstance(error, ValueError) and isinstance(data, dict):
                        saved = json.loads(task.checkpoint_json)
                        saved.update(validation_draft=data, validation_stage=stage)
                        task.checkpoint_json = dumps(saved)
                    self._reason = 'task_error'
                    self._retry_at = time.time() + 60
                code = error.code if isinstance(error, ProviderError) else 'validation'
                record_call(task, provider, stage, completed=generation_completed, code=code,
                            message=task.error or '已让出阅读通道')
                db.commit()
