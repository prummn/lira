import json
import time

import pytest
from sqlalchemy import select

from app.models import PaperChunk, ResearchTask, ResearchFinding, KnowledgeCandidate
from app.research_schemas import ResearchSettings, ScopeUpdate
from test_background_research import research


def brief(**changes):
    return {**dict(title='When does retrieval affect the next action?',
        question='Trace a stored memory through retrieval to the next action.',
        rationale='The existing note asks whether retrieval becomes stale.',
        kind='gap', paper_ids=['p1'], section_hints=['Method'], existing_id=None), **changes}


class Planner:
    model = 'fixture-planner'
    last_usage = {'input_tokens': 100, 'output_tokens': 60}

    def __init__(self):
        self.calls = []

    def _complete(self, system, user, **kwargs):
        self.calls.append((system, json.loads(user)))
        if 'STAGE: PLAN' in system:
            return json.dumps({'tasks': [brief()]})
        return json.dumps({'findings': [dict(kind='gap', title='Retrieval selects the experience',
            body='The experience is stored, then selected by relevance and recency before use. [1](#source-S1)',
            next_step='Trace the action after retrieval.', existing_id=None,
            evidence=[{'source_id': 'S1', 'quote': 'The agent stores experience in external memory.'}])]})


def prepare(worker):
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0,
                                    investigations_enabled=True, calls_per_hour=18))
    worker.scope('topic', ScopeUpdate(enabled=True, focus='How does memory change decisions?',
                                     work_types=['gaps', 'connections', 'questions']))
    initial = worker.enqueue('topic', kind='findings')
    with worker.database.sessions() as db:
        db.get(ResearchTask, initial['id']).status = 'completed'
        db.commit()
    return initial


def test_plan_rejects_unselected_types_unknown_papers_and_duplicate_questions(research):
    from app.services.research_agenda import validate_plan
    _, worker = research
    prepare(worker)
    material = {'work_types': ['gaps'], 'papers': [{'id': 'p1'}]}
    assert len(validate_plan({'tasks': [brief()]}, material, [])) == 1
    for tasks in ([brief(paper_ids=['p2'])], [brief(kind='connection')],
                  [brief(), brief(title='Renamed', question='Trace a stored memory through retrieval to the next action. ')],
                  [brief(existing_id='not-in-this-topic')], [brief()] * 7):
        with pytest.raises(ValueError):
            validate_plan({'tasks': tasks}, material, [])
    assert validate_plan({'tasks': []}, material, []) == []


def test_planning_persists_finite_tasks_and_publishes_in_existing_findings(research):
    client, worker = research
    prepare(worker)
    planner = Planner()
    worker.profiles.subscription_provider = lambda _: planner
    for _ in range(5):
        worker._next_scan = 0
        worker.process_next()
    data = client.get('/api/research/collections/topic/findings').json()
    assert len(data['agenda']['tasks']) == 1
    task = data['agenda']['tasks'][0]
    assert task['title'] == brief()['title']
    assert task['status'] == 'completed'
    assert task['outcome_ids'] == [data['items'][0]['id']]
    assert len(planner.calls) == 3
    assert data['agenda']['planner']['status'] == 'completed'
    for _ in range(3):
        worker._next_scan = 0
        worker.process_next()
    assert len(planner.calls) == 3


def test_investigation_material_reads_full_local_sections_beyond_initial_snapshot(research):
    from app.services.research_agenda import investigation_material
    _, worker = research
    prepare(worker)
    with worker.database.sessions() as db:
        db.add(PaperChunk(id='late', paper_id='p1', page=14, section='Appendix retrieval',
                         content='An obscure appendix describes stale memory handling in detail.'))
        db.commit()
        material = investigation_material(db, 'topic', 'base', brief(section_hints=['Appendix retrieval']),
                                          {'papers': [{'id': 'p1', 'title': 'Memory'}],
                                           'sources': [], 'coverage': [], 'work_types': ['gaps']})
    assert any(s['chunk_id'] == 'late' for s in material['sources'])
    assert material['investigation'] == brief(section_hints=['Appendix retrieval'])
    assert material['work_types'] == ['gaps']
    assert all(s['paper_id'] == 'p1' for s in material['sources'])


def test_reading_allows_agenda_but_hourly_budget_still_stops_calls(research):
    _, worker = research
    prepare(worker)
    planner = Planner()
    worker.profiles.subscription_provider = lambda _: planner
    worker.profiles.priority.presence('reader', True)
    worker._next_scan = 0
    worker.process_next()
    worker.process_next()
    assert planner.calls
    count = len(planner.calls)
    with worker.database.sessions() as db:
        task = db.scalar(select(ResearchTask).where(ResearchTask.kind == 'findings'))
        task.usage_json = json.dumps({'call_times': [time.time()] * 18})
        db.commit()
    worker.process_next()
    assert len(planner.calls) == count
    assert worker.status()['reason'] == 'hourly_budget'


def test_turning_off_deep_research_stops_children_without_losing_queue(research):
    client, worker = research
    prepare(worker)
    planner = Planner()
    worker.profiles.subscription_provider = lambda _: planner
    for _ in range(3):
        worker._next_scan = 0
        worker.process_next()
        if client.get('/api/research/collections/topic/findings').json()['agenda']['tasks']:
            break
    settings = worker.settings()
    settings.investigations_enabled = False
    worker.settings(settings)
    count = len(planner.calls)
    for _ in range(3):
        worker.process_next()
    assert len(planner.calls) == count
    assert client.get('/api/research/collections/topic/findings').json()['agenda']['tasks'][0]['status'] == 'queued'


def test_changed_material_supersedes_old_investigation(research):
    client, worker = research
    prepare(worker)
    planner = Planner()
    worker.profiles.subscription_provider = lambda _: planner
    for _ in range(3):
        worker._next_scan = 0
        worker.process_next()
        if client.get('/api/research/collections/topic/findings').json()['agenda']['tasks']:
            break
    with worker.database.sessions() as db:
        db.get(PaperChunk, 'c1').content += ' New evidence changes the conclusion.'
        db.commit()
    worker.process_next()
    with worker.database.sessions() as db:
        task = db.scalar(select(ResearchTask).where(ResearchTask.kind == 'investigation'))
        assert task.status == 'superseded'
    assert len(planner.calls) == 1


def test_deep_research_budget_can_be_raised_without_removing_quota_reserves(research):
    client, worker = research
    prepare(worker)
    settings = worker.settings().model_dump()
    settings['calls_per_hour'] = 36
    response = client.put('/api/research/settings', json=settings)
    assert response.status_code == 200
    assert response.json()['stop_remaining'] == 35
    assert response.json()['long_reserve'] == 30
    settings['calls_per_hour'] = 61
    assert client.put('/api/research/settings', json=settings).status_code == 422


def test_maintenance_batch_cannot_exceed_remaining_hourly_budget(research):
    from test_background_research import MaintenanceWriter
    _, worker = research
    initial = prepare(worker)
    worker.scope('topic', ScopeUpdate(enabled=False))
    settings = worker.settings()
    settings.maintenance_enabled = True
    worker.settings(settings)
    with worker.database.sessions() as db:
        task = db.get(ResearchTask, initial['id'])
        task.usage_json = json.dumps({'call_times': [time.time()] * 17})
        for key in ('dup-1', 'dup-2'):
            db.add(KnowledgeCandidate(id=key, paper_id='p1', entity_type='method',
                name='Memory', normalized_name='memory', status='candidate',
                evidence_json='[{"chunk_id":"c1","quote":"external memory"}]'))
        db.commit()
    writer = MaintenanceWriter()
    worker.profiles.subscription_provider = lambda _: writer
    worker.process_next()
    assert len(writer.calls) == 1


def test_finish_one_investigation_before_starting_more_drafts(research):
    client, worker = research
    prepare(worker)
    class TwoQuestions(Planner):
        def _complete(self, system, user, **kwargs):
            result = super()._complete(system, user, **kwargs)
            if 'STAGE: PLAN' in system:
                return json.dumps({'tasks': [brief(), brief(title='What happens to stale memories?',
                    question='Check whether outdated memories expire after a newer event.')]})
            return result
    writer = TwoQuestions()
    worker.profiles.subscription_provider = lambda _: writer
    worker.process_next()
    worker.process_next()
    worker.process_next()
    worker.process_next()
    data = client.get('/api/research/collections/topic/findings').json()
    states = sorted(task['status'] for task in data['agenda']['tasks'])
    assert states == ['completed', 'queued']
    assert len(data['items']) == 1


def test_full_source_changes_outside_initial_sample_invalidate_deep_work(research):
    from app.models import ResearchScope
    from app.services import research_agenda as agenda
    _, worker = research
    with worker.database.sessions() as db:
        db.get(PaperChunk, 'c1').content = 'A' * 79000
        db.add(PaperChunk(id='late', paper_id='p1', page=2, section='Method', content='B' * 2000))
        db.commit()
    prepare(worker)
    with worker.database.sessions() as db:
        scope = db.get(ResearchScope, 'topic')
        parent = agenda.enqueue_plan(db, 'topic', scope.focus, json.loads(scope.work_types_json))
        assert parent is not None
        agenda.create_investigations(db, parent, [brief()])
        child = db.scalar(select(ResearchTask).where(ResearchTask.kind == 'investigation'))
        assert any(s['chunk_id'] == 'late' for s in json.loads(child.material_json)['sources'])
        assert worker._current_material(db, child, scope)
        db.get(PaperChunk, 'late').content = 'C' * 2000
        db.commit()
        assert not worker._current_material(db, child, scope)
        updated = agenda.enqueue_plan(db, 'topic', scope.focus, json.loads(scope.work_types_json))
        assert updated.id != parent.id


def test_existing_session_plan_is_adopted_without_repeating_completed_work(research):
    import hashlib
    from app.models import ResearchScope
    from app.services import research_agenda as agenda
    _, worker = research
    prepare(worker)
    with worker.database.sessions() as db:
        scope = db.get(ResearchScope, 'topic')
        parent = agenda.enqueue_plan(db, 'topic', scope.focus, json.loads(scope.work_types_json))
        agenda.create_investigations(db, parent, [brief()])
        material = json.loads(parent.material_json)
        recipe = [(agenda.PROMPTS / f'research_{s}.txt').read_text(encoding='utf-8') for s in ('plan', 'investigate')]
        parent.fingerprint = hashlib.sha256(agenda.dumps(['agenda-v1', material['_base_fingerprint'], recipe]).encode()).hexdigest()
        material.pop('_source_fingerprint')
        parent.material_json = agenda.dumps(material)
        parent.status = 'completed'
        child = db.scalar(select(ResearchTask).where(ResearchTask.kind == 'investigation'))
        saved = json.loads(child.material_json)
        saved.pop('_source_fingerprint')
        child.material_json = agenda.dumps(saved)
        db.commit()
        adopted = agenda.enqueue_plan(db, 'topic', scope.focus, json.loads(scope.work_types_json))
        assert adopted.id == parent.id
        assert adopted.status == 'completed'
        assert json.loads(child.material_json)['_source_fingerprint'] == json.loads(adopted.material_json)['_source_fingerprint']
        assert len(list(db.scalars(select(ResearchTask).where(ResearchTask.kind == 'agenda')))) == 1


def test_legacy_plan_with_changed_child_sources_is_replanned(research):
    import hashlib
    from app.models import ResearchScope
    from app.services import research_agenda as agenda
    _, worker = research
    with worker.database.sessions() as db:
        db.get(PaperChunk, 'c1').content = 'A' * 79000
        db.add(PaperChunk(id='late', paper_id='p1', page=2, section='Method', content='B' * 2000))
        db.commit()
    prepare(worker)
    with worker.database.sessions() as db:
        scope = db.get(ResearchScope, 'topic')
        types = json.loads(scope.work_types_json)
        parent = agenda.enqueue_plan(db, 'topic', scope.focus, types)
        agenda.create_investigations(db, parent, [brief()])
        material = json.loads(parent.material_json)
        recipe = [(agenda.PROMPTS / f'research_{s}.txt').read_text(encoding='utf-8') for s in ('plan', 'investigate')]
        parent.fingerprint = hashlib.sha256(agenda.dumps(['agenda-v1', material['_base_fingerprint'], recipe]).encode()).hexdigest()
        material.pop('_source_fingerprint')
        parent.material_json = agenda.dumps(material)
        parent.status = 'completed'
        db.get(PaperChunk, 'late').content = 'C' * 2000
        db.commit()
        updated = agenda.enqueue_plan(db, 'topic', scope.focus, types)
        assert updated.id != parent.id
        assert updated.status == 'queued'


def add_prior(worker):
    with worker.database.sessions() as db:
        db.add(ResearchFinding(id='prior', collection_id='topic', identity='prior-identity', kind='gap',
            title='Existing memory question', body='A useful earlier explanation.', next_step='Inspect retrieval.',
            sources_json='[]', model='fixture'))
        db.commit()


@pytest.mark.parametrize('when', ['plan', 'queued', 'assess'])
@pytest.mark.parametrize('decision', ['dismiss', 'done'])
def test_user_decisions_stop_targeted_work_at_each_checkpoint(research, when, decision):
    client, worker = research
    prepare(worker)
    add_prior(worker)
    class TargetedPlanner(Planner):
        def _complete(self, system, user, **kwargs):
            result = super()._complete(system, user, **kwargs)
            if f'STAGE: {when.upper()}' in system:
                worker.finding_action('prior', decision)
            if 'STAGE: PLAN' in system:
                return json.dumps({'tasks': [brief(existing_id='prior')]})
            return result
    writer = TargetedPlanner()
    worker.profiles.subscription_provider = lambda _: writer
    worker.process_next()
    worker.process_next()
    if when == 'queued':
        worker.finding_action('prior', decision)
    for _ in range(4):
        worker.process_next()
    data = client.get('/api/research/collections/topic/findings').json()
    assert len(data['items']) == 1
    assert data['items'][0]['body'] == 'A useful earlier explanation.'
    assert data['items'][0]['status'] == ('dismissed' if decision == 'dismiss' else 'done')
    assert len(writer.calls) == (3 if when == 'assess' else 1)
    assert all(t['status'] == 'superseded' for t in data['agenda']['tasks'])


def test_targeted_result_updates_original_even_when_model_omits_existing_id(research):
    client, worker = research
    prepare(worker)
    add_prior(worker)
    class TargetedPlanner(Planner):
        def _complete(self, system, user, **kwargs):
            result = super()._complete(system, user, **kwargs)
            return json.dumps({'tasks': [brief(existing_id='prior')]}) if 'STAGE: PLAN' in system else result
    writer = TargetedPlanner()
    worker.profiles.subscription_provider = lambda _: writer
    for _ in range(4):
        worker.process_next()
    items = client.get('/api/research/collections/topic/findings').json()['items']
    assert len(items) == 1
    assert items[0]['id'] == 'prior'
    assert items[0]['title'] == 'Retrieval selects the experience'
    assert len(worker.finding_history('prior')['revisions']) == 1


def test_failed_maintenance_generations_consume_shared_hourly_budget(research):
    from app.providers.base import ProviderError
    from test_background_research import MaintenanceWriter
    _, worker = research
    initial = prepare(worker)
    worker.scope('topic', ScopeUpdate(enabled=False))
    settings = worker.settings()
    settings.maintenance_enabled = True
    worker.settings(settings)
    with worker.database.sessions() as db:
        db.get(ResearchTask, initial['id']).usage_json = json.dumps({'call_times': [time.time()] * 17})
        for key in ('dup-1', 'dup-2'):
            db.add(KnowledgeCandidate(id=key, paper_id='p1', entity_type='method', name='Memory',
                normalized_name='memory', status='candidate', evidence_json='[{"chunk_id":"c1","quote":"external memory"}]'))
        db.commit()
    class FailingAuditor(MaintenanceWriter):
        def audit_knowledge_bundle(self, bundle):
            self.calls.append(bundle)
            raise ProviderError('Invalid generated citation', 502, code='invalid_response')
    writer = FailingAuditor()
    worker.profiles.subscription_provider = lambda _: writer
    for _ in range(4):
        worker._retry_at = 0
        worker.process_next()
    assert len(writer.calls) == 1
    assert worker._remaining_calls(settings) == 0
