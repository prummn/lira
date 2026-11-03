import json
import time

import pytest
from sqlalchemy import select

from app.models import Collection, CollectionPaper, Paper, PaperChunk, Note, KnowledgeCandidate
from app.providers.base import ProviderError


@pytest.fixture
def research(client):
    from app.research_schemas import ResearchSettings, ScopeUpdate
    worker = client.app.state.research_worker
    worker.stop()
    with worker.database.sessions() as db:
        db.add_all([Collection(id='topic', name='Memory'), Collection(id='other', name='Other'),
                    Paper(id='p1', title='Memory mechanisms'), Paper(id='p2', title='Unrelated')])
        db.flush()
        db.add_all([CollectionPaper(collection_id='topic', paper_id='p1'),
                    PaperChunk(id='c1', paper_id='p1', page=1, section='Method',
                        content='The agent stores experience in external memory. Retrieval depends on relevance and recency.'),
                    PaperChunk(id='c2', paper_id='p2', page=1, content='Unrelated secret scope text.'),
                    Note(id='n1', paper_id='p1', content='Does retrieval become stale?', kind='question')])
        db.commit()
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0))
    worker.scope('topic', ScopeUpdate(enabled=True, focus='How does memory change decisions?'))
    worker.profiles.public = lambda: {'profiles': [{'id': 'official', 'provider_kind': 'codex'}]}
    worker.profiles.codex.status = lambda **kw: {'authenticated': True, 'limits': [
        dict(name='primary', used_percent=10, window_minutes=300, resets_at=time.time()+300)]}
    return client, worker


def essay():
    return {'title': '记忆如何改变决策', 'dek': '从可检索的经历出发，理解记忆的作用边界。',
            'markdown': ('## 记忆的工作位置\n\n外部记忆把经历带回决策现场。它的价值取决于何时检索以及检索到什么。[1](#source-S1)\n\n' * 12),
            'changes': '建立初版论证，并说明检索的适用边界。'}


def teaching():
    return {'reader_questions': ['How does a stored experience affect the next action?'],
            'explanations': [{'question': 'What happens after a memory is stored?',
                'steps': [{'text': 'Write the experience to external memory.', 'source_ids': ['S1']},
                          {'text': 'Select a relevant experience for the next decision.', 'source_ids': ['S1']}],
                'example': {'kind': 'illustrative', 'text': 'Imagine recalling a conversation before a meeting.',
                            'source_ids': ['S1']}}]}


class Writer:
    model = 'fixture-model'
    last_usage = {'input_tokens': 100, 'output_tokens': 50}
    def __init__(self):
        self.calls = []
        self.interrupt = False
        self.bad_quote = False
    def _complete(self, system, user, **kw):
        self.calls.append((system, user))
        if self.interrupt:
            raise ProviderError('yield', 409, code='background_preempted')
        if 'STAGE: SYNTHESIS' in system:
            return json.dumps({'title': '记忆如何改变决策', 'thesis': 'Memory depends on retrieval.',
                'outline': ['What is stored?', 'When is it used?'],
                'teaching': teaching(),
                'evidence': [{'source_id': 'S1', 'quote': 'Invented text' if self.bad_quote else 'The agent stores experience in external memory.',
                              'claim': 'The mechanism uses external experience.'}], 'questions': ['Does retrieval become stale?']})
        return json.dumps(essay(), ensure_ascii=False)


def test_collection_deleted_after_worker_selects_task(research, monkeypatch):
    client, worker = research
    worker.enqueue('topic')

    def delete_before_material_check(*args, **kwargs):
        assert client.delete('/api/collections/topic').status_code == 204
        return True

    monkeypatch.setattr(worker, '_eligible', delete_before_material_check)
    assert worker.process_next(translations=False) is False
    assert client.get('/api/collections/other').status_code == 200


def test_collection_deleted_during_generation_does_not_restore_task(research):
    from app.models import ResearchTask, ResearchRevision
    client, worker = research
    task = worker.enqueue('topic')

    class DeletingWriter(Writer):
        def _complete(self, *args, **kwargs):
            assert client.delete('/api/collections/topic').status_code == 204
            return super()._complete(*args, **kwargs)

    writer = DeletingWriter()
    worker.profiles.subscription_provider = lambda _: writer
    worker._step(task['id'], worker.settings())
    assert len(writer.calls) == 1
    with worker.database.sessions() as db:
        assert db.get(ResearchTask, task['id']) is None
        assert db.scalar(select(ResearchRevision.id)) is None
        assert db.get(Paper, 'p1') is not None


def test_queue_fingerprint_is_scoped_and_notes_trigger_finite_update(research):
    client, worker = research
    with worker.database.sessions() as db:
        db.get(Note, 'n1').kind = 'note'
        db.commit()
    a = worker.enqueue('topic')
    assert worker.enqueue('topic')['id'] == a['id']
    with worker.database.sessions() as db:
        from app.models import ResearchTask
        task = db.get(ResearchTask, a['id'])
        snapshot = json.loads(task.material_json)
        assert snapshot['papers'][0]['id'] == 'p1'
        assert 'Unrelated secret scope text' not in task.material_json
        assert 'Does retrieval become stale?' in task.material_json
        db.get(Note, 'n1').content = 'Compare retrieval with forgetting.'
        db.commit()
    b = worker.enqueue('topic')
    assert b['id'] != a['id']
    assert worker.enqueue('topic')['id'] == b['id']


def test_pipeline_persists_checkpoints_and_publishes_version_only_after_review(research):
    client, worker = research
    writer = Writer()
    worker.profiles.subscription_provider = lambda _: writer
    task = worker.enqueue('topic')
    assert worker.process_next()
    data = client.get('/api/research/collections/topic').json()
    assert data['revision'] is None
    assert data['task']['stage'] == 'draft'
    writer.interrupt = True
    worker.process_next()
    data = client.get('/api/research/collections/topic').json()
    assert data['task']['status'] == 'paused'
    assert data['task']['stage'] == 'draft'
    writer.interrupt = False
    worker.process_next()
    worker.process_next()
    data = client.get('/api/research/collections/topic').json()
    assert data['revision']['number'] == 1
    assert data['revision']['sources'][0]['quote'].startswith('The agent stores')
    assert data['task']['status'] == 'completed'
    assert len(writer.calls) == 4
    assert worker.enqueue('topic')['id'] == task['id']
    worker.process_next()
    assert len(writer.calls) == 4


def test_bad_quotes_never_publish_and_retries_are_bounded(research):
    _, worker = research
    writer = Writer()
    writer.bad_quote = True
    worker.profiles.subscription_provider = lambda _: writer
    worker.enqueue('topic')
    for _ in range(7):
        worker.process_next()
        worker._retry_at = 0
    data = worker.collection('topic')
    assert data['revision'] is None
    assert data['task']['status'] == 'failed'
    assert len(writer.calls) == 2


def test_material_change_during_generation_cannot_publish_old_essay(research):
    _, worker = research
    worker.profiles.subscription_provider = lambda _: Writer()
    worker.enqueue('topic')
    worker.process_next()
    worker.process_next()
    with worker.database.sessions() as db:
        db.get(PaperChunk, 'c1').content += ' The revised paper retracts the original result.'
        db.commit()
    worker.process_next()
    assert worker.collection('topic')['revision'] is None
    assert worker.collection('topic')['task']['status'] == 'superseded'


def test_unknown_quota_pauses_without_paid_fallback(research):
    _, worker = research
    writer = Writer()
    worker.profiles.subscription_provider = lambda _: writer
    worker.profiles.codex.status = lambda **kw: {'authenticated': True, 'limits': []}
    worker.enqueue('topic')
    worker.process_next()
    assert not writer.calls
    assert worker.status()['reason'] == 'quota_unknown'


@pytest.mark.parametrize('code,reason', [('transport_timeout', 'quota_timeout'),
    ('transport_error', 'quota_unavailable'), ('codex_account_error', 'quota_unavailable')])
def test_failed_quota_read_has_a_distinct_reason_and_refresh_recovers_without_cooldown(research, code, reason):
    _, worker = research
    worker.profiles.codex.status = lambda **kw: {'authenticated': True, 'limits': [],
        'limits_error_code': code, 'limits_retryable': True}
    assert not worker._eligible(worker.settings())
    status = worker.status()
    assert status['reason'] == reason
    assert status['quota_error_code'] == code
    refreshed = worker.refresh_quota()
    assert refreshed['available'] is True and refreshed['quota_error_code'] == code
    assert worker._retry_at > time.time()
    worker.profiles.codex.status = lambda **kw: {'authenticated': True, 'limits': [
        dict(name='primary', used_percent=10, window_minutes=300, resets_at=time.time()+300)]}
    refreshed = worker.refresh_quota()
    assert refreshed['quota_error_code'] is None
    assert worker._eligible(worker.settings())
    assert worker.status()['quota_error_code'] is None


@pytest.mark.parametrize('reason', ['quota_timeout', 'quota_unavailable'])
def test_maintenance_quota_failure_survives_outer_scheduler(research, monkeypatch, reason):
    _, worker = research
    worker.settings(worker.settings().model_copy(update={'maintenance_enabled': True}))
    worker._next_scan = worker._next_reading_scan = time.time()+600
    worker._quota_at = time.time()
    def maintenance(settings):
        worker._reason = reason
        return False
    monkeypatch.setattr(worker, '_process_maintenance', maintenance)
    assert not worker.process_next()
    assert worker.status()['reason'] == reason


def test_repeated_preparation_gates_allow_official_short_lived_status_cache(research, monkeypatch):
    _, worker = research
    requests = []
    def status(**kwargs):
        requests.append(kwargs)
        return {'authenticated': True, 'limits': [dict(name='primary', used_percent=10,
            window_minutes=300, resets_at=time.time()+300)]}
    monkeypatch.setattr(worker.profiles.codex, 'status', status)
    assert worker._eligible(worker.settings())
    assert worker._eligible(worker.settings())
    assert all(not request.get('refresh') for request in requests)
    worker.refresh_quota()
    assert requests[-1]['refresh'] is True


def test_recent_official_quota_survives_network_failure_but_expires_and_preserves_reserves(research):
    _, worker = research
    checked = time.time()-40
    state = {'authenticated': True, 'limits_checked_at': checked,
        'limits_attempted_at': time.time(), 'limits_error_code': 'transport_timeout',
        'limits': [dict(name='primary', used_percent=10, window_minutes=300, resets_at=time.time()+600)]}
    worker.profiles.codex.status = lambda **kwargs: state
    assert worker._eligible(worker.settings())
    assert worker.status()['quota_checked_at'] == checked
    assert worker.status()['quota_using_recent'] is True
    state['limits'][0]['used_percent'] = 80
    assert not worker._eligible(worker.settings())
    assert worker.status()['reason'] == 'quota_reserve'
    worker._retry_at = 0
    state['limits'][0]['used_percent'] = 10
    state['limits_checked_at'] = time.time()-121
    assert not worker._eligible(worker.settings())
    assert worker.status()['reason'] == 'quota_timeout'
    assert worker.status()['quota_using_recent'] is False
    assert worker.status()['quota_checked_at'] == state['limits_checked_at']


def test_presence_preempts_and_settings_validate_profile_and_thresholds(research):
    client, worker = research
    assert client.put('/api/research/settings', json={'start_remaining': 20, 'stop_remaining': 35}).status_code == 422
    assert client.put('/api/research/settings', json={'profile_id': 'missing'}).status_code == 422
    assert client.post('/api/research/presence', json={'client_id': 'tab-1', 'reading': True}).status_code == 200
    assert not worker.profiles.priority.idle(0)
    client.post('/api/research/presence', json={'client_id': 'tab-1', 'reading': False})
    assert worker.profiles.priority.idle(0)
    assert client.get('/api/research/collections/missing').status_code == 404


class MaintenanceWriter:
    mode = 'remote'
    configured = True
    model = 'maintenance-fixture'
    last_usage = {'input_tokens': 40, 'output_tokens': 12}

    def __init__(self):
        self.calls = []

    def audit_knowledge_bundle(self, bundle):
        self.calls.append(bundle)
        return {'summary': 'Checked the supplied paper', 'candidates': [], 'relations': [], 'reviews': []}


def test_maintenance_waits_for_reading_and_uses_shared_quota_gate(research):
    client, worker = research
    from app.models import KnowledgeMaintenanceRun
    from app.services.knowledge_maintenance import prepare_run
    from app.research_schemas import ResearchSettings
    with worker.database.sessions() as db:
        db.add_all([
                KnowledgeCandidate(id='maint-c1', paper_id='p1', entity_type='method', name='ReAct', normalized_name='react', role='proposed', confidence=.9, status='candidate', evidence_json='[{"chunk_id":"c1","page":1,"section":"Method","quote":"external memory","bbox":null,"page_width":null,"page_height":null}]'),
                KnowledgeCandidate(id='maint-c2', paper_id='p1', entity_type='method', name='ReAct', normalized_name='react', role='proposed', confidence=.9, status='candidate', evidence_json='[{"chunk_id":"c1","page":1,"section":"Method","quote":"external memory","bbox":null,"page_width":null,"page_height":null}]'),
        ])
        db.commit()
    worker.scope('topic', __import__('app.research_schemas', fromlist=['ScopeUpdate']).ScopeUpdate(enabled=False, focus=''))
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0, maintenance_enabled=True, maintenance_interval_minutes=30, maintenance_calls_per_run=1))
    writer = MaintenanceWriter()
    worker.profiles.subscription_provider = lambda _: writer
    worker.profiles.priority.presence('reading-tab', True)
    assert worker.process_next() is False
    assert worker.status()['reason'] == 'reading'
    worker.profiles.priority.presence('reading-tab', False)
    assert worker.process_next() is True, worker.status()
    assert worker.status()['maintenance']['status'] == 'partial'
    assert worker.process_next() is True, worker.status()
    assert worker.status()['maintenance']['status'] == 'complete'
    with worker.database.sessions() as db:
        run = db.scalar(select(KnowledgeMaintenanceRun).order_by(KnowledgeMaintenanceRun.created_at.desc()))
        assert json.loads(run.usage_json)['total_tokens'] == 104


def test_partial_maintenance_run_resumes_unchecked_issues(research):
    _, worker = research
    from app.models import KnowledgeMaintenanceRun
    from app.research_schemas import ResearchSettings, ScopeUpdate
    with worker.database.sessions() as db:
        db.add_all([
            KnowledgeCandidate(id='resume-c1', paper_id='p1', entity_type='method', name='ReAct', normalized_name='react', role='proposed', confidence=.9, status='candidate', evidence_json='[{"chunk_id":"c1","quote":"external memory"}]'),
            KnowledgeCandidate(id='resume-c2', paper_id='p1', entity_type='method', name='ReAct', normalized_name='react', role='proposed', confidence=.9, status='candidate', evidence_json='[{"chunk_id":"c1","quote":"external memory"}]'),
        ])
        db.commit()
    worker.scope('topic', ScopeUpdate(enabled=False, focus=''))
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0, maintenance_enabled=True, maintenance_interval_minutes=30, maintenance_calls_per_run=1))
    writer = MaintenanceWriter()
    worker.profiles.subscription_provider = lambda _: writer
    worker._next_maintenance_scan = 0
    assert worker.process_next() is True, worker.status()
    assert worker.status()['maintenance']['status'] == 'partial'
    worker._next_maintenance_scan = 0
    assert worker.process_next() is True, worker.status()
    worker._next_maintenance_scan = 0
    assert worker.status()['maintenance']['status'] == 'complete'
    assert len(writer.calls) == 2
    with worker.database.sessions() as db:
        run = db.scalar(select(KnowledgeMaintenanceRun).order_by(KnowledgeMaintenanceRun.created_at.desc()))
        assert len(json.loads(run.usage_json)['processed_issue_ids']) == 2


def test_reverting_focus_resumes_superseded_work(research):
    from app.research_schemas import ScopeUpdate
    _, worker = research
    original = worker.enqueue('topic')
    worker.scope('topic', ScopeUpdate(enabled=True, focus='Other question'))
    second = worker.enqueue('topic')
    worker.scope('topic', ScopeUpdate(enabled=True, focus='How does memory change decisions?'))
    returned = worker.enqueue('topic')
    assert returned['status'] == 'queued'
    assert returned['id'] == original['id']


def test_subscription_profile_cannot_be_replaced_with_paid_api(tmp_path):
    from app.providers.profiles import ProfileStore
    from app.schemas import ModelProfileUpdate
    store = ProfileStore(tmp_path/'models.json')
    profile = store.save(ModelProfileUpdate(name='Paid', api_key='test-secret',base_url='https://api.openai.com/v1',model='test-model',test_connection=False))
    with pytest.raises(ProviderError) as error:
        store.subscription_provider(profile['id'])
    assert error.value.code == 'subscription_required'


@pytest.mark.parametrize('bad', ['[2](#source-S999 "bad")', '[2][bad]\n\n[bad]: #source-S999 "bad"'])
def test_markdown_citation_variants_cannot_bypass_validation(bad):
    from app.services.research_materials import verify_article
    article=essay()
    article['markdown'] += '\n\n'+bad
    with pytest.raises(ValueError):
        verify_article(article, [{'id':'S1'}])


def test_unexpected_checkpoint_failure_recovers_on_next_tick(research, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.models import ResearchTask
    _, worker = research
    writer = Writer()
    worker.profiles.subscription_provider = lambda _: writer
    task = worker.enqueue('topic')
    original = worker.database.sessions.class_.commit
    def fail_after_generation(db):
        if len(writer.calls)==1:
            raise OperationalError('checkpoint', {}, Exception('locked'))
        return original(db)
    with monkeypatch.context() as patch:
        patch.setattr(worker.database.sessions.class_, 'commit', fail_after_generation)
        with pytest.raises(OperationalError):
            worker.process_next()
    assert worker.collection('topic')['task']['status']=='running'
    worker.process_next()
    assert worker.collection('topic')['task']['stage']=='draft'


def test_completed_history_can_become_current_again_without_mutating_revision(research):
    from app.research_schemas import ScopeUpdate
    _, worker = research
    worker.profiles.subscription_provider = lambda _: Writer()
    first = worker.enqueue('topic')
    for _ in range(3): worker.process_next()
    original_revision = worker.collection('topic')['revision']
    worker.scope('topic', ScopeUpdate(enabled=True,focus='New comparison'))
    worker.enqueue('topic')
    for _ in range(3): worker.process_next()
    worker.scope('topic', ScopeUpdate(enabled=True, focus='How does memory change decisions?'))
    latest = worker.enqueue('topic')
    assert latest['id'] != first['id']
    assert latest['status']=='queued'
    assert worker.collection('topic',original_revision['id'])['revision']==original_revision


def test_idle_monitor_refreshes_quota_without_regenerating_finished_article(research):
    client, worker = research
    writer=Writer()
    worker.profiles.subscription_provider=lambda _:writer
    worker.enqueue('topic')
    for _ in range(3): worker.process_next()
    worker._quota,worker._quota_at=[],0
    worker.process_next()
    assert worker.status()['quota']
    assert len(writer.calls)==3
    response=client.get('/api/research/quota')
    assert response.status_code==200
    assert response.json()['quota'][0]['used_percent']==10
    assert 'email' not in response.json()


@pytest.mark.parametrize('kind', ['illustrative', 'reported'])
def test_teaching_examples_preserve_their_provenance(kind):
    from app.services.research_materials import verify_teaching
    plan = teaching()
    plan['explanations'][0]['example']['kind'] = kind
    verify_teaching(plan, [{'id': 'S1'}])
    # An example is optional; a useful mechanism explanation is not.
    plan['explanations'][0].pop('example')
    verify_teaching(plan, [{'id': 'S1'}])


@pytest.mark.parametrize('damage', ['missing_plan', 'unknown_step', 'unbacked_report', 'ambiguous_example'])
def test_teaching_cannot_pass_unverified_mechanisms_or_untyped_examples(damage):
    from app.services.research_materials import verify_teaching
    plan = teaching()
    if damage == 'missing_plan':
        plan = None
    elif damage == 'unknown_step':
        plan['explanations'][0]['steps'][0]['source_ids'] = ['S999']
    elif damage == 'unbacked_report':
        plan['explanations'][0]['example'].update(kind='reported', source_ids=[])
    else:
        plan['explanations'][0]['example']['kind'] = 'fact_or_imagination'
    with pytest.raises(ValueError):
        verify_teaching(plan, [{'id': 'S1'}])


def test_teaching_plan_survives_checkpoint_and_reaches_writer_and_editor(research):
    _, worker = research
    writer = Writer()
    worker.profiles.subscription_provider = lambda _: writer
    worker.enqueue('topic')
    worker.process_next()
    # Resuming uses the persisted plan, rather than reconstructing it from a summary.
    from app.services.background_research import BackgroundResearchWorker
    resumed = BackgroundResearchWorker(worker.database, worker.profiles)
    resumed.process_next()
    resumed.process_next()
    for _, user in writer.calls[1:]:
        assert json.loads(user)['synthesis']['teaching'] == teaching()
    assert resumed.collection('topic')['revision']['number'] == 1


def test_missing_teaching_plan_stops_before_drafting(research):
    _, worker = research
    class UngroundedWriter(Writer):
        def _complete(self, system, user, **kw):
            result = json.loads(super()._complete(system, user, **kw))
            result.pop('teaching', None)
            return json.dumps(result)
    writer = UngroundedWriter()
    worker.profiles.subscription_provider = lambda _: writer
    worker.enqueue('topic')
    for _ in range(3):
        worker.process_next()
        worker._retry_at = 0
    current = worker.collection('topic')
    assert current['task']['status'] == 'failed'
    assert current['task']['stage'] == 'synthesis'
    assert current['revision'] is None
    assert len(writer.calls) == 2


def test_previous_prose_is_read_for_insights_but_not_reused_as_writer_template(research):
    _, worker = research
    writer = Writer()
    worker.profiles.subscription_provider = lambda _: writer
    worker.enqueue('topic')
    for _ in range(3): worker.process_next()
    with worker.database.sessions() as db:
        db.get(Note, 'n1').kind = 'note'
        db.get(Note, 'n1').content = 'Explain the actual retrieval process.'
        db.commit()
    worker.enqueue('topic')
    worker.process_next()
    worker.process_next()
    reading = json.loads(writer.calls[3][1])
    writing = json.loads(writer.calls[4][1])
    assert reading['previous_article'] == essay()['markdown']
    assert 'previous_article' not in writing
    assert writing['synthesis']['teaching'] == teaching()


def test_changed_writing_recipe_creates_new_version_without_editing_scope_or_history(research, monkeypatch, tmp_path):
    from pathlib import Path
    from app.services import research_materials
    _, worker = research
    for stage in ('synthesis', 'draft', 'review'):
        text = (Path(__file__).resolve().parents[2] / 'prompts' / f'research_{stage}.txt').read_text(encoding='utf-8')
        (tmp_path / f'research_{stage}.txt').write_text(text, encoding='utf-8')
    monkeypatch.setattr(research_materials, 'PROMPTS', tmp_path, raising=False)
    worker.profiles.subscription_provider = lambda _: Writer()
    first = worker.enqueue('topic')
    for _ in range(3): worker.process_next()
    before = worker.collection('topic')
    assert worker.enqueue('topic')['id'] == first['id']
    draft = tmp_path / 'research_draft.txt'
    draft.write_text(draft.read_text(encoding='utf-8') + '\nExplain the execution steps.', encoding='utf-8')
    second = worker.enqueue('topic')
    assert second['id'] != first['id']
    after = worker.collection('topic')
    assert after['revision'] == before['revision']
    assert after['scope'] == before['scope']
    for _ in range(3): worker.process_next()
    assert worker.collection('topic')['revision']['number'] == 2
    assert worker.collection('topic', before['revision']['id'])['revision'] == before['revision']
