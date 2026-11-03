"""Optional research shares capacity with reading; all stores are temporary."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

from app.models import CollectionPaper, KnowledgeMaintenanceRun, ResearchTask
from app.providers.priority import check_background, scheduled_work
from app.providers.profiles import ProfileStore
from app.research_schemas import ScopeUpdate
from app.services.knowledge_maintenance import prepare_run
from test_background_research import research, Writer, MaintenanceWriter


def test_reader_reserves_one_position_while_background_uses_the_rest(tmp_path):
    store = ProfileStore(tmp_path / 'models.json')
    store.set_codex_concurrency(3)
    store.priority.presence('reader', True)
    release = threading.Event()
    entered = [threading.Event() for _ in range(3)]
    def run(index):
        with scheduled_work(4), store.capacity('codex-subscription', 3):
            entered[index].set()
            assert release.wait(4)
            check_background()
    with ThreadPoolExecutor(3) as pool:
        jobs = [pool.submit(run, i) for i in range(3)]
        try:
            assert entered[0].wait(2) and entered[1].wait(2)
            assert not entered[2].wait(.15), 'background consumed the reserved interactive position'
            with store.capacity('codex-subscription', 3):
                assert store.capacity_status()['official']['active'] == 3
            store.priority.presence('reader', False)
            assert entered[2].wait(2), 'idle capacity was not borrowed'
        finally:
            release.set()
        for job in jobs:
            job.result(3)


def test_independent_topics_run_together_and_foreground_does_not_discard_results(research):
    _, worker = research
    with worker.database.sessions() as db:
        db.add(CollectionPaper(collection_id='other', paper_id='p2'))
        db.commit()
    worker.scope('other', ScopeUpdate(enabled=True, focus='Other memory mechanism'))
    tasks = [worker.enqueue(topic) for topic in ('topic', 'other')]
    entered = threading.Barrier(3)
    release = threading.Event()
    class BlockingWriter(Writer):
        def _complete(self, *args, **kwargs):
            entered.wait(timeout=3)
            assert release.wait(4)
            check_background()
            return super()._complete(*args, **kwargs)
    worker.profiles.subscription_provider = lambda _: BlockingWriter()
    worker.profiles.priority.presence('reader', True)
    with ThreadPoolExecutor(2) as pool:
        calls = [pool.submit(worker.process_next, translations=False) for _ in tasks]
        try:
            entered.wait(timeout=3)
            # No third worker may claim the same collection's in-flight step.
            assert not worker.process_next(translations=False)
            worker.profiles.priority.foreground()
        finally:
            release.set()
        for call in calls:
            assert call.result(4)
    with worker.database.sessions() as db:
        jobs = [db.get(ResearchTask, task['id']) for task in tasks]
        # p2's fixture has different text, so use call/retention rather than
        # requiring its deliberately mismatched synthesis quote to validate.
        assert all(job.calls == 1 for job in jobs)
        assert db.get(ResearchTask, tasks[0]['id']).stage == 'draft'


def test_one_curation_batch_checks_distinct_papers_concurrently_without_losing_progress(research):
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    worker.settings(worker.settings().model_copy(update={'maintenance_enabled': True}))
    with worker.database.sessions() as db:
        run = prepare_run(db, scope_type='library', allow_external=False)
        run_id = run.id
        db.commit()
    entered = threading.Barrier(3)
    release = threading.Event()
    paper_ids = []
    class BlockingCurator(MaintenanceWriter):
        def audit_knowledge_bundle(self, bundle):
            paper_ids.append(bundle['paper_id'])
            entered.wait(timeout=3)
            assert release.wait(4)
            check_background()
            return super().audit_knowledge_bundle(bundle)
    worker.profiles.subscription_provider = lambda _: BlockingCurator()
    worker.profiles.priority.presence('reader', True)
    with ThreadPoolExecutor(2) as pool:
        calls = [pool.submit(worker.process_next, translations=False) for _ in range(2)]
        try:
            entered.wait(timeout=3)
            assert len(set(paper_ids)) == 2
            row = next(row for row in worker.status()['maintenance_tasks'] if row['id'] == run_id)
            assert len(row['active_papers']) == 2
            assert not worker.process_next(translations=False)
            worker.profiles.priority.foreground()
        finally:
            release.set()
        for call in calls:
            assert call.result(4)
    with worker.database.sessions() as db:
        run = db.get(KnowledgeMaintenanceRun, run_id)
        usage = json.loads(run.usage_json)
        assert run.status == 'complete', run.error_message
        assert len(usage['processed_issue_ids']) == 2
        assert len(usage['call_times']) == 2
        assert usage['total_tokens'] == 104


def test_parallel_optional_calls_cannot_overrun_hourly_budget(research):
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    worker.settings(worker.settings().model_copy(update={'maintenance_enabled': True, 'calls_per_hour': 1}))
    with worker.database.sessions() as db:
        run = prepare_run(db, scope_type='library', allow_external=False)
        db.commit()
    entered, release = threading.Event(), threading.Event()
    calls = []
    class Curator(MaintenanceWriter):
        def audit_knowledge_bundle(self, bundle):
            calls.append(bundle)
            entered.set()
            assert release.wait(4)
            return super().audit_knowledge_bundle(bundle)
    worker.profiles.subscription_provider = lambda _: Curator()
    with ThreadPoolExecutor(1) as pool:
        first = pool.submit(worker.process_next, translations=False)
        try:
            assert entered.wait(2)
            assert not worker.process_next(translations=False)
            assert len(calls) == 1
        finally:
            release.set()
        assert first.result(4)
    assert worker._remaining_calls(worker.settings()) == 0


def test_foreground_already_using_reserved_position_does_not_leave_another_empty(tmp_path):
    store = ProfileStore(tmp_path / 'models.json')
    store.set_codex_concurrency(3)
    release = threading.Event()
    entered = threading.Barrier(3)
    def run():
        with scheduled_work(4), store.capacity('codex-subscription', 3):
            entered.wait(timeout=2)
            assert release.wait(3)
    with ThreadPoolExecutor(2) as pool:
        with store.capacity('codex-subscription', 3):
            jobs = [pool.submit(run) for _ in range(2)]
            try:
                entered.wait(timeout=2)
                assert store.capacity_status()['official']['active'] == 3
            finally:
                release.set()
        for job in jobs:
            job.result(3)


def test_official_early_week_reset_retires_previous_daily_budget():
    from app.services.research_policy import observe_budget
    now = time.time()
    windows = [dict(name='secondary', limit_id='codex', used_percent=83,
                    window_minutes=10080, resets_at=now+8*86400)]
    ledger, _ = observe_budget({}, windows, now=now, reserve=0)
    windows[0]['used_percent'] = 92
    windows[0]['resets_at'] = now+86400
    ledger, blocked = observe_budget(ledger, windows, now=now+10, reserve=0)
    assert not blocked['allowed']
    # A rollback without a new official period must not replenish anything.
    windows[0]['used_percent'] = 0
    _, rolled_back = observe_budget(ledger, windows, now=now+20, reserve=0)
    assert not rolled_back['allowed']
    # An early reset changes both the usage and the period by several days.
    windows[0]['resets_at'] = now+7*86400
    _, reset = observe_budget(ledger, windows, now=now+30, reserve=0)
    assert reset['allowed'] and reset['observed_use'] == 0
    assert reset['remaining'] > 14


def test_overlapping_batches_do_not_check_same_paper_twice_and_cancel_is_local(research):
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    worker.settings(worker.settings().model_copy(update={'maintenance_enabled': True}))
    with worker.database.sessions() as db:
        library = prepare_run(db, scope_type='library', allow_external=False)
        duplicate = prepare_run(db, scope_type='papers', paper_ids=['p1'], allow_external=False)
        library_id, duplicate_id = library.id, duplicate.id
        db.commit()
    entered, release = threading.Event(), threading.Event()
    calls = []
    class Curator(MaintenanceWriter):
        def audit_knowledge_bundle(self, bundle):
            calls.append(bundle['paper_id'])
            entered.set()
            assert release.wait(4)
            check_background()
            return super().audit_knowledge_bundle(bundle)
    worker.profiles.subscription_provider = lambda _: Curator()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(worker.process_next, translations=False)
        try:
            assert entered.wait(2)
            second = pool.submit(worker.process_next, translations=False)
            deadline = time.monotonic()+2
            while len(calls) < 2 and time.monotonic() < deadline:
                time.sleep(.01)
            assert sorted(calls) == ['p1', 'p2']
            assert not worker.process_next(translations=False)
            # Cancelling the duplicate must not interrupt either owned request.
            worker.maintenance_action(duplicate_id, 'cancel')
        finally:
            release.set()
        assert first.result(4) and second.result(4)
    with worker.database.sessions() as db:
        assert db.get(KnowledgeMaintenanceRun, library_id).status == 'complete'
        assert db.get(KnowledgeMaintenanceRun, duplicate_id).status == 'cancelled'


def test_parallel_curation_resolves_one_canonical_entity_from_fresh_state(research):
    from app.models import KnowledgeCandidate, KnowledgeEntity, PaperChunk
    from sqlalchemy import select
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    worker.settings(worker.settings().model_copy(update={'maintenance_enabled': True}))
    with worker.database.sessions() as db:
        db.get(PaperChunk, 'c2').content = 'The agent stores experience in external memory.'
        run = prepare_run(db, scope_type='library', allow_external=False)
        run_id = run.id
        db.commit()
    entered = threading.Barrier(2)
    class Curator(MaintenanceWriter):
        def audit_knowledge_bundle(self, bundle):
            entered.wait(timeout=3)
            return dict(summary='Checked memory', candidates=[dict(name='Memory', entity_type='method',
                role='used', confidence=.99, citations=[dict(chunk_id=bundle['chunks'][0]['chunk_id'],
                quote='The agent stores experience in external memory.')])])
    worker.profiles.subscription_provider = lambda _: Curator()
    with ThreadPoolExecutor(2) as pool:
        calls = [pool.submit(worker.process_next, translations=False) for _ in range(2)]
        assert all(call.result(5) for call in calls)
    with worker.database.sessions() as db:
        assert db.get(KnowledgeMaintenanceRun, run_id).status == 'complete'
        entities = db.scalars(select(KnowledgeEntity)).all()
        objects = db.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.status == 'confirmed')).all()
        assert len(entities) == 1 and len(objects) == 2
        assert all(obj.entity_id == entities[0].id for obj in objects)


def test_single_position_can_still_run_background_during_reading(tmp_path):
    store = ProfileStore(tmp_path / 'models.json')
    store.set_codex_concurrency(1)
    store.priority.presence('reader', True)
    with scheduled_work(4), store.capacity('codex-subscription', 1):
        store.priority.foreground()
        check_background()
        assert store.capacity_status()['official']['active'] == 1


def test_batch_with_every_paper_already_checked_finishes_without_model_call(research):
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    worker.settings(worker.settings().model_copy(update={'maintenance_enabled': True}))
    writer = MaintenanceWriter()
    worker.profiles.subscription_provider = lambda _: writer
    assert worker.process_next(translations=False)
    assert worker.process_next(translations=False)
    count = len(writer.calls)
    with worker.database.sessions() as db:
        run = prepare_run(db, scope_type='collection', scope_id='topic', allow_external=False)
        run_id = run.id
        assert json.loads(run.usage_json)['audit_issue_ids'] == []
        db.commit()
    assert worker.process_next(translations=False)
    with worker.database.sessions() as db:
        assert db.get(KnowledgeMaintenanceRun, run_id).status == 'complete'
    assert len(writer.calls) == count


def test_slow_cancellation_check_cannot_hold_the_shared_admission_lock(tmp_path):
    store = ProfileStore(tmp_path / 'models.json')
    checking, release, foreground = threading.Event(), threading.Event(), threading.Event()
    def check():
        checking.set()
        assert release.wait(3)
    def background():
        with scheduled_work(4, check), store.capacity('codex-subscription', 4):
            pass
    def question():
        with store.capacity('codex-subscription', 4):
            foreground.set()
    with ThreadPoolExecutor(2) as pool:
        background_job = pool.submit(background)
        try:
            assert checking.wait(1)
            question_job = pool.submit(question)
            assert foreground.wait(.5), 'slow background state lookup blocked an unused foreground position'
        finally:
            release.set()
        background_job.result(3)
        question_job.result(3)


def test_old_curation_result_is_not_applied_after_cancel_and_fast_retry(research):
    from app.models import Paper, PaperChunk
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    worker.settings(worker.settings().model_copy(update={'maintenance_enabled': True}))
    with worker.database.sessions() as db:
        db.add(Paper(id='p3', title='Third paper'))
        db.flush()
        db.add(PaperChunk(id='c3', paper_id='p3', content='Memory guides the agent.'))
        run_id = prepare_run(db, scope_type='library', allow_external=False).id
        db.commit()
    entered = threading.Barrier(3)
    old_release, fresh_entered, fresh_release = threading.Event(), threading.Event(), threading.Event()
    calls = []
    class Curator(MaintenanceWriter):
        def audit_knowledge_bundle(self, bundle):
            calls.append(bundle['paper_id'])
            if len(calls) <= 2:
                entered.wait(timeout=3)
                assert old_release.wait(4)
            else:
                fresh_entered.set()
                assert fresh_release.wait(4)
            return super().audit_knowledge_bundle(bundle)
    worker.profiles.subscription_provider = lambda _: Curator()
    with ThreadPoolExecutor(3) as pool:
        old = [pool.submit(worker.process_next, translations=False) for _ in range(2)]
        try:
            entered.wait(timeout=3)
            worker.maintenance_action(run_id, 'cancel')
            worker.maintenance_action(run_id, 'retry')
            fresh = pool.submit(worker.process_next, translations=False)
            assert fresh_entered.wait(2)
            old_release.set()
            for job in old:
                job.result(3)
            with worker.database.sessions() as db:
                usage = json.loads(db.get(KnowledgeMaintenanceRun, run_id).usage_json)
                assert not usage.get('paper_audits'), 'cancelled generation was admitted after retry'
        finally:
            old_release.set()
            fresh_release.set()
        fresh.result(4)


def test_automatic_curation_skips_demo_papers_in_new_and_legacy_batches(research):
    from app.models import Paper
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    worker.settings(worker.settings().model_copy(update={'maintenance_enabled': True}))
    with worker.database.sessions() as db:
        # Legacy batches may already contain a now-hidden demo paper.
        run_id = prepare_run(db, scope_type='library', allow_external=False).id
        db.get(Paper, 'p1').is_demo = True
        db.commit()
        fresh = prepare_run(db, scope_type='library', allow_external=False, force=True)
        assert len(json.loads(fresh.usage_json)['audit_issue_ids']) == 1
        db.rollback()  # Scope check only; do not request a forced second audit.
    writer = MaintenanceWriter()
    worker.profiles.subscription_provider = lambda _: writer
    for _ in range(3):
        worker.process_next(translations=False)
    assert [bundle['paper_id'] for bundle in writer.calls] == ['p2']
    with worker.database.sessions() as db:
        assert db.get(KnowledgeMaintenanceRun, run_id).status == 'complete'


def test_metadata_lookup_releases_checkpoint_lock_for_interaction(research, monkeypatch):
    import httpx
    from app.services import publication_metadata
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    worker.settings(worker.settings().model_copy(update={'maintenance_enabled': True}))
    worker.profiles.subscription_provider = lambda _: MaintenanceWriter()
    entered, release = threading.Event(), threading.Event()
    def handle(request):
        entered.set()
        assert release.wait(3)
        return httpx.Response(200, json={'results': [], 'message': {'items': []}})
    original = publication_metadata.enrich_publication
    def enrich(session, paper, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            return original(session, paper, client=client, **kwargs)
    monkeypatch.setattr(publication_metadata, 'enrich_publication', enrich)
    with worker.database.sessions() as db:
        prepare_run(db, scope_type='library', allow_external=True)
        db.commit()
    with ThreadPoolExecutor(2) as pool:
        audit = pool.submit(worker.process_next, translations=False)
        try:
            assert entered.wait(2)
            interaction = pool.submit(worker.settings)
            assert interaction.result(.5).enabled
        finally:
            release.set()
        assert audit.result(4)


def test_toggling_curation_does_not_discard_an_independent_essay(research):
    _, worker = research
    worker.settings(worker.settings().model_copy(update={'maintenance_enabled': True}))
    class EssayWriter(Writer):
        def _complete(self, *args, **kwargs):
            control = worker.settings()
            worker.settings(control.model_copy(update={'maintenance_enabled': False}))
            worker.settings(control)
            return super()._complete(*args, **kwargs)
    worker.profiles.subscription_provider = lambda _: EssayWriter()
    task = worker.enqueue('topic')
    assert worker.process_next(translations=False)
    with worker.database.sessions() as db:
        assert db.get(ResearchTask, task['id']).stage == 'draft'
