import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Collection, CollectionPaper, Paper, PaperChunk
from app.providers.base import ProviderError
from app.providers.validation import canonical_quote


@pytest.fixture
def findings(client):
    from app.research_schemas import ResearchSettings, ScopeUpdate
    worker = client.app.state.research_worker
    worker.stop()
    with worker.database.sessions() as db:
        db.add_all([Collection(id='topic', name='Memory'), Collection(id='other', name='Other'),
                    Paper(id='p1', title='Agent A'), Paper(id='p2', title='Agent B')])
        db.flush()
        db.add_all([CollectionPaper(collection_id='topic', paper_id='p1'),
                    CollectionPaper(collection_id='topic', paper_id='p2'),
                    PaperChunk(id='c1', paper_id='p1', page=1, content='The agent stores observations and retrieves them before planning.'),
                    PaperChunk(id='c2', paper_id='p2', page=2, content='The agent uses function calls to retrieve earlier conversations.')])
        db.commit()
    worker.settings(ResearchSettings(enabled=True, profile_id='official', idle_seconds=0, calls_per_hour=18))
    worker.scope('topic', ScopeUpdate(enabled=True, focus='Memory control flow',
        work_types=['essay', 'connections', 'gaps', 'review', 'questions']))
    worker.profiles.public = lambda: {'profiles': [{'id': 'official', 'provider_kind': 'codex'}]}
    worker.profiles.codex.status = lambda **kw: {'authenticated': True, 'limits': [
        dict(name='primary', used_percent=10, window_minutes=300, resets_at=time.time()+300)]}
    return client, worker


def candidates():
    return {'findings': [
        {'kind': 'connection', 'title': '检索何时改变下一步行动？',
         'body': '两个系统都把历史取回当前决策，但一个用于计划，另一个用于连续查询。[1](#source-S1)[2](#source-S2)',
         'next_step': '比较一次查询返回后，两个系统下一次推理的输入。',
         'evidence': [{'source_id': 'S1', 'quote': 'The agent stores observations and retrieves them before planning.'},
                      {'source_id': 'S2', 'quote': 'The agent uses function calls to retrieve earlier conversations.'}]},
        {'kind': 'review', 'title': '存下历史后，模型什么时候能再次使用它？',
         'body': '历史必须被检索并放回当前推理。保存和下一步的计划通过检索连接。[1](#source-S1)',
         'next_step': '遮住答案，用一次具体对话解释检索的位置。',
         'evidence': [{'source_id': 'S1', 'quote': 'The agent stores observations and retrieves them before planning.'}]}
    ]}


class Finder:
    model = 'fixture'
    last_usage = {'input_tokens': 100, 'output_tokens': 50}
    def __init__(self):
        self.calls = []
        self.interrupt = False
    def _complete(self, system, user, **kw):
        self.calls.append((system, json.loads(user)))
        if self.interrupt:
            raise ProviderError('yield', 409, code='background_preempted')
        return json.dumps(candidates())


def test_findings_publish_only_after_review_and_resume_persisted_candidates(findings):
    client, worker = findings
    finder = Finder()
    worker.profiles.subscription_provider = lambda _: finder
    task = worker.enqueue('topic', kind='findings')
    assert worker.enqueue('topic', kind='findings')['id'] == task['id']
    worker.process_next()
    state = client.get('/api/research/collections/topic/findings').json()
    assert state['items'] == []
    assert state['task']['stage'] == 'assess'
    finder.interrupt = True
    worker.process_next()
    assert worker.findings('topic')['task']['status'] == 'paused'
    finder.interrupt = False
    worker.process_next()
    state = worker.findings('topic')
    assert len(state['items']) == 2
    assert state['task']['status'] == 'completed'
    assert len(finder.calls) == 3
    assert finder.calls[-1][1]['candidates']['findings'][0]['title'] == candidates()['findings'][0]['title']
    worker.process_next()
    assert len(finder.calls) == 3


def test_essay_and_findings_queues_do_not_supersede_each_other(findings):
    _, worker = findings
    essay = worker.enqueue('topic')
    batch = worker.enqueue('topic', kind='findings')
    assert essay['id'] != batch['id']
    assert worker.collection('topic')['task']['id'] == essay['id']
    assert worker.findings('topic')['task']['id'] == batch['id']
    assert all(t['status'] == 'queued' for t in worker.status()['tasks'])


@pytest.mark.parametrize('damage', ['quote', 'one_paper_connection', 'unselected_kind', 'foreign_id', 'unknown_citation'])
def test_findings_require_scoped_supported_evidence(findings, damage):
    from app.services.research_findings import verify_findings
    from app.services.research_materials import snapshot
    _, worker = findings
    with worker.database.sessions() as db:
        material, _ = snapshot(db, 'topic', 'Memory control flow', kind='findings',
            work_types=['connections', 'review'])
    data = candidates()
    if damage == 'quote': data['findings'][0]['evidence'][0]['quote'] = 'A fabricated unsupported quotation.'
    elif damage == 'one_paper_connection': data['findings'][0]['evidence'].pop()
    elif damage == 'unselected_kind': data['findings'][0]['kind'] = 'gap'
    elif damage == 'foreign_id': data['findings'][0]['existing_id'] = 'finding-from-another-collection'
    else: data['findings'][0]['body'] += '[3](#source-S999)'
    with pytest.raises(ValueError): verify_findings(data, material, [])


def test_canonical_quote_matches_pdf_ligatures_and_line_break_hyphenation():
    source = 'A state-of-\nthe-art method improves veriﬁcation quality.'

    matched = canonical_quote(source, 'state-of-the-art method improves verification quality.',
                              allow_pdf_formatting=True)

    assert matched == 'state-of-\nthe-art method improves veriﬁcation quality.'


def test_replayed_discovery_preserves_user_decisions_and_revision_history(findings):
    from app.services.research_findings import publish_findings, verify_findings
    from app.services.research_materials import snapshot
    from app.models import ResearchTask, ResearchFindingRevision
    client, worker = findings
    finder = Finder()
    worker.profiles.subscription_provider = lambda _: finder
    first = worker.enqueue('topic', kind='findings')
    for _ in range(2): worker.process_next()
    item = next(i for i in worker.findings('topic')['items'] if i['kind'] == 'connection')
    response = client.patch(f'/api/research/findings/{item["id"]}', json={'action': 'dismiss'})
    assert response.status_code == 200
    with worker.database.sessions() as db:
        task = db.get(ResearchTask, first['id'])
        material = json.loads(task.material_json)
        data = candidates()
        data['findings'][0].update(existing_id=item['id'], body='补充运行条件。[1](#source-S1)[2](#source-S2)')
        verified = verify_findings(data, material, worker.findings('topic')['items'])
        publish_findings(db, task, verified, 'fixture')
        publish_findings(db, task, verified, 'fixture')
        db.commit()
        assert len(db.scalars(select(ResearchFindingRevision).where(ResearchFindingRevision.finding_id == item['id'])).all()) == 2
    after = worker.findings('topic')['items']
    assert len(after) == 2
    assert next(i for i in after if i['id'] == item['id'])['status'] == 'dismissed'
    assert client.get(f'/api/research/findings/{item["id"]}/history').json()['revisions'][0]['body'].startswith('补充')


def test_review_schedule_persists_without_new_model_calls(findings):
    client, worker = findings
    finder = Finder()
    worker.profiles.subscription_provider = lambda _: finder
    worker.enqueue('topic', kind='findings')
    for _ in range(2): worker.process_next()
    item = next(i for i in worker.findings('topic')['items'] if i['kind'] == 'review')
    answer = client.patch(f'/api/research/findings/{item["id"]}', json={'action': 'remembered'}).json()
    assert answer['review_count'] == 1
    assert datetime.fromisoformat(answer['due_at']) > datetime.now(timezone.utc) + timedelta(hours=20)
    assert worker.findings('topic')['due_count'] == 0
    again = client.patch(f'/api/research/findings/{item["id"]}', json={'action': 'again'}).json()
    assert again['review_count'] == 0
    assert len(finder.calls) == 2
    assert client.patch('/api/research/findings/missing', json={'action': 'keep'}).status_code == 404


def test_empty_review_finishes_without_fabricating_findings(findings):
    _, worker = findings
    finder = Finder()
    finder._complete = lambda *args, **kw: json.dumps({'findings': []})
    worker.profiles.subscription_provider = lambda _: finder
    worker.enqueue('topic', kind='findings')
    for _ in range(2): worker.process_next()
    assert worker.findings('topic')['task']['status'] == 'completed'
    assert worker.findings('topic')['items'] == []


def test_scope_choices_cancel_stale_work_and_do_not_change_essay_fingerprint(findings):
    from app.research_schemas import ScopeUpdate
    _, worker = findings
    essay = worker.enqueue('topic')
    job = worker.enqueue('topic', kind='findings')
    worker.scope('topic', ScopeUpdate(enabled=True, focus='Memory control flow', work_types=['essay', 'review']))
    assert worker.enqueue('topic')['id'] == essay['id']
    new = worker.enqueue('topic', kind='findings')
    assert new['id'] != job['id']
    assert next(t for t in worker.status()['tasks'] if t['id'] == job['id'])['status'] == 'superseded'


def test_findings_rename_reuses_identity_and_does_not_reset_review_decision(findings):
    from app.services.research_findings import publish_findings, verify_findings
    from app.models import ResearchTask
    client, worker = findings
    worker.profiles.subscription_provider = lambda _: Finder()
    task = worker.enqueue('topic', kind='findings')
    for _ in range(2): worker.process_next()
    item = next(i for i in worker.findings('topic')['items'] if i['kind'] == 'review')
    client.patch(f'/api/research/findings/{item["id"]}', json={'action': 'remembered'})
    with worker.database.sessions() as db:
        stored = db.get(ResearchTask, task['id'])
        data = {'findings': [candidates()['findings'][1]]}
        data['findings'][0].update(title='一次检索如何把历史带回上下文？', existing_id=item['id'])
        verified = verify_findings(data, json.loads(stored.material_json), worker.findings('topic')['items'])
        publish_findings(db, stored, verified, 'fixture')
        db.commit()
        # Replayed output can omit the update ID and still find the renamed identity.
        verified[0]['existing_id'] = None
        publish_findings(db, stored, verified, 'fixture')
        db.commit()
    rows = worker.findings('topic')['items']
    assert len(rows) == 2
    assert next(i for i in rows if i['id'] == item['id'])['review_count'] == 1


def test_identical_explanation_with_paraphrased_title_reuses_dismissed_item(findings):
    from app.services.research_findings import publish_findings, verify_findings
    from app.models import ResearchTask
    client, worker = findings
    worker.profiles.subscription_provider = lambda _: Finder()
    task = worker.enqueue('topic', kind='findings')
    for _ in range(2): worker.process_next()
    item = next(i for i in worker.findings('topic')['items'] if i['kind'] == 'review')
    client.patch(f'/api/research/findings/{item["id"]}', json={'action': 'dismiss'})
    with worker.database.sessions() as db:
        stored = db.get(ResearchTask, task['id'])
        data = {'findings': [candidates()['findings'][1]]}
        data['findings'][0]['title'] = '改换一个问法：什么时候又能用到保存的历史？'
        verified = verify_findings(data, json.loads(stored.material_json), worker.findings('topic')['items'])
        publish_findings(db, stored, verified, 'fixture')
        db.commit()
    rows = worker.findings('topic')['items']
    assert len(rows) == 2
    assert next(i for i in rows if i['kind'] == 'review')['status'] == 'dismissed'


def test_same_batch_cannot_publish_renamed_copies(findings):
    from copy import deepcopy
    from app.services.research_findings import verify_findings
    from app.services.research_materials import snapshot
    _, worker = findings
    with worker.database.sessions() as db:
        material, _ = snapshot(db, 'topic', '', kind='findings', work_types=['review'])
    item = candidates()['findings'][1]
    renamed = deepcopy(item)
    renamed['title'] = '同一个答案的另一种标题'
    with pytest.raises(ValueError, match='重复'):
        verify_findings({'findings': [item, renamed]}, material, [])


def test_duplicate_matching_preserves_mathematical_operators(findings):
    from copy import deepcopy
    from app.services.research_findings import verify_findings
    from app.services.research_materials import snapshot
    _, worker = findings
    with worker.database.sessions() as db:
        material, _ = snapshot(db, 'topic', '', kind='findings', work_types=['review'])
    first = candidates()['findings'][1]
    second = deepcopy(first)
    first.update(title='何时 x 大于零？', body='当 x > 0 时，系统触发检索。')
    second.update(title='何时 x 小于零？', body='当 x < 0 时，系统触发检索。')
    assert len(verify_findings({'findings': [first, second]}, material, [])) == 2


def test_rejected_output_keeps_usage_and_failure_reason_after_recovery(findings):
    from copy import deepcopy
    _, worker = findings
    finder = Finder()
    bad = deepcopy(candidates())
    bad['findings'][0]['evidence'][0]['quote'] = 'This is an invented statement outside the source.'
    finder._complete = lambda *args, **kw: json.dumps(bad)
    worker.profiles.subscription_provider = lambda _: finder
    worker.enqueue('topic', kind='findings')
    worker.process_next()
    task = worker.findings('topic')['task']
    assert task['usage']['events'][-1]['code'] == 'validation'
    assert '引文' in task['usage']['events'][-1]['message']
    assert task['usage']['input_tokens'] == 100
    finder._complete = lambda *args, **kw: json.dumps(candidates())
    worker._retry_at = 0
    for _ in range(2): worker.process_next()
    task = worker.findings('topic')['task']
    assert task['status'] == 'completed'
    assert task['error'] is None
    assert task['usage']['events'][0]['code'] == 'validation'
    assert task['usage']['input_tokens'] == 300
