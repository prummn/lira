"""Concurrent queue invariants; temporary stores only, never real model calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import threading
import time

import pytest
from sqlalchemy import select

from app.models import Paper, PaperChunk, IntelligenceTask, TranslationItem
from app.providers.base import ProviderError
from app.providers.priority import scheduled_work
from app.providers.profiles import ProfileStore
from test_translation_queue import queue, enqueue, latest


def test_default_four_and_explicit_limit_survive_reload(tmp_path):
    store = ProfileStore(tmp_path / 'models.json')
    assert store.codex_concurrency() == 4
    store.set_codex_concurrency(3)
    assert ProfileStore(store.path).codex_concurrency() == 3


def test_background_can_borrow_all_slots_and_foreground_wins_next(tmp_path):
    store = ProfileStore(tmp_path / 'models.json')
    store.set_codex_concurrency(2)
    release = threading.Event()
    entered = [threading.Event(), threading.Event()]
    order = []
    def call(name, rank, block=None):
        with scheduled_work(rank) if rank else nullcontext():
            with store.capacity('codex-subscription', 2):
                order.append(name)
                if block is not None:
                    entered[block].set()
                    assert release.wait(3)
    with ThreadPoolExecutor(4) as pool:
        first = pool.submit(call, 'a', 2, 0)
        second = pool.submit(call, 'b', 2, 1)
        try:
            assert all(event.wait(1) for event in entered)
            background = pool.submit(call, 'later', 3)
            foreground = pool.submit(call, 'question', 0)
            deadline = time.monotonic() + 1
            while not store.priority.foreground_busy() and time.monotonic() < deadline:
                time.sleep(.005)
            assert store.priority.foreground_busy()
        finally:
            release.set()
        for future in (first, second, background, foreground):
            future.result(2)
    assert order[2:] == ['question', 'later']


def test_rate_limit_reduces_effective_capacity_without_changing_saved_choice(tmp_path):
    store = ProfileStore(tmp_path / 'models.json')
    store.set_codex_concurrency(4)
    with pytest.raises(ProviderError):
        with store.capacity('codex-subscription', 4):
            raise ProviderError('limited', 429, code='rate_limit', retryable=True, retry_after=30)
    state = store.capacity_status()['official']
    assert state['configured'] == 4 and state['effective'] == 2
    assert state['active'] == 0 and state['waiting'] == 0
    assert ProfileStore(store.path).codex_concurrency() == 4


def test_already_waiting_translation_can_be_promoted(tmp_path):
    store = ProfileStore(tmp_path / 'models.json')
    priorities, order = {'first': 2, 'promoted': 2}, []
    def run(name):
        with scheduled_work(lambda: priorities[name]), store.capacity('api', 1):
            order.append(name)
    with ThreadPoolExecutor(2) as pool:
        with store.capacity('api', 1):
            first = pool.submit(run, 'first')
            deadline = time.monotonic() + 1
            while store.capacity_status()['waiting'] < 1 and time.monotonic() < deadline:
                time.sleep(.005)
            second = pool.submit(run, 'promoted')
            deadline = time.monotonic() + 1
            while store.capacity_status()['waiting'] < 2 and time.monotonic() < deadline:
                time.sleep(.005)
            priorities['promoted'] = 1
        first.result(2)
        second.result(2)
    assert order == ['promoted', 'first']


def test_two_paragraphs_of_same_paper_finish_independently_without_duplicate_calls(queue):
    _, worker, provider, _, _ = queue
    enqueue(queue)
    entered = threading.Barrier(3)
    release = threading.Event()
    def block():
        entered.wait(timeout=2)
        assert release.wait(3)
    provider.during = block
    with ThreadPoolExecutor(2) as pool:
        tasks = [pool.submit(worker.process_translation) for _ in range(2)]
        try:
            entered.wait(timeout=2)
        finally:
            release.set()
        for task in tasks:
            assert task.result(3)
    assert len(provider.calls) == len(set(provider.calls)) == 2
    assert latest(queue)['status'] == 'completed'


def test_shared_selected_and_full_work_is_claimed_only_once(queue):
    _, worker, provider, _, paragraphs = queue
    enqueue(queue, [paragraphs[0]['id']])
    enqueue(queue, mode='full')
    entered, release = threading.Event(), threading.Event()
    def block():
        entered.set()
        assert release.wait(3)
    provider.during = block
    with ThreadPoolExecutor(1) as pool:
        first = pool.submit(worker.process_translation)
        try:
            assert entered.wait(1)
            with worker.database.sessions() as db:
                ids = db.scalars(select(TranslationItem.id).where(TranslationItem.source_text == paragraphs[0]['source_text'])).all()
                assert len(ids) == 2
            # A second worker may do the other paragraph, but cannot claim this source.
            from app.services.translation_queue import claim_next
            with claim_next(worker) as candidate:
                assert candidate is not None
                assert candidate[1] not in ids
        finally:
            release.set()
        assert first.result(3)
    assert provider.calls == [paragraphs[0]['source_text']]


def test_stable_paragraphs_share_paper_access_but_review_waits():
    from app.services.translations import source_lock
    lock = source_lock('sqlite:///fixture', 'parallel-lock', 'first')
    release, entered = threading.Event(), threading.Event()
    def review():
        with lock:
            entered.set()
    with ThreadPoolExecutor(1) as pool:
        with lock.translation('first'), lock.translation('second'):
            pending = pool.submit(review)
            assert not entered.wait(.05)
        pending.result(1)
    assert entered.is_set()


def test_independent_analyses_are_claimed_concurrently(client, monkeypatch):
    from app.services.intelligence import queue_tasks
    from test_intelligence_jobs import FailingProvider
    worker = client.app.state.intelligence_worker
    worker.stop()
    provider = FailingProvider()
    with worker.database.sessions() as db:
        for i in range(2):
            db.add(Paper(id=f'parallel-{i}', title=f'Parallel {i}'))
            db.flush()
            db.add(PaperChunk(id=f'parallel-source-{i}', paper_id=f'parallel-{i}', page=1,
                content='The method stores observations for future decisions.'))
        db.commit()
        queue_tasks(db, ['parallel-0', 'parallel-1'], provider)
    barrier = threading.Barrier(3)
    def analyze(*args, **kwargs):
        barrier.wait(timeout=2)
        raise ProviderError('fixture stop after concurrent claim')
    monkeypatch.setattr('app.services.intelligence.analyze_full_paper', analyze)
    with ThreadPoolExecutor(2) as pool:
        tasks = [pool.submit(worker.process_next, provider, wait=True) for _ in range(2)]
        try:
            barrier.wait(timeout=2)
        finally:
            barrier.abort()
        for task in tasks:
            assert task.result(3)
    with worker.database.sessions() as db:
        rows = db.scalars(select(IntelligenceTask).where(IntelligenceTask.paper_id.like('parallel-%'))).all()
        assert len(rows) == 2 and all(row.status == 'failed' for row in rows)


def test_transient_analysis_failure_returns_to_queue_with_backoff(client, monkeypatch):
    from app.services.intelligence import queue_tasks
    from test_intelligence_jobs import FailingProvider
    worker = client.app.state.intelligence_worker
    worker.stop()
    provider = FailingProvider()
    with worker.database.sessions() as db:
        db.add(Paper(id='retry-analysis', title='Retry analysis'))
        db.flush()
        db.add(PaperChunk(id='retry-source', paper_id='retry-analysis', page=1,
            content='The method stores earlier observations.'))
        db.commit()
        task_id = queue_tasks(db, ['retry-analysis'], provider)[0].id
    def limited(*args, **kwargs):
        raise ProviderError('limited', 429, code='rate_limit', retryable=True, retry_after=30)
    monkeypatch.setattr('app.services.intelligence.analyze_full_paper', limited)
    assert worker.process_next(provider)
    with worker.database.sessions() as db:
        task = db.get(IntelligenceTask, task_id)
        assert task.status == 'queued' and task.phase == 'awaiting_quota'
        import json
        assert json.loads(task.report_json)['workflow']['retry_after'] > time.time()
    assert not worker.process_next(provider)


def test_pool_runs_bounded_work_and_survives_a_failed_tick():
    from app.services.worker_pool import WorkerPool
    lock, entered, release = threading.Lock(), threading.Event(), threading.Event()
    active, high, calls = 0, 0, 0
    def tick():
        nonlocal active, high, calls
        with lock:
            calls += 1
            if calls == 1:
                raise RuntimeError('fixture failure')
            active += 1
            high = max(high, active)
            if active == 2:
                entered.set()
        try:
            assert release.wait(3)
        finally:
            with lock:
                active -= 1
        return False
    pool = WorkerPool('test-pool', tick, lambda: 2, maximum=4)
    pool.start()
    try:
        assert entered.wait(2)
    finally:
        release.set()
        pool.stop()
    assert high == 2 and calls >= 3
    assert not any(thread.is_alive() for thread in pool.threads)


def test_pool_does_not_silently_restart_while_old_request_is_draining():
    from app.services.worker_pool import WorkerPool
    entered, release = threading.Event(), threading.Event()
    def tick():
        entered.set()
        release.wait(3)
        return False
    pool = WorkerPool('draining', tick, lambda: 1, maximum=1)
    pool.start()
    assert entered.wait(1)
    pool.stop(timeout=.01)
    try:
        with pytest.raises(RuntimeError, match='draining'):
            pool.start()
    finally:
        release.set()
        pool.stop()
    pool.start()
    pool.stop()


def test_unexpected_provider_failure_cannot_strand_a_running_paragraph(queue):
    _, worker, provider, _, _ = queue
    enqueue(queue)
    provider.during = lambda: (_ for _ in ()).throw(RuntimeError('private model details'))
    worker.process_translation()
    assert all(item['status'] != 'running' for item in latest(queue)['items'])
    assert worker._translation_claims == {}
    assert 'private model details' not in str(latest(queue))


def test_direct_translation_revalidates_after_waiting_for_review(queue, monkeypatch):
    from app.services import translations
    client, worker, provider, _, paragraphs = queue
    waiting = threading.Event()
    original = translations.source_lock
    lock = original(worker.database.url, 'queue-paper', '')
    class ObservedLock:
        def translation(self, source):
            from contextlib import contextmanager
            @contextmanager
            def access():
                waiting.set()
                with lock.translation(source):
                    yield
            return access()
    monkeypatch.setattr(translations, 'source_lock', lambda *args: ObservedLock())
    with ThreadPoolExecutor(1) as pool:
        with lock:
            pending = pool.submit(client.post, '/api/papers/queue-paper/translate',
                json={'paragraph_id': paragraphs[0]['id']})
            assert waiting.wait(1)
            with worker.database.sessions() as db:
                db.get(PaperChunk, 'q0').content += ' Updated source structure.'
                db.commit()
        response = pending.result(2)
    assert response.status_code == 409
    assert provider.calls == []


def test_parallel_analysis_publication_keeps_each_papers_evidence_and_intake(client, monkeypatch):
    from types import SimpleNamespace
    from app.models import KnowledgeCandidate
    from app.providers.base import AnalysisResult, CardEntry, VerifiedCitation, KnowledgeCandidateEntry
    from app.services.intelligence import queue_tasks
    from test_intelligence_jobs import FailingProvider
    worker = client.app.state.intelligence_worker
    worker.stop()
    provider = FailingProvider()
    with worker.database.sessions() as db:
        for i in range(2):
            db.add(Paper(id=f'publish-{i}', title=f'Publish {i}'))
            db.flush()
            db.add(PaperChunk(id=f'publish-source-{i}', paper_id=f'publish-{i}', page=1,
                section='Method', content='The memory method stores observations for future decisions.'))
        db.commit()
        queue_tasks(db, ['publish-0', 'publish-1'], provider)
    barrier = threading.Barrier(2)
    def analyze(database, model, chunks, **kwargs):
        source = chunks[0]
        citation = VerifiedCitation(source, source.content, 'Memory stores observations.', 'method')
        analysis = AnalysisResult(method='Memory stores observations.', citations=[citation],
            card={'method': CardEntry('Memory stores observations.', [citation])},
            knowledge_candidates=[KnowledgeCandidateEntry('method', 'Memory', 'memory', [],
                'Stores observations.', 'proposed', .95, [citation])], prompt_version='parallel-fixture')
        barrier.wait(3)
        return SimpleNamespace(analysis=analysis, report={'partial': False})
    monkeypatch.setattr('app.services.intelligence.analyze_full_paper', analyze)
    with ThreadPoolExecutor(2) as pool:
        tasks = [pool.submit(worker.process_next, provider, wait=True) for _ in range(2)]
        assert all(task.result(5) for task in tasks)
    with worker.database.sessions() as db:
        for i in range(2):
            paper = db.get(Paper, f'publish-{i}')
            assert paper.intelligence_status == 'completed'
            assert paper.analysis_status == 'ready'
            assert len(paper.evidence) == 1
            assert paper.evidence[0].chunk_id == f'publish-source-{i}'
        assert len(db.scalars(select(KnowledgeCandidate).where(
            KnowledgeCandidate.paper_id.in_(['publish-0', 'publish-1']))).all()) == 2


def test_optional_research_checks_admission_before_loading_full_topic(client, monkeypatch):
    from app.models import Collection, ResearchScope, ResearchTask
    from app.research_schemas import ResearchSettings
    worker = client.app.state.research_worker
    worker.stop()
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0,
        investigations_enabled=False, maintenance_enabled=False))
    worker._next_scan = worker._next_reading_scan = time.time() + 60
    with worker.database.sessions() as db:
        db.add(Collection(id='blocked-topic', name='Blocked topic'))
        db.flush()
        db.add(ResearchScope(collection_id='blocked-topic', enabled=True))
        db.add(ResearchTask(id='blocked-research', collection_id='blocked-topic', fingerprint='fixture',
            status='queued', stage='draft', material_json='{}'))
        db.commit()
    monkeypatch.setattr(worker, '_eligible', lambda *args, **kwargs: False)
    def unnecessary(*args):
        raise AssertionError('Blocked optional research loaded the entire topic')
    monkeypatch.setattr(worker, '_current_material', unnecessary)
    assert worker.process_next(translations=False) is False
