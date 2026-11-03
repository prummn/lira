"""Persistent translation tasks use isolated stores and deterministic providers."""
import json
import threading
import time

import pytest
from sqlalchemy import select

from app.models import Paper, PaperChunk, Translation
from app.providers.base import ProviderError
from app.providers.priority import background_call, check_background
from app.research_schemas import ResearchSettings


class Translator:
    name, mode, model = 'CodexSubscriptionProvider', 'remote', 'fixture-model'
    translation_available = configured = True
    translation_configuration_version, translation_prompt_version = 'config-a', 'prompt-a'
    profile_id, response_model = 'selected', None
    profile_name,base_url = 'Selected fixture','https://fixture.invalid'
    last_usage = {}

    def __init__(self):
        self.calls = []
        self.fail = set()
        self.during = None

    def translate(self, chunk):
        self.calls.append(chunk.content)
        if self.during:
            self.during()
        if chunk.content in self.fail:
            raise ProviderError('这段翻译失败', code='translation_failed')
        check_background()
        return '译文：' + chunk.content


@pytest.fixture
def queue(client, monkeypatch):
    worker = client.app.state.research_worker
    worker.stop()
    provider = Translator()
    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: provider)
    monkeypatch.setattr(worker.profiles, 'provider', lambda _: provider)
    monkeypatch.setattr(worker.profiles, 'selected', lambda: provider)
    monkeypatch.setattr(worker.profiles, 'subscription_provider', lambda _: provider)
    monkeypatch.setattr(worker.profiles, 'public', lambda: {'profiles': [{'id': 'official', 'provider_kind': 'codex'}]})
    monkeypatch.setattr(worker.profiles.codex, 'status', lambda **kw: {'authenticated': True, 'limits': [
        {'name': 'primary', 'used_percent': 10, 'window_minutes': 300, 'resets_at': time.time()+300}]})
    with worker.database.sessions() as db:
        db.add(Paper(id='queue-paper', title='Queue research'))
        db.flush()
        db.add_all([PaperChunk(id=f'q{i}', paper_id='queue-paper', page=i+1, section=section, content=text)
            for i, (section, text) in enumerate([
                ('Method', 'The first method stores evidence in persistent memory.'),
                ('Results', 'The second result improves retrieval in the next experiment.'),
                ('References', 'Example author. Reference entry that must not be translated.')])])
        db.commit()
    path = '/api/papers/queue-paper/translation-jobs'
    paragraphs = client.get('/api/papers/queue-paper/reading-paragraphs').json()['paragraphs']
    return client, worker, provider, path, paragraphs


def enqueue(queue, ids=None, mode='selected', *, automatic=False):
    client, _, _, path, paragraphs = queue
    if automatic:
        from app.services.translation_queue import enqueue as queue_job
        import httpx
        with queue[1].database.sessions() as db:
            return httpx.Response(200, json=queue_job(queue[1], db, path.split('/')[3], mode, []))
    return client.post(path, json={'mode': mode, **({'paragraph_ids': ids or [p['id'] for p in paragraphs[:2]]} if mode == 'selected' else {})})


def latest(queue):
    return queue[0].get(queue[3]).json()['jobs'][0]


def test_enqueue_returns_before_network_and_each_completed_paragraph_is_readable(queue):
    _, worker, provider, _, _ = queue
    response = enqueue(queue)
    assert response.status_code == 200
    assert response.json()['status'] == 'queued'
    assert provider.calls == []
    assert worker.process_next()
    partial = latest(queue)
    assert partial['completed'] == 1 and partial['total'] == 2
    assert partial['items'][0]['translation']['text'].startswith('译文：')
    assert partial['items'][1]['status'] == 'queued'
    assert 'source_text' not in partial['items'][0]
    assert worker.process_next()
    assert latest(queue)['status'] == 'completed'


def test_deletion_during_translation_discards_result_without_worker_error(queue):
    from app.models import TranslationJob, TranslationItem
    from app.services.translation_queue import process_next
    client, worker, provider, _, _ = queue
    enqueue(queue)
    def delete_during_call():
        assert client.delete('/api/papers/queue-paper').status_code == 200
    provider.during = delete_during_call
    assert process_next(worker) == (True, True)
    assert worker._reason != 'service_error'
    with worker.database.sessions() as db:
        for model in (Paper, Translation, TranslationJob, TranslationItem):
            assert db.scalars(select(model)).all() == []
    assert not worker._translation_claims
    assert process_next(worker) == (False, False)


@pytest.mark.parametrize('phase', ['resolve', 'provider', 'record'])
def test_deleted_translation_job_is_deferred(queue, phase):
    from app.models import TranslationJob, TranslationItem
    from app.services.translation_queue import Deferred, _provider, _record, _resolve
    client, worker, _, _, _ = queue
    enqueue(queue)
    with worker.database.sessions() as db:
        job = db.scalars(select(TranslationJob)).one()
        item = db.scalars(select(TranslationItem)).first()
        job_id, item_id = job.id, item.id
    assert client.delete('/api/papers/queue-paper').status_code == 200
    with pytest.raises(Deferred) as caught:
        if phase == 'record':
            _record(worker, job_id, item_id, 'translating')
        elif phase == 'provider':
            _provider(worker, None)
        else:
            with worker.database.sessions() as db:
                _resolve(db, db.get(TranslationJob, job_id), db.get(TranslationItem, item_id))
    assert caught.value.reason == 'cancelled'


def test_global_monitor_keeps_completed_progress_without_sending_translation_content(queue):
    client, worker, _, _, _ = queue
    job = enqueue(queue).json()
    initial = client.get('/api/research/status').json()['translation_jobs'][0]
    assert initial['paper_title'] == 'Queue research'
    assert initial['id'] == job['id']
    assert initial['completed'] == 0 and initial['total'] == 2
    assert 'items' not in initial
    worker.process_next()
    partial = client.get('/api/research/status').json()['translation_jobs'][0]
    assert partial['completed'] == 1
    worker.process_next()
    completed = client.get('/api/research/status').json()['translation_jobs'][0]
    assert completed['id'] == job['id'] and completed['status'] == 'completed'
    assert completed['completed'] == completed['total'] == 2
    assert 'items' not in completed and 'source_text' not in completed


def test_active_jobs_and_existing_translation_cache_are_reused(queue):
    client, worker, provider, path, paragraphs = queue
    job = enqueue(queue).json()
    assert enqueue(queue).json()['id'] == job['id']
    worker.process_next()
    worker.process_next()
    again = enqueue(queue).json()
    assert again['completed'] == 2
    assert len(provider.calls) == 2
    cached = client.post('/api/papers/queue-paper/translate', json={'paragraph_id': paragraphs[0]['id']}).json()
    assert cached['cached'] is True
    assert cached['text'] == again['items'][0]['translation']['text']


def test_pause_resume_cancel_and_retry_only_failed_items(queue):
    client, worker, provider, _, _ = queue
    job = enqueue(queue).json()
    base = '/api/translation-jobs/' + job['id']
    assert client.post(base+'/pause').json()['status'] == 'paused'
    assert not worker.process_next()
    client.post(base+'/resume')
    worker.process_next()
    provider.fail.add('The second result improves retrieval in the next experiment.')
    worker.process_next()
    worker.process_next()
    failed = latest(queue)
    assert failed['status'] == 'failed' and failed['completed'] == 1 and failed['failed'] == 1
    provider.fail.clear()
    assert client.post(base+'/retry').json()['completed'] == 1
    worker.process_next()
    assert latest(queue)['status'] == 'completed'
    assert provider.calls.count('The first method stores evidence in persistent memory.') == 1
    fresh = enqueue(queue).json()
    assert client.post('/api/translation-jobs/'+fresh['id']+'/cancel').status_code == 200


def test_selected_runs_while_reading_and_disabled_but_foreground_preempts(queue):
    _, worker, provider, _, _ = queue
    worker.profiles.priority.presence('reader', True)
    enqueue(queue)
    assert worker.process_next()
    provider.during = worker.profiles.priority.foreground
    assert worker.process_next()
    assert latest(queue)['items'][1]['status'] == 'completed'
    provider.during = None
    worker.process_next()
    assert latest(queue)['status'] == 'completed'


def test_reading_presence_does_not_cancel_selected_context():
    from app.providers.priority import ResearchPriority
    priority = ResearchPriority()
    with background_call(priority, yield_to_reading=False):
        priority.presence('reader', True)
        check_background()
        priority.foreground()
        with pytest.raises(ProviderError):
            check_background()


def test_full_excludes_references_and_continues_during_reading_heartbeats(queue):
    _, worker, provider, _, _ = queue
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=180))
    full = enqueue(queue, mode='full')
    assert full.status_code == 200
    assert full.json()['total'] == 2
    worker.profiles.priority.presence('reader', True)
    provider.during = lambda: worker.profiles.priority.presence('reader', True)
    assert worker.process_next()
    assert len(provider.calls) == 1
    assert latest(queue)['completed'] == 1
    assert worker.process_next()
    assert latest(queue)['status'] == 'completed'


def test_full_scope_stops_before_appendix_or_references_but_selected_can_translate_them(queue):
    queue[1].settings(ResearchSettings(profile_id='official'))
    with queue[1].database.sessions() as db:
        paper = db.get(Paper, 'queue-paper')
        # Put the appendix before references, and use actual prose-sized
        # chunks: short strings are intentionally excluded by the reader.
        db.get(PaperChunk, 'q2').section = 'A Appendix'
        db.add_all([
            PaperChunk(id='q3', paper_id=paper.id, page=4, section='A.1 Implementation', content='The appendix describes additional implementation details for reproducibility.'),
            PaperChunk(id='q4', paper_id=paper.id, page=6, section='7 References', content='Example author. A reference entry that should only be translated on request.'),
        ])
        db.commit()
    paragraphs = queue[0].get('/api/papers/queue-paper/reading-paragraphs').json()['paragraphs']
    full = enqueue(queue, mode='full').json()
    assert full['total'] == full['scope_total'] == 2
    assert full['scope_skipped'] == 3
    assert full['scope_reason'] == 'appendix_or_references'
    assert {item['paragraph_id'] for item in full['items']} == {p['id'] for p in paragraphs[:2]}
    summary = queue[0].get('/api/research/status').json()['translation_jobs'][0]
    assert (summary['scope_total'], summary['scope_skipped'], summary['scope_reason']) == (2, 3, 'appendix_or_references')

    selected = [p['id'] for p in paragraphs[2:]]
    response = queue[0].post('/api/papers/queue-paper/translation-jobs', json={
        'mode': 'selected', 'paragraph_ids': selected,
    })
    assert response.status_code == 200
    assert response.json()['total'] == 3
    assert response.json()['scope_skipped'] == 0
    assert response.json()['scope_reason'] is None


def test_full_scope_uses_appendix_heading_even_when_reader_filters_it_out(queue):
    queue[1].settings(ResearchSettings(profile_id='official'))
    with queue[1].database.sessions() as db:
        heading = db.get(PaperChunk, 'q2')
        heading.section = heading.content = 'Appendix'
        db.add(PaperChunk(id='q3', paper_id='queue-paper', page=4, section='A.1 Implementation',
                         content='Additional details explain the implementation and experimental configuration.'))
        db.commit()
    paragraphs = queue[0].get('/api/papers/queue-paper/reading-paragraphs').json()['paragraphs']
    assert [p['section'] for p in paragraphs] == ['Method', 'Results', 'A.1 Implementation']
    full = enqueue(queue, mode='full').json()
    assert full['total'] == full['scope_total'] == 2
    assert full['scope_skipped'] == 1


@pytest.mark.parametrize('heading', [
    'Appendix', 'Appendices', 'APPENDIX A Additional Details', 'A Appendix', 'A. Appendix',
    '7 References', '7. REFERENCES', 'Bibliography', 'Supplementary Material',
    'Supplementary Information', '附录', '参考文献',
])
def test_full_scope_heading_variants(heading):
    from app.services.translation_queue import full_translation_scope
    body = {'id': 'body', 'section': 'Introduction', 'source_text': 'We refer to Appendix A and References below.'}
    tail = {'id': 'tail', 'section': heading}
    later = {'id': 'later', 'section': 'Details'}
    eligible, skipped, reason = full_translation_scope([body, tail, later])
    assert eligible == [body]
    assert skipped == [tail, later]
    assert reason == 'appendix_or_references'


def test_full_scope_recognizes_numbered_multilingual_cutoffs_without_matching_inline_text():
    from app.services.translation_queue import full_translation_scope

    paragraphs = [
        {'id': 'p1', 'kind': 'prose', 'section': '3 Experiments'},
        {'id': 'p2', 'kind': 'prose', 'section': 'A Appendix'},
        {'id': 'p3', 'kind': 'prose', 'section': '参考文献'},
    ]
    eligible, skipped, reason = full_translation_scope(paragraphs)
    assert [item['id'] for item in eligible] == ['p1']
    assert [item['id'] for item in skipped] == ['p2', 'p3']
    assert reason == 'appendix_or_references'

    no_cutoff, skipped, reason = full_translation_scope([
        {'id': 'p1', 'kind': 'prose', 'section': 'Introduction'},
        {'id': 'p2', 'kind': 'prose', 'section': 'Discussion'},
    ])
    assert [item['id'] for item in no_cutoff] == ['p1', 'p2']
    assert skipped == [] and reason is None


def test_full_scope_keeps_all_paragraphs_when_no_boundary_is_identified(queue):
    queue[1].settings(ResearchSettings(profile_id='official'))
    with queue[1].database.sessions() as db:
        db.get(PaperChunk, 'q2').section = None
        db.commit()
    full = enqueue(queue, mode='full').json()
    assert full['total'] == full['scope_total'] == 3
    assert full['scope_skipped'] == 0 and full['scope_reason'] is None


def test_requested_full_translation_runs_while_reader_is_present(queue):
    _, worker, provider, _, _ = queue
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=180))
    enqueue(queue, mode='full')
    worker.profiles.priority.presence('reader', True)
    with worker.profiles.priority.foreground_work():
        assert worker.process_next()
        assert len(provider.calls) == 1
    assert latest(queue)['completed'] == 1


def test_automatic_pretranslation_can_use_spare_capacity_during_foreground_work(queue):
    _, worker, provider, _, _ = queue
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0))
    enqueue(queue, mode='full', automatic=True)
    with worker.profiles.priority.foreground_work():
        assert worker.process_translation()
        assert len(provider.calls) == 1
    assert latest(queue)['completed'] == 1


def test_requested_full_translation_finishes_current_paragraph_during_reading(queue):
    _, worker, provider, _, _ = queue
    worker.settings(ResearchSettings(enabled=True,profile_id="official",idle_seconds=180))
    enqueue(queue,mode="full")
    worker.profiles.priority.presence("reader",True)
    provider.during = worker.profiles.priority.foreground
    assert worker.process_next()
    assert latest(queue)["completed"] == 1 and latest(queue)["failed"] == 0
    provider.during = None
    assert worker.process_next()
    assert latest(queue)["completed"] == 2


def test_requested_queue_paragraph_preempts_other_translation_then_restores_it(queue):
    client, worker, provider, path, paragraphs = queue
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0))
    enqueue(queue, mode='full')
    def request_second():
        provider.during = None
        response = client.post(path+'/prioritize', json={'paragraph_id': paragraphs[1]['id']})
        assert response.status_code == 200
    provider.during = request_second
    worker.process_next()
    interrupted = latest(queue)
    assert interrupted['completed'] == 1 and interrupted['failed'] == 0
    assert worker.process_next()
    assert latest(queue)['items'][1]['status'] == 'completed'
    assert latest(queue)['status'] == 'completed'
    assert provider.calls == [paragraphs[0]['source_text'], paragraphs[1]['source_text']]


def test_selecting_the_inflight_paragraph_does_not_restart_its_generation(queue):
    client, worker, provider, path, paragraphs = queue
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0))
    enqueue(queue, mode='full')
    provider.during = lambda: client.post(path+'/prioritize', json={'paragraph_id': paragraphs[0]['id']})
    assert worker.process_next()
    assert latest(queue)['completed'] == 1
    assert len(provider.calls) == 1


@pytest.mark.parametrize("state", ["completed", "paused"])
def test_selecting_saved_or_paused_translation_does_not_interrupt_other_work(queue,state):
    client, worker, _, path, paragraphs = queue
    job = enqueue(queue).json()
    worker.process_next()
    if state == "paused":
        client.post("/api/translation-jobs/"+job["id"]+"/pause")
    with background_call(worker.profiles.priority):
        response = client.post(path+"/prioritize",json={"paragraph_id":paragraphs[0 if state == "completed" else 1]["id"]})
        assert response.status_code == 200
        check_background()


def test_priority_change_during_quota_check_is_observed_before_generation(queue,monkeypatch):
    client,worker,provider,path,paragraphs = queue
    worker.settings(ResearchSettings(enabled=True,profile_id="official",idle_seconds=0))
    enqueue(queue,mode="full")
    original = worker.profiles.codex.status
    def quota(**kwargs):
        monkeypatch.setattr(worker.profiles.codex,"status",original)
        client.post(path+"/prioritize",json={"paragraph_id":paragraphs[1]["id"]})
        return original(**kwargs)
    monkeypatch.setattr(worker.profiles.codex,"status",quota)
    worker.process_next()
    assert provider.calls == []
    assert worker.process_next()
    assert provider.calls == [paragraphs[1]["source_text"]]


def test_prioritize_moves_an_existing_item_ahead(queue):
    client, worker, provider, path, paragraphs = queue
    job = enqueue(queue).json()
    raised = client.post(path+'/prioritize', json={'paragraph_id': paragraphs[1]['id']})
    assert raised.status_code == 200 and raised.json()['id'] == job['id']
    worker.process_next()
    assert provider.calls == [paragraphs[1]['source_text']]


def test_source_or_configuration_changed_during_call_cannot_publish(queue):
    _, worker, provider, _, _ = queue
    enqueue(queue)
    def edit():
        with worker.database.sessions() as db:
            db.get(PaperChunk, 'q0').content += ' Corrected source.'
            db.commit()
    provider.during = edit
    worker.process_next()
    item = latest(queue)['items'][0]
    assert item['status'] == 'failed' and item['error']
    with worker.database.sessions() as db:
        assert db.scalar(select(Translation)) is None


def test_pause_during_return_saves_cache_but_preserves_pause(queue):
    client, worker, provider, _, _ = queue
    job = enqueue(queue).json()
    provider.during = lambda: client.post('/api/translation-jobs/'+job['id']+'/pause')
    worker.process_next()
    assert latest(queue)['status'] == 'paused'
    with worker.database.sessions() as db:
        assert db.scalar(select(Translation)) is not None


def test_full_unknown_quota_has_no_paid_fallback_and_shared_hourly_ledger(queue, monkeypatch):
    _, worker, provider, _, _ = queue
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0, calls_per_hour=1))
    enqueue(queue, mode='full', automatic=True)
    monkeypatch.setattr(worker.profiles.codex, 'status', lambda **kw: {'authenticated': True, 'limits': []})
    assert not worker.process_next()
    assert latest(queue)['reason'] == 'quota_unknown' and provider.calls == []
    monkeypatch.setattr(worker.profiles.codex, 'status', lambda **kw: {'authenticated': True, 'limits': [
        {'name': 'primary', 'used_percent': 10, 'window_minutes': 300, 'resets_at': time.time()+300}]})
    worker._retry_at = 0
    assert worker.process_next()
    assert worker._remaining_calls(worker.settings()) == 0
    assert not worker.process_next()
    assert latest(queue)['reason'] == 'hourly_budget'


def boundary_queue(queue, monkeypatch):
    from test_reading_boundary_review import seed_fragments
    client, worker, provider, _, _ = queue
    reading_path = seed_fragments(client)
    provider.review_calls = []
    def complete_json(system,payload,**kw):
        provider.review_calls.append(payload)
        return {'decisions':[{'boundary_id':b['boundary_id'],'same_paragraph':True,'confidence':.99,'reason':'Continuation.'}
            for b in payload['boundaries']]}
    provider.complete_json = complete_json
    path = '/api/papers/boundary-paper/translation-jobs'
    paragraphs = client.get(reading_path).json()['paragraphs']
    return client,worker,provider,path,paragraphs


def test_boundary_merge_redirects_adjacent_items_and_translates_only_once(queue,monkeypatch):
    q = boundary_queue(queue,monkeypatch)
    client,worker,provider,path,paragraphs = q
    selected = [p['id'] for p in paragraphs if p['kind'] == 'prose']
    job = enqueue(q,selected).json()
    assert worker.process_next()
    result = client.get(path).json()['jobs'][0]
    assert result['status'] == 'completed' and result['completed'] == 2
    assert len(provider.calls) == 1 and len(provider.review_calls) == 1
    assert result['items'][0]['paragraph_id'] == result['items'][1]['paragraph_id']
    assert result['items'][0]['translation'] == result['items'][1]['translation']
    assert set(selected) <= set(result['items'][0]['aliases']) | set(result['items'][1]['aliases'])
    assert 'Figure 1' not in provider.calls[0]


def test_boundary_check_consumes_budget_before_translation_and_checkpoints_merge(queue,monkeypatch):
    q = boundary_queue(queue,monkeypatch)
    client,worker,provider,path,_ = q
    worker.settings(ResearchSettings(enabled=True,profile_id='official',idle_seconds=0,calls_per_hour=1))
    enqueue(q,mode='full',automatic=True)
    worker.process_next()
    result = client.get(path).json()['jobs'][0]
    assert result['reason'] == 'hourly_budget'
    assert provider.calls == [] and len(provider.review_calls) == 1
    assert worker._remaining_calls(worker.settings()) == 0
    assert client.get('/api/papers/boundary-paper/reading-paragraphs').json()['paragraphs'][0]['review_needed'] is False


def test_failed_boundary_review_never_translates_fragments(queue,monkeypatch):
    q = boundary_queue(queue,monkeypatch)
    client,worker,provider,path,paragraphs = q
    provider.complete_json = lambda *a,**kw: {'decisions':[]}
    enqueue(q,[paragraphs[0]['id']])
    worker.process_next()
    worker.process_next()
    assert client.get(path).json()['jobs'][0]['status'] == 'failed'
    assert provider.calls == []


def test_configuration_change_midcall_does_not_save_under_new_identity(queue):
    _,worker,provider,_,_ = queue
    enqueue(queue)
    provider.during = lambda: setattr(provider,'translation_configuration_version','config-b')
    worker.process_next()
    assert latest(queue)['items'][0]['status'] == 'failed'
    with worker.database.sessions() as db:
        assert db.scalar(select(Translation)) is None


def test_restart_recovers_running_item_without_retranslating_completed(queue,monkeypatch):
    from app.models import TranslationItem,TranslationJob
    from app.services.background_research import BackgroundResearchWorker
    _,worker,provider,_,_ = queue
    job = enqueue(queue).json()
    worker.process_next()
    with worker.database.sessions() as db:
        row = db.get(TranslationJob,job['id'])
        row.status = 'running'
        row.items[1].status,row.items[1].phase = 'running','translating'
        db.commit()
    restarted = BackgroundResearchWorker(worker.database,worker.profiles)
    monkeypatch.setattr(restarted._research_pool,'start',lambda:None)
    monkeypatch.setattr(restarted._translation_pool,'start',lambda:None)
    restarted.start()
    restarted.stop()
    assert restarted.process_next()
    assert latest(queue)['status'] == 'completed' and len(provider.calls) == 2


def test_cancel_midcall_preserves_cache_without_resuming_job(queue):
    client,worker,provider,_,_ = queue
    job = enqueue(queue).json()
    provider.during = lambda: client.post('/api/translation-jobs/'+job['id']+'/cancel')
    worker.process_next()
    result = latest(queue)
    assert result['status'] == 'cancelled'
    assert result['completed'] == 0
    assert all(i['status'] == 'cancelled' for i in result['items'])
    with worker.database.sessions() as db:
        assert db.scalar(select(Translation)) is not None
    assert not worker.process_next()


def test_no_database_connection_held_during_translation(queue):
    _,worker,provider,_,_ = queue
    enqueue(queue)
    def assert_closed():
        assert worker.database.engine.pool.checkedout() == 0
    provider.during = assert_closed
    assert worker.process_next()


def test_requested_full_uses_selected_api_without_requiring_official_profile(queue,monkeypatch):
    _,worker,provider,_,_ = queue
    monkeypatch.setattr(worker.profiles,'public',lambda:{'profiles':[{'id':'paid','provider_kind':'openai'}]})
    worker.settings(ResearchSettings(enabled=True,profile_id='paid',idle_seconds=0))
    assert enqueue(queue,mode='full').status_code == 200
    assert provider.calls == []


def test_lowering_weekly_reserve_resumes_existing_pretranslation_without_reenqueue(queue, monkeypatch):
    client, worker, provider, _, _ = queue
    monkeypatch.setattr(worker.profiles.codex, 'status', lambda **kw: {'authenticated': True, 'limits': [
        {'name': 'primary', 'used_percent': 0, 'window_minutes': 300, 'resets_at': time.time()+300},
        {'name': 'secondary', 'used_percent': 77, 'window_minutes': 10080, 'resets_at': time.time()+86400}]})
    job = enqueue(queue, mode='full').json()
    assert not worker.process_next()
    assert latest(queue)['reason'] == 'quota_reserve' and provider.calls == []
    response = client.patch('/api/research/quota-policy', json={'long_reserve': 10})
    assert response.status_code == 200
    assert worker.process_next()
    resumed = latest(queue)
    assert resumed['id'] == job['id'] and resumed['completed'] == 1
    assert len(provider.calls) == 1


def test_full_disabled_is_durable_and_returns_waiting_reason(queue):
    _,worker,provider,_,_ = queue
    worker.settings(ResearchSettings(enabled=False,profile_id='official',idle_seconds=0))
    result = enqueue(queue,mode='full')
    assert result.status_code == 200
    assert worker.process_next() and len(provider.calls) == 1


def test_full_prioritized_item_runs_explicitly_even_when_reading_and_disabled(queue):
    client,worker,provider,path,paragraphs = queue
    worker.settings(ResearchSettings(enabled=False,profile_id='official',idle_seconds=0))
    enqueue(queue,mode='full',automatic=True)
    worker.profiles.priority.presence('reader',True)
    client.post(path+'/prioritize',json={'paragraph_id':paragraphs[1]['id']})
    assert worker.process_next()
    assert provider.calls == [paragraphs[1]['source_text']]
    assert not worker.process_next()


def test_direct_request_and_preempted_queue_never_generate_same_source_concurrently(queue):
    client,worker,provider,_,paragraphs = queue
    enqueue(queue,[paragraphs[0]['id']])
    entered,release = threading.Event(),threading.Event()
    def block():
        entered.set()
        assert release.wait(5)
    provider.during = block
    work = threading.Thread(target=worker.process_next)
    work.start()
    assert entered.wait(5)
    outputs=[]
    direct = threading.Thread(target=lambda:outputs.append(client.post('/api/papers/queue-paper/translate',
        json={'paragraph_id':paragraphs[0]['id']})))
    direct.start()
    release.set()
    work.join(8)
    direct.join(8)
    assert 1 <= len(provider.calls) <= 2
    assert outputs[0].status_code == 200
    provider.during = None
    worker.process_next()
    assert latest(queue)['status'] == 'completed'
    assert len(provider.calls) <= 2


def test_overlapping_selected_requests_extend_one_active_job(queue):
    _,_,_,_,paragraphs = queue
    first = enqueue(queue,[paragraphs[0]['id']]).json()
    second = enqueue(queue,[paragraphs[0]['id'],paragraphs[1]['id']]).json()
    assert second['id'] == first['id'] and second['total'] == 2


def test_cached_translation_remains_readable_after_active_profile_changes(queue):
    client,worker,provider,_,paragraphs = queue
    enqueue(queue,[paragraphs[0]['id']])
    worker.process_next()
    provider.translation_configuration_version = 'another-active-config'
    result = client.get('/api/papers/queue-paper/reading-paragraphs').json()
    assert result['translations'][paragraphs[0]['id']]['text'].startswith('译文：')


def test_stale_full_profile_does_not_starve_a_new_full_job(queue):
    _,worker,provider,_,_ = queue
    worker.settings(ResearchSettings(enabled=True,profile_id='official',idle_seconds=0))
    first = enqueue(queue,mode='full',automatic=True).json()
    worker.settings(ResearchSettings(enabled=True,profile_id='other-official',idle_seconds=0))
    worker.profiles.public = lambda:{'profiles':[{'id':'other-official','provider_kind':'codex'}]}
    provider.translation_configuration_version = 'config-other'
    second = enqueue(queue,mode='full',automatic=True).json()
    assert second['id'] != first['id']
    assert worker.process_next() and len(provider.calls) == 1


def test_selected_then_full_links_the_same_persistent_paragraph_work(queue):
    from app.models import TranslationJob
    _,worker,provider,_,paragraphs = queue
    first = enqueue(queue,[paragraphs[0]['id']]).json()
    worker.settings(ResearchSettings(enabled=True,profile_id='official',idle_seconds=0))
    second = enqueue(queue,mode='full').json()
    with worker.database.sessions() as db:
        a,b = db.get(TranslationJob,first['id']),db.get(TranslationJob,second['id'])
        assert b.items[0].work_item_id == a.items[0].id
    worker.process_next()
    jobs = queue[0].get(queue[3]).json()['jobs']
    assert all(j['items'][0]['status'] == 'completed' for j in jobs)
    assert len(provider.calls) == 1


def test_three_overlapping_jobs_share_work_and_owner_cancel_preserves_other_authorization(queue):
    from app.models import TranslationJob
    client,worker,provider,_,paragraphs = queue
    a = enqueue(queue,[paragraphs[0]['id']]).json()
    b = enqueue(queue,[paragraphs[1]['id']]).json()
    joined = enqueue(queue,[paragraphs[0]['id'],paragraphs[1]['id']]).json()
    with worker.database.sessions() as db:
        rows = [i for j in db.scalars(select(TranslationJob)) for i in j.items]
        root_ids = {i.work_item_id or i.id for i in rows}
        assert len(root_ids) == 2
    client.post('/api/translation-jobs/'+a['id']+'/cancel')
    worker.process_next()
    worker.process_next()
    assert len(provider.calls) == 2
    jobs = {j['id']:j for j in client.get(queue[3]).json()['jobs']}
    assert jobs[a['id']]['status'] == 'cancelled'
    assert jobs[joined['id']]['status'] == 'completed'


def test_paused_shared_selected_work_can_be_fulfilled_by_full_without_resuming_pause(queue):
    client,worker,provider,_,paragraphs = queue
    selected = enqueue(queue,[paragraphs[0]['id']]).json()
    client.post('/api/translation-jobs/'+selected['id']+'/pause')
    worker.settings(ResearchSettings(enabled=True,profile_id='official',idle_seconds=0))
    full = enqueue(queue,mode='full').json()
    assert worker.process_next()
    jobs = {j['id']:j for j in client.get(queue[3]).json()['jobs']}
    assert jobs[selected['id']]['status'] == 'paused'
    assert jobs[full['id']]['completed'] == 1
    assert len(provider.calls) == 1


def test_source_lock_normalizes_url_encoding_and_windows_case():
    from app.services.translations import source_lock
    assert source_lock('sqlite:///D%3A/papers.db','p','fragment') is source_lock('sqlite:///d:/papers.db','p','merged fragment')


def test_resume_fully_cached_paused_job_finishes_immediately(queue):
    client,worker,provider,_,paragraphs = queue
    job = enqueue(queue,[paragraphs[0]['id']]).json()
    provider.during = lambda:client.post('/api/translation-jobs/'+job['id']+'/pause')
    worker.process_next()
    resumed = client.post('/api/translation-jobs/'+job['id']+'/resume').json()
    assert resumed['status'] == 'completed' and resumed['completed'] == 1


@pytest.mark.parametrize("reading", [False, True])
def test_full_yields_to_research_only_when_research_can_run(queue,monkeypatch,reading):
    from app.models import Collection,ResearchScope,ResearchTask
    _,worker,provider,_,_ = queue
    with worker.database.sessions() as db:
        db.add(Collection(id='fair-topic',name='Fair background work'))
        db.flush()
        db.add(ResearchScope(collection_id='fair-topic',enabled=True))
        db.add(ResearchTask(id='fair-research',collection_id='fair-topic',fingerprint='fair',status='queued',stage='draft',material_json='{}'))
        db.commit()
    worker.settings(ResearchSettings(enabled=True,profile_id='official',idle_seconds=0))
    enqueue(queue,mode='full',automatic=True)
    if reading:
        worker.profiles.priority.presence("reader",True)
    calls=[]
    monkeypatch.setattr(worker,'_current_material',lambda *a:True)
    monkeypatch.setattr(worker,'_step',lambda *a:calls.append('research'))
    assert worker.process_next()
    assert worker.process_next()
    assert calls == ([] if reading else ['research'])
    assert len(provider.calls) == (2 if reading else 1)


@pytest.mark.parametrize('code',['rate_limit','local_capacity','upstream_error'])
def test_transient_failure_persists_backoff_without_blocking_other_selected_work(queue,monkeypatch,code):
    from app.models import TranslationJob
    client,worker,provider,path,paragraphs = queue
    first = enqueue(queue,[paragraphs[0]['id']]).json()
    second = enqueue(queue,[paragraphs[1]['id']]).json()
    client.post(path+'/prioritize',json={'paragraph_id':paragraphs[0]['id']})
    clock = [time.time()]
    monkeypatch.setattr('app.services.translation_queue.time.time',lambda:clock[0])
    original = provider.translate
    def flaky(chunk):
        if chunk.content == paragraphs[0]['source_text']:
            provider.calls.append(chunk.content)
            raise ProviderError('连接稍后恢复',503,code=code,retryable=True,retry_after=120)
        return original(chunk)
    provider.translate = flaky
    worker.process_next()
    with worker.database.sessions() as db:
        job = db.get(TranslationJob,first['id'])
        assert json.loads(job.usage_json)['next_retry_at'] >= clock[0]+120
        assert job.items[0].attempts == 0
    assert worker.process_next()
    assert provider.calls == [paragraphs[0]['source_text'],paragraphs[1]['source_text']]
    assert not worker.process_next()
    clock[0] += 121
    worker.process_next()
    assert provider.calls.count(paragraphs[0]['source_text']) == 2


def test_prioritize_uses_running_shared_authorization_before_newer_paused_job(queue):
    client,worker,provider,path,paragraphs = queue
    selected = enqueue(queue).json()
    worker.settings(ResearchSettings(enabled=True,profile_id='official',idle_seconds=0))
    full = enqueue(queue,mode='full').json()
    client.post('/api/translation-jobs/'+full['id']+'/pause')
    raised = client.post(path+'/prioritize',json={'paragraph_id':paragraphs[1]['id']}).json()
    assert raised['id'] == selected['id'] and raised['status'] != 'paused'
    worker.process_next()
    assert provider.calls == [paragraphs[1]['source_text']]


def test_direct_force_returns_new_text_when_same_cache_row_is_updated(queue):
    client,_,provider,_,paragraphs = queue
    path = '/api/papers/queue-paper/translate'
    first = client.post(path,json={'paragraph_id':paragraphs[0]['id']}).json()
    provider.translate = lambda chunk:'Updated forced translation.'
    forced = client.post(path,json={'paragraph_id':paragraphs[0]['id'],'force':True}).json()
    assert forced['id'] == first['id']
    assert forced['text'] == 'Updated forced translation.' and forced['cached'] is False


def test_invalid_translation_is_not_saved_by_direct_request(queue):
    client, _, provider, _, paragraphs = queue
    provider.translate = lambda chunk: '未提供待翻译的原文。'
    response = client.post('/api/papers/queue-paper/translate', json={'paragraph_id': paragraphs[0]['id']})
    assert response.status_code == 502
    assert '译文' in response.json()['detail']
    with client.app.state.database.sessions() as db:
        assert list(db.scalars(select(Translation))) == []


def test_invalid_forced_translation_preserves_previous_good_result(queue):
    client, _, provider, _, paragraphs = queue
    path = '/api/papers/queue-paper/translate'
    first = client.post(path, json={'paragraph_id': paragraphs[0]['id']}).json()
    provider.translate = lambda chunk: '未提供待翻译的原文。'
    failed = client.post(path, json={'paragraph_id': paragraphs[0]['id'], 'force': True})
    assert failed.status_code == 502
    cached = client.post(path, json={'paragraph_id': paragraphs[0]['id']}).json()
    assert cached['cached'] and cached['text'] == first['text']


def test_invalid_background_translation_is_failed_instead_of_completed(queue):
    client, worker, provider, _, paragraphs = queue
    provider.translate = lambda chunk: '未提供待翻译的原文。'
    enqueue(queue, [paragraphs[0]['id']])
    worker.process_next()
    worker.process_next()
    job = latest(queue)
    assert job['status'] == 'failed' and job['completed'] == 0
    assert 'translation' not in job['items'][0]
    assert job['items'][0]['error']
    with worker.database.sessions() as db:
        assert list(db.scalars(select(Translation))) == []


def test_historical_invalid_cache_is_not_shown_or_reused(queue):
    client, worker, provider, _, paragraphs = queue
    path = '/api/papers/queue-paper/translate'
    first = client.post(path, json={'paragraph_id': paragraphs[0]['id']}).json()
    with worker.database.sessions() as db:
        db.get(Translation, first['id']).text = '未提供待翻译的原文。'
        db.commit()
    reading = client.get('/api/papers/queue-paper/reading-paragraphs').json()
    assert paragraphs[0]['id'] not in reading['translations']
    assert reading['translation_errors'][paragraphs[0]['id']]
    provider.calls.clear()
    job = enqueue(queue, [paragraphs[0]['id']]).json()
    assert job['completed'] == 0
    worker.process_next()
    assert latest(queue)['completed'] == 1 and len(provider.calls) == 1


def test_historical_invalid_queue_output_cannot_resurrect_bad_translation(queue):
    client, worker, _, _, paragraphs = queue
    enqueue(queue, [paragraphs[0]['id']])
    worker.process_next()
    with worker.database.sessions() as db:
        db.scalar(select(Translation)).text = '未提供待翻译的原文。'
        db.commit()
    item = latest(queue)['items'][0]
    assert 'translation' not in item
    assert item['status'] == 'failed' and item['error']
    retried = client.post('/api/translation-jobs/' + latest(queue)['id'] + '/retry')
    assert retried.status_code == 200 and retried.json()['status'] == 'queued'
    worker.process_next()
    assert latest(queue)['completed'] == 1


def test_restart_marks_historical_invalid_queue_results_failed_in_global_monitor(queue):
    from app.services.translation_queue import recover
    client, worker, _, _, paragraphs = queue
    enqueue(queue, [paragraphs[0]['id']])
    worker.process_next()
    with worker.database.sessions() as db:
        db.scalar(select(Translation)).text = '未提供待翻译的原文。'
        db.commit()
        recover(db)
    job = client.get('/api/research/status').json()['translation_jobs'][0]
    assert job['status'] == 'failed' and job['completed'] == 0 and job['failed'] == 1


def test_full_reauthorization_binds_new_official_profile_even_with_identical_configuration(queue):
    from app.models import TranslationJob
    client,worker,provider,path,_ = queue
    worker.profiles.public = lambda:{'profiles':[
        {'id':'official-a','provider_kind':'codex'},{'id':'official-b','provider_kind':'codex'}]}
    worker.settings(ResearchSettings(enabled=True,profile_id='official-a',idle_seconds=0))
    old = enqueue(queue,mode='full',automatic=True).json()
    worker.settings(ResearchSettings(enabled=True,profile_id='official-b',idle_seconds=0))
    new = enqueue(queue,mode='full',automatic=True).json()
    assert new['id'] != old['id'] and new['status'] == 'queued'
    with worker.database.sessions() as db:
        a,b = db.get(TranslationJob,old['id']),db.get(TranslationJob,new['id'])
        assert b.profile_id == 'official-b' and a.profile_id == 'official-a'
        assert b.items[0].work_item_id == a.items[0].id
    assert worker.process_next() and len(provider.calls) == 1


def test_new_selected_authorization_runs_without_resuming_paused_full(queue):
    from app.models import TranslationJob
    client,worker,provider,path,paragraphs = queue
    provider.profile_id = 'official'
    worker.settings(ResearchSettings(enabled=True,profile_id='official',idle_seconds=0))
    full = enqueue(queue,mode='full').json()
    client.post('/api/translation-jobs/'+full['id']+'/pause')
    selected = enqueue(queue,[paragraphs[0]['id']]).json()
    assert selected['id'] != full['id'] and selected['status'] == 'queued' and selected['mode'] == 'selected'
    with worker.database.sessions() as db:
        a,b = db.get(TranslationJob,full['id']),db.get(TranslationJob,selected['id'])
        assert b.items[0].work_item_id == a.items[0].id
    worker.profiles.priority.presence('reader',True)
    assert worker.process_next() and len(provider.calls) == 1
    jobs = {j['id']:j for j in client.get(path).json()['jobs']}
    assert jobs[full['id']]['status'] == 'paused'
    assert jobs[full['id']]['items'][1]['status'] == 'queued'
    assert jobs[selected['id']]['status'] == 'completed'
