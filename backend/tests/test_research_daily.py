import json
import time

import pytest
from sqlalchemy import select

from app.models import ChatConversation, ChatTurn, Note, PaperChunk, ResearchScope, ResearchTask
from app.research_schemas import ResearchSettings, ScopeUpdate
from test_background_research import research


def test_maintenance_rechecks_actual_quota_between_every_generation(research):
    from app.models import KnowledgeCandidate
    from test_background_research import MaintenanceWriter
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    settings = worker.settings()
    settings.maintenance_enabled = True
    settings.maintenance_calls_per_run = 3
    worker.settings(settings)
    used = [7]
    reset = time.time()+6*86400
    worker.profiles.codex.status = lambda **kw: dict(authenticated=True, limits=[
        dict(name='primary', used_percent=10, window_minutes=300, resets_at=time.time()+300),
        dict(name='secondary', used_percent=used[0], window_minutes=10080, resets_at=reset)])
    class ConsumingAuditor(MaintenanceWriter):
        def audit_knowledge_bundle(self, bundle):
            used[0] = 75
            return super().audit_knowledge_bundle(bundle)
    with worker.database.sessions() as db:
        for i in range(2):
            db.add(KnowledgeCandidate(id=f'dup-{i}', paper_id='p1', entity_type='method', name='Memory',
                normalized_name='memory', status='candidate', evidence_json='[{"chunk_id":"c1","quote":"external memory"}]'))
        db.commit()
    writer = ConsumingAuditor()
    worker.profiles.subscription_provider = lambda _: writer
    worker.process_next()
    worker.process_next()
    assert len(writer.calls) == 1
    assert worker.status()['reason'] == 'quota_reserve'


@pytest.mark.parametrize('started,used,allowed', [(False, 50, False), (True, 50, True), (True, 65, False)])
def test_maintenance_uses_the_same_start_and_stop_thresholds(research, started, used, allowed):
    from app.models import KnowledgeCandidate
    from app.services.knowledge_maintenance import prepare_run
    from test_background_research import MaintenanceWriter
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    settings = worker.settings()
    settings.maintenance_enabled = True
    settings.maintenance_calls_per_run = 1
    worker.settings(settings)
    with worker.database.sessions() as db:
        for i in range(2):
            db.add(KnowledgeCandidate(id=f'threshold-{i}', paper_id='p1', entity_type='method', name='Memory',
                normalized_name='memory', status='candidate', evidence_json='[{"chunk_id":"c1","quote":"external memory"}]'))
        db.flush()
        run = prepare_run(db, scope_type='library', allow_external=False)
        if started:
            run.usage_json = json.dumps({'call_times': [time.time()-120]})
        db.commit()
    worker.profiles.codex.status = lambda **kw: dict(authenticated=True, limits=[
        dict(name='primary', used_percent=used, window_minutes=300, resets_at=time.time()+300)])
    # Exercise both a recent quota observation and the periodic refresh path.
    worker._quota_at = 0 if started else time.time()
    writer = MaintenanceWriter()
    worker.profiles.subscription_provider = lambda _: writer
    assert worker.process_next() is allowed
    assert len(writer.calls) == int(allowed)


def test_resuming_fresh_maintenance_does_not_block_another_started_batch(research):
    from app.models import KnowledgeCandidate
    from app.services.knowledge_maintenance import prepare_run
    from test_background_research import MaintenanceWriter
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=False))
    settings = worker.settings()
    settings.maintenance_enabled = True
    settings.maintenance_calls_per_run = 1
    worker.settings(settings)
    with worker.database.sessions() as db:
        for i in range(2):
            db.add(KnowledgeCandidate(id=f'batch-{i}', paper_id='p1', entity_type='method', name='Memory',
                normalized_name='memory', status='candidate', evidence_json='[{"chunk_id":"c1","quote":"external memory"}]'))
        db.flush()
        older = prepare_run(db, scope_type='library', allow_external=False)
        older.status = 'cancelled'
        db.flush()
        newer = prepare_run(db, scope_type='library', allow_external=False)
        older_id = older.id
        db.commit()
    writer = MaintenanceWriter()
    worker.profiles.subscription_provider = lambda _: writer
    assert worker.process_next()
    worker.maintenance_action(older_id, 'retry')
    worker.profiles.codex.status = lambda **kw: dict(authenticated=True, limits=[
        dict(name='primary', used_percent=50, window_minutes=300, resets_at=time.time()+300)])
    assert worker.process_next()
    assert len(writer.calls) == 2


def enable_reading(worker):
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0,
                                    investigations_enabled=True, calls_per_hour=24))
    worker.scope('topic', ScopeUpdate(enabled=True, focus='Memory in action', work_types=['reading']))


class ReadingWriter:
    model = 'reading-fixture'
    last_usage = {'input_tokens': 300, 'output_tokens': 100}

    def __init__(self):
        self.calls = []

    def _complete(self, system, user, **kwargs):
        context = json.loads(user)
        self.calls.append(context)
        return json.dumps({'findings': [dict(kind='reading', title='How retrieval selects a memory',
            body='Retrieval depends on relevance and recency. [1](#source-S1)',
            next_step='Follow the retrieved experience into the next action.', existing_id=None,
            evidence=[dict(source_id='S1', quote='The agent stores experience in external memory.')])]})


def test_reading_questions_run_without_base_round_and_persist_origin(research):
    client, worker = research
    enable_reading(worker)
    writer = ReadingWriter()
    worker.profiles.subscription_provider = lambda _: writer
    for _ in range(4):
        worker._next_scan = 0
        worker.process_next()
    data = client.get('/api/research/collections/topic/findings').json()
    assert len(writer.calls) == 2
    assert len(data['items']) == 1 and data['items'][0]['kind'] == 'reading'
    task = data['agenda']['tasks'][0]
    assert task['origin']['kind'] == 'note'
    assert task['origin']['id'] == 'n1'
    assert task['outcome_ids'] == [data['items'][0]['id']]
    assert task['status'] == 'completed'
    with worker.database.sessions() as db:
        assert not db.scalar(select(ResearchTask).where(ResearchTask.kind.in_(['essay', 'findings', 'agenda'])))


def test_cancelled_intent_stays_cancelled_but_edited_question_can_run(research):
    from app.services.research_reading import enqueue_reading
    _, worker = research
    enable_reading(worker)
    with worker.database.sessions() as db:
        scope = db.get(ResearchScope, 'topic')
        first = enqueue_reading(db, scope)[0]
        first.status = 'cancelled'
        db.commit()
        assert enqueue_reading(db, scope)[0].id == first.id
        db.get(Note, 'n1').content = 'What determines relevance during retrieval?'
        db.commit()
        second = enqueue_reading(db, scope)[0]
        assert second.id != first.id
        db.commit()


def test_reverted_question_can_resume_superseded_task(research):
    from app.services.research_reading import enqueue_reading
    _, worker = research
    enable_reading(worker)
    with worker.database.sessions() as db:
        scope = db.get(ResearchScope, 'topic')
        first = enqueue_reading(db, scope)[0]
        first.status = 'superseded'
        db.commit()
        restored = enqueue_reading(db, scope)[0]
        assert restored.id == first.id and restored.status == 'queued'
        restored.status = 'superseded'
        db.delete(db.get(Note, 'n1'))
        db.add(Note(id='recreated', paper_id='p1', kind='question', content='Does retrieval become stale?'))
        db.commit()
        restored = enqueue_reading(db, scope)[0]
        assert json.loads(restored.material_json)['origin']['id'] == 'recreated'


def test_reading_task_has_one_stable_home_and_cancellation_survives_scope_changes(research):
    from app.models import CollectionPaper
    from app.services.research_reading import enqueue_reading
    _, worker = research
    enable_reading(worker)
    with worker.database.sessions() as db:
        first = enqueue_reading(db, db.get(ResearchScope, 'topic'))[0]
        db.add(CollectionPaper(collection_id='other', paper_id='p1'))
        db.add(ResearchScope(collection_id='other', enabled=True, focus='Memory in action', work_types_json='["reading"]'))
        db.commit()
        enqueue_reading(db, db.get(ResearchScope, 'other'))
        assert len(list(db.scalars(select(ResearchTask).where(ResearchTask.kind == 'investigation')))) == 1
        first.status = 'cancelled'
        db.get(ResearchScope, 'topic').enabled = False
        db.commit()
        enqueue_reading(db, db.get(ResearchScope, 'other'))
        assert len(list(db.scalars(select(ResearchTask).where(ResearchTask.kind == 'investigation')))) == 1


def test_same_question_on_different_passages_is_two_reading_intents(research):
    from app.services.research_reading import enqueue_reading
    _, worker = research
    enable_reading(worker)
    with worker.database.sessions() as db:
        note = db.get(Note, 'n1')
        note.content, note.page, note.source_text = 'What does this paragraph mean?', 1, 'First passage'
        db.add(Note(id='another', paper_id='p1', kind='question', content=note.content,
                    page=2, source_text='Second passage'))
        db.commit()
        tasks = enqueue_reading(db, db.get(ResearchScope, 'topic'))
        assert len(tasks) == 2 and tasks[0].intent_key != tasks[1].intent_key
        db.commit()
    worker.profiles.subscription_provider = lambda _: ReadingWriter()
    for _ in range(5): worker.process_next()
    assert len(worker.findings('topic')['items']) == 2


def test_reading_only_scope_can_request_an_immediate_scan(research):
    client, worker = research
    enable_reading(worker)
    response = client.post('/api/research/collections/topic/reading')
    assert response.status_code == 200
    assert len(response.json()['tasks']) == 1


def test_new_reading_intent_cannot_overwrite_an_unrelated_answer(research):
    import pytest
    from app.services.research_agenda import bind_target
    data = {'findings': [dict(existing_id='another-answer')]}
    with pytest.raises(ValueError):
        bind_target(data, {'origin': {'kind': 'note'}, 'investigation': {'existing_id': None}})


@pytest.mark.parametrize('decision', ['keep', 'dismiss', 'done'])
def test_a_rephrased_question_can_link_existing_answer_without_overwriting_it(research, decision):
    from app.services.research_reading import enqueue_reading
    _, worker = research
    enable_reading(worker)
    worker.profiles.subscription_provider = lambda _: ReadingWriter()
    for _ in range(3): worker.process_next()
    item = worker.findings('topic')['items'][0]
    with worker.database.sessions() as db:
        db.get(Note, 'n1').content = 'Could you explain the same retrieval sequence again?'
        db.commit()
    class ReuseWriter(ReadingWriter):
        def _complete(self, *args, **kwargs):
            super()._complete(*args, **kwargs)
            return json.dumps({'answered_by': item['id'], 'reason': 'The same retrieval mechanism is already explained.'})
    writer = ReuseWriter()
    worker.profiles.subscription_provider = lambda _: writer
    worker._next_reading_scan = 0
    for _ in range(3): worker.process_next()
    data = worker.findings('topic')
    assert len(writer.calls) == 1
    assert len(data['items']) == 1 and data['items'][0]['body'] == item['body']
    assert all(t['status'] == 'completed' and t['outcome_ids'] == [item['id']] for t in data['agenda']['tasks'])
    worker.finding_action(item['id'], decision)
    with worker.database.sessions() as db:
        db.get(PaperChunk, 'c1').content += ' A clarification of the protocol.'
        db.commit()
        tasks = enqueue_reading(db, db.get(ResearchScope, 'topic'))
        assert len(tasks) == 1
        if decision == 'keep':
            assert tasks[0].status == 'queued'
            assert json.loads(tasks[0].material_json)['investigation']['existing_id'] == item['id']
        else:
            assert tasks[0].status == 'completed'


@pytest.mark.parametrize('field,value', [('page', 2), ('section', 'Corrected section')])
def test_reused_answer_rejects_changed_source_locator(research, field, value):
    from app.services.research_reading import answer_reference
    _, worker = research
    enable_reading(worker)
    worker.profiles.subscription_provider = lambda _: ReadingWriter()
    for _ in range(3): worker.process_next()
    item = worker.findings('topic')['items'][0]
    with worker.database.sessions() as db:
        setattr(db.get(PaperChunk, 'c1'), field, value)
        db.commit()
        with pytest.raises(ValueError, match='已有答案依据已经变化'):
            answer_reference(db, 'topic', {'origin': {'paper_id': 'p1'}},
                             {'answered_by': item['id'], 'reason': 'The same retrieval mechanism is already explained.'})


def test_rejected_draft_is_available_for_repair_and_started_work_uses_stop_threshold(research):
    _, worker = research
    enable_reading(worker)
    used = [47]
    worker.profiles.codex.status = lambda **kw: dict(authenticated=True, limits=[
        dict(name='primary', used_percent=used[0], window_minutes=300, resets_at=time.time()+300)])
    class RepairWriter(ReadingWriter):
        def _complete(self, *args, **kwargs):
            output = json.loads(super()._complete(*args, **kwargs))
            if len(self.calls) == 1:
                used[0] = 50
                output['findings'][0]['evidence'][0]['quote'] = 'An invented quotation without support.'
            elif len(self.calls) == 2:
                assert self.calls[-1]['rejected_draft']['findings'][0]['evidence'][0]['quote'].startswith('An invented')
            return json.dumps(output)
    writer = RepairWriter()
    worker.profiles.subscription_provider = lambda _: writer
    for _ in range(4):
        worker._retry_at = 0
        worker.process_next()
    assert len(writer.calls) == 3
    assert worker.findings('topic')['agenda']['tasks'][0]['status'] == 'completed'


def test_fresh_question_cannot_block_started_work_at_start_reserve(research):
    from datetime import datetime, timedelta, timezone
    from app.services.research_reading import enqueue_reading
    _, worker = research
    enable_reading(worker)
    with worker.database.sessions() as db:
        scope = db.get(ResearchScope, 'topic')
        fresh = enqueue_reading(db, scope)[0]
        fresh.updated_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.add(Note(id='n2', paper_id='p1', kind='question', content='How does the search continue?'))
        db.flush()
        started = next(t for t in enqueue_reading(db, scope) if t.id != fresh.id)
        started.calls = 1
        started.updated_at = datetime.now(timezone.utc)
        started_id, fresh_id = started.id, fresh.id
        db.commit()
    worker.profiles.codex.status = lambda **kw: dict(authenticated=True, limits=[
        dict(name='primary', used_percent=50, window_minutes=300, resets_at=time.time()+300)])
    writer = ReadingWriter()
    worker.profiles.subscription_provider = lambda _: writer
    assert worker.process_next()
    with worker.database.sessions() as db:
        assert db.get(ResearchTask, started_id).stage == 'assess'
        assert db.get(ResearchTask, fresh_id).calls == 0
    assert len(writer.calls) == 1


def test_older_pending_question_remains_valid_and_ignored_result_stays_ignored(research):
    from app.services.research_reading import enqueue_reading, intent_active
    _, worker = research
    enable_reading(worker)
    writer = ReadingWriter()
    worker.profiles.subscription_provider = lambda _: writer
    for _ in range(3): worker.process_next()
    item = worker.findings('topic')['items'][0]
    worker.finding_action(item['id'], 'dismiss')
    with worker.database.sessions() as db:
        first = db.scalar(select(ResearchTask).where(ResearchTask.kind == 'investigation'))
        original = json.loads(first.material_json)
        for i in range(45):
            db.add(Note(id=f'new-{i}', paper_id='p1', kind='question', content=f'New question {i}'))
        db.get(PaperChunk, 'c1').content += ' A source correction.'
        db.commit()
        assert intent_active(db, 'topic', original)
        enqueue_reading(db, db.get(ResearchScope, 'topic'))
        assert len(list(db.scalars(select(ResearchTask).where(ResearchTask.intent_key == first.intent_key)))) == 1


def test_deleted_or_answered_intent_cannot_publish(research):
    _, worker = research
    enable_reading(worker)
    class ChangedDuringCall(ReadingWriter):
        def _complete(self, *args, **kwargs):
            answer = super()._complete(*args, **kwargs)
            with worker.database.sessions() as db:
                db.delete(db.get(Note, 'n1'))
                db.commit()
            return answer
    writer = ChangedDuringCall()
    worker.profiles.subscription_provider = lambda _: writer
    for _ in range(4):
        worker._next_scan = 0
        worker.process_next()
    assert len(writer.calls) == 1
    assert worker.findings('topic')['items'] == []
    assert worker.findings('topic')['agenda']['tasks'][0]['status'] == 'superseded'


def test_successful_chat_is_not_reanswered_and_retry_success_retires_failed_intent(research):
    from app.services.research_reading import enqueue_reading, intent_active
    _, worker = research
    enable_reading(worker)
    with worker.database.sessions() as db:
        db.delete(db.get(Note, 'n1'))
        db.add(ChatConversation(id='chat', kind='explanation', paper_id='p1',
            context_json='{"page":1,"chunk_id":"c1","selected_text":"relevance"}', context_key='key'))
        db.flush()
        db.add(ChatTurn(id='failed', conversation_id='chat', request_id='failed',
                        question='How does retrieval work?', status='failed'))
        db.add(ChatTurn(id='answered', conversation_id='chat', request_id='answered',
                        question='What is external memory?', status='completed', response_json='{}'))
        db.commit()
        tasks = enqueue_reading(db, db.get(ResearchScope, 'topic'))
        assert len(tasks) == 1
        material = json.loads(tasks[0].material_json)
        assert material['origin']['id'] == 'failed'
        db.add(ChatTurn(id='retry', conversation_id='chat', request_id='retry',
                        question='How does retrieval work?', status='completed', response_json='{}'))
        db.commit()
        assert not intent_active(db, 'topic', material)


def test_successful_retry_in_new_conversation_prevents_reanswering(research):
    from app.services.research_reading import enqueue_reading
    _, worker = research
    enable_reading(worker)
    with worker.database.sessions() as db:
        db.delete(db.get(Note, 'n1'))
        for cid in ('failed-chat', 'successful-chat'):
            db.add(ChatConversation(id=cid, kind='paper', paper_id='p1', context_key=cid))
        db.flush()
        db.add(ChatTurn(id='f', conversation_id='failed-chat', request_id='f',
                        question='How does retrieval work?', status='failed'))
        db.add(ChatTurn(id='s', conversation_id='successful-chat', request_id='s',
                        question='How does retrieval work?', status='completed', response_json='{}'))
        db.commit()
        assert enqueue_reading(db, db.get(ResearchScope, 'topic')) == []


def test_source_update_replaces_stale_reading_task_without_reviving_cancelled_question(research):
    from app.services.research_reading import enqueue_reading
    _, worker = research
    enable_reading(worker)
    with worker.database.sessions() as db:
        scope = db.get(ResearchScope, 'topic')
        first = enqueue_reading(db, scope)[0]
        first.status = 'superseded'
        db.get(PaperChunk, 'c1').content += ' A corrected account of retrieval.'
        db.commit()
        replacement = enqueue_reading(db, scope)[0]
        assert replacement.id != first.id


def test_investigation_can_expand_once_then_publish_with_current_source_ids(research):
    client, worker = research
    enable_reading(worker)
    with worker.database.sessions() as db:
        for i in range(8):
            db.add(PaperChunk(id=f'long-{i}', paper_id='p1', page=i+2, section='Detailed retrieval',
                content='A step of the detailed retrieval protocol. '+('Extra context. '*1000)))
        db.commit()
    class ExpandWriter(ReadingWriter):
        def _complete(self, system, user, **kwargs):
            result = super()._complete(system, user, **kwargs)
            if len(self.calls) == 1:
                return json.dumps({'read_more': [dict(paper_id='p1', sections=['Detailed retrieval'], reason='Need exact sequence')]})
            return result
    writer = ExpandWriter()
    worker.profiles.subscription_provider = lambda _: writer
    for _ in range(5):
        worker._next_scan = 0
        worker.process_next()
    task = client.get('/api/research/collections/topic/findings').json()['agenda']['tasks'][0]
    assert task['status'] == 'completed' and len(writer.calls) == 3
    assert writer.calls[1]['material']['coverage'][0]['included_chars'] > writer.calls[0]['material']['coverage'][0]['included_chars']
    with worker.database.sessions() as db:
        assert json.loads(db.get(ResearchTask, task['id']).checkpoint_json)['expanded']


def test_unsupported_expansion_cannot_read_other_papers_or_loop(research):
    from app.services.research_agenda import expand_material
    from app.services.research_reading import enqueue_reading
    import pytest
    _, worker = research
    enable_reading(worker)
    with worker.database.sessions() as db:
        material = json.loads(enqueue_reading(db, db.get(ResearchScope, 'topic'))[0].material_json)
        for request in ([dict(paper_id='p2', sections=['Method'])], [None],
                        [dict(paper_id='p1', sections=['Does not exist'])]):
            with pytest.raises(ValueError):
                expand_material(db, material, request)


def test_question_note_changes_do_not_invalidate_topic_round_but_research_notes_do(research):
    _, worker = research
    worker.scope('topic', ScopeUpdate(enabled=True, work_types=['essay', 'reading']))
    first = worker.enqueue('topic')
    with worker.database.sessions() as db:
        db.get(Note, 'n1').content = 'A new reading question'
        db.commit()
    assert worker.enqueue('topic')['id'] == first['id']
    with worker.database.sessions() as db:
        db.add(Note(id='interpretation', paper_id='p1', kind='note', content='A new research interpretation'))
        db.commit()
    assert worker.enqueue('topic')['id'] != first['id']


def test_reused_evidence_must_still_match_and_material_has_real_section_coverage(research):
    from app.models import ResearchFinding
    from app.services.research_agenda import investigation_material
    _, worker = research
    with worker.database.sessions() as db:
        for index in range(20):
            db.add(PaperChunk(id=f'appendix-{index}', paper_id='p1', page=index+2,
                section='Unrelated appendix', content='An unrelated calculation. ' * 300))
        db.add(ResearchFinding(id='old', collection_id='topic', identity='old', kind='gap',
            title='Memory retrieval', body='Useful prior interpretation.', next_step='Inspect the mechanism.',
            sources_json=json.dumps([dict(chunk_id='c1', paper_id='p1',
                quote='The agent stores experience in external memory.', text='STALE SNAPSHOT')]), model='fixture'))
        db.commit()
        brief = dict(kind='gap', title='Memory retrieval', question='How does retrieval work?',
            rationale='Understand the next action', paper_ids=['p1'], section_hints=['Method'], existing_id=None)
        material = investigation_material(db, 'topic', 'base', brief,
            dict(papers=[dict(id='p1', title='Memory mechanisms')], sources=[], coverage=[]))
        assert material['reused_evidence'][0]['finding_id'] == 'old'
        assert material['coverage'][0]['included_chars'] < material['coverage'][0]['total_chars']
        assert material['section_index'][0]['sections']
        db.get(PaperChunk, 'c1').content = 'The mechanism has changed.'
        db.commit()
        material = investigation_material(db, 'topic', 'base', brief,
            dict(papers=[dict(id='p1', title='Memory mechanisms')], sources=[], coverage=[]))
        assert material['reused_evidence'] == []
