import json

import pytest
from sqlalchemy import select

from app.models import Paper, PaperChunk


def add_paper(client, identity='paper-one'):
    with client.app.state.database.sessions() as session:
        session.add(Paper(id=identity, title='A paper'))
        session.flush()
        session.add(PaperChunk(id='chunk-' + identity, paper_id=identity, page=2,
            content='The verifier selects valid reasoning traces.', bbox_json='[30,40,200,80]', page_width=600, page_height=800))
        session.commit()


def test_paper_answers_are_saved_with_sources_and_survive_new_database_connection(client):
    add_paper(client)
    result = client.post('/api/papers/paper-one/ask', json={'question': 'What does the verifier select?', 'request_id': 'request-one'})
    assert result.status_code == 200
    answer = result.json()
    assert answer.get('conversation_id'), 'Successful answers must identify their saved conversation'
    history = client.get('/api/conversations/' + answer['conversation_id']).json()
    turn = history['turns'][0]
    assert turn['question'] == 'What does the verifier select?'
    assert turn['status'] == 'completed'
    assert turn['response']['answer'] == answer['answer']
    assert turn['response']['citations'] == answer['citations']
    from app.db import Database
    from app.services.conversations import read_conversation
    reopened = Database(client.app.state.database.url)
    try:
        assert read_conversation(reopened, answer['conversation_id'])['turns'][0]['response'] == turn['response']
    finally:
        reopened.engine.dispose()


def test_same_request_replay_does_not_repeat_model_work_or_duplicate_history(client, monkeypatch):
    add_paper(client)
    from app.api import papers
    original = papers.get_model_provider
    calls = []
    def provider():
        calls.append(1)
        return original()
    monkeypatch.setattr(papers, 'get_model_provider', provider)
    payload = {'question': 'What does the verifier select?', 'request_id': 'same-request'}
    first = client.post('/api/papers/paper-one/ask', json=payload).json()
    second = client.post('/api/papers/paper-one/ask', json=payload).json()
    assert first.get('conversation_id') and first == second
    assert len(calls) == 1
    assert len(client.get('/api/conversations/' + first['conversation_id']).json()['turns']) == 1
    changed = client.post('/api/papers/paper-one/ask', json={**payload, 'question': 'Different question'})
    assert changed.status_code == 409


def test_explanations_restore_only_their_paper_and_selected_context(client):
    add_paper(client)
    add_paper(client, 'paper-two')
    context = {'page': 2, 'chunk_id': 'chunk-paper-one', 'selected_text': 'verifier', 'visual': False}
    result = client.post('/api/papers/paper-one/explain', json={
        'question': 'What is this?', 'chunk_id': context['chunk_id'], 'selected_text': 'verifier'})
    assert result.status_code == 200
    conversation_id = result.json().get('conversation_id')
    assert conversation_id
    matches = client.get('/api/conversations', params={'kind': 'explanation', 'paper_id': 'paper-one', 'context': json.dumps(context)}).json()['items']
    assert [item['id'] for item in matches] == [conversation_id]
    assert client.get('/api/conversations', params={'kind': 'explanation', 'paper_id': 'paper-two'}).json()['items'] == []
    context['selected_text'] = 'reasoning'
    assert client.get('/api/conversations', params={'kind': 'explanation', 'paper_id': 'paper-one', 'context': json.dumps(context)}).json()['items'] == []


def test_librarian_questions_persist_complete_answers_and_refuse_cross_scope_thread(client, monkeypatch):
    add_paper(client)
    add_paper(client, 'paper-two')
    from app.api import librarian
    from app.library_schemas import LibraryAnswer
    calls = []
    def answer(database, provider, payload):
        calls.append(payload.question)
        return LibraryAnswer(answer='## A saved answer\n\nWith a table.', items=[], citations=[], provider='Fixture', mode='remote',
            insufficient_evidence=False, limitations=[], retrieved_paper_ids=payload.paper_ids or [], queries=[], coverage={}, usage={}, cached=False)
    monkeypatch.setattr(librarian, 'answer_library', answer)
    result = client.post('/api/intelligence/ask', json={'question': 'Explain the paper', 'paper_ids': ['paper-one'], 'conversation_kind': 'paper'})
    assert result.status_code == 200
    conversation_id = result.json().get('conversation_id')
    assert conversation_id
    saved = client.get('/api/conversations/' + conversation_id).json()
    assert saved['kind'] == 'paper' and saved['paper_id'] == 'paper-one'
    assert saved['turns'][0]['response']['answer'].startswith('## A saved answer')
    mismatch = client.post('/api/intelligence/ask', json={'question': 'Wrong scope', 'paper_ids': ['paper-two'],
        'conversation_kind': 'paper', 'conversation_id': conversation_id})
    assert mismatch.status_code == 409 and len(calls) == 1
    # Existing clients may narrow a collection to an explicit subset of papers.
    combined = client.post('/api/intelligence/ask', json={'question': 'A collection subset',
        'paper_ids': ['paper-one'], 'collection_id': 'collection-one'})
    assert combined.status_code == 200
    saved_scope = client.get('/api/conversations/' + combined.json()['conversation_id']).json()['context']
    assert saved_scope == {'paper_ids': ['paper-one'], 'collection_id': 'collection-one'}


def test_failed_questions_remain_visible_and_restart_marks_unfinished_work(client, monkeypatch):
    add_paper(client)
    from app.api import librarian
    from app.providers.base import ProviderError
    def fail(database, provider, payload):
        raise ProviderError('A provider timeout', 504)
    monkeypatch.setattr(librarian, 'answer_library', fail)
    assert client.post('/api/intelligence/ask', json={'question': 'Keep this question', 'paper_ids': ['paper-one']}).status_code == 504
    conversations = client.get('/api/conversations', params={'kind': 'librarian'}).json()['items']
    assert len(conversations) == 1
    saved = client.get('/api/conversations/' + conversations[0]['id']).json()['turns'][0]
    assert saved['question'] == 'Keep this question' and saved['status'] == 'failed'
    assert 'timeout' in saved['error']
    from app.models import ChatTurn
    from app.services.conversations import recover_interrupted
    with client.app.state.database.sessions() as session:
        session.add(ChatTurn(id='interrupted-turn', conversation_id=conversations[0]['id'], request_id='pending-request',
            question='Interrupted question', status='running'))
        session.commit()
    recover_interrupted(client.app.state.database)
    saved = client.get('/api/conversations/' + conversations[0]['id']).json()['turns'][-1]
    assert saved['status'] == 'interrupted' and saved['question'] == 'Interrupted question'


def test_new_conversation_does_not_remove_old_history_and_deleted_paper_cascades(client):
    add_paper(client)
    first = client.post('/api/papers/paper-one/ask', json={'question': 'First question'}).json()
    created = client.post('/api/conversations', json={'kind': 'paper', 'paper_id': 'paper-one', 'context': {}})
    assert created.status_code == 201
    newer = created.json()
    assert newer['id'] != first.get('conversation_id')
    assert len(client.get('/api/conversations/' + first['conversation_id']).json()['turns']) == 1
    assert client.get('/api/conversations/' + newer['id']).json()['turns'] == []
    from sqlalchemy import delete
    with client.app.state.database.sessions() as session:
        session.execute(delete(Paper).where(Paper.id == 'paper-one'))
        session.commit()
    assert client.get('/api/conversations/' + first['conversation_id']).status_code == 404


def test_unicode_context_and_empty_selected_scope_do_not_lose_history(client):
    add_paper(client)
    context = {'page': 2, 'chunk_id': 'chunk-paper-one', 'selected_text': '科研' * 2000, 'visual': False}
    created = client.post('/api/conversations', json={'kind': 'explanation', 'paper_id': 'paper-one', 'context': context})
    assert created.status_code == 201
    restored = client.get('/api/conversations', params={'kind': 'explanation', 'paper_id': 'paper-one', 'context': json.dumps(context, ensure_ascii=False)})
    assert restored.status_code == 200 and restored.json()['items'][0]['id'] == created.json()['id']
    global_chat = client.post('/api/conversations', json={'kind': 'librarian', 'context': {}}).json()
    selected_chat = client.post('/api/conversations', json={'kind': 'librarian', 'context': {'paper_ids': []}}).json()
    selected = client.get('/api/conversations', params={'kind': 'librarian', 'context': '{"paper_ids":[]}'}).json()
    assert [item['id'] for item in selected['items']] == [selected_chat['id']]
    assert selected_chat['id'] != global_chat['id']


def test_visual_equation_context_survives_conversation_normalization():
    from app.services.conversations import normalize_context

    normalized = normalize_context('explanation', {
        'page': 4, 'selected_text': 'E = mc^2', 'visual': True,
        'visual_kind': 'equation', 'visual_label': 'Equation (3)', 'bbox': [10, 20, 90, 55],
    })

    assert normalized['visual_kind'] == 'equation'
    assert normalized['visual_label'] == 'Equation (3)'


@pytest.mark.parametrize('kind,context', [
    ('explanation', {'selected_text': ['bad']}), ('explanation', {'page': 'bad'}),
    ('librarian', {'paper_ids': [None]}), ('librarian', {'paper_ids': 'paper-one'}),
    ('librarian', {'collection_id': []}),
])
def test_invalid_context_is_rejected_without_server_error(client, kind, context):
    add_paper(client)
    assert client.post('/api/conversations', json={'kind': kind, 'paper_id': 'paper-one', 'context': context}).status_code == 422
    assert client.get('/api/conversations', params={'kind': kind, 'context': json.dumps(context)}).status_code == 422


def test_question_is_visible_while_provider_runs_and_parallel_submission_is_refused(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.api import papers
    entered, release = Event(), Event()
    add_paper(client)
    original = papers._ask_response
    def delayed(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(papers, '_ask_response', delayed)
    conversation = client.post('/api/conversations', json={'kind': 'paper', 'paper_id': 'paper-one'}).json()
    payload = {'question': 'What does the verifier select?', 'conversation_id': conversation['id'], 'request_id': 'pending-request'}
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.post, '/api/papers/paper-one/ask', json=payload)
        try:
            assert entered.wait(10)
            turn = client.get('/api/conversations/' + conversation['id']).json()['turns'][0]
            assert turn['status'] == 'running' and turn['question'] == payload['question']
            summary = client.get('/api/conversations', params={'kind': 'paper', 'paper_id': 'paper-one'}).json()['items'][0]
            assert summary['latest_status'] == 'running'
            assert client.post('/api/papers/paper-one/ask', json=payload).status_code == 409
            assert client.post('/api/papers/paper-one/ask', json={**payload, 'request_id': 'second-request'}).status_code == 409
        finally:
            release.set()
        assert future.result().status_code == 200
    assert len(client.get('/api/conversations/' + conversation['id']).json()['turns']) == 1
    assert client.get('/api/conversations', params={'kind': 'paper', 'paper_id': 'paper-one'}).json()['items'][0]['latest_status'] == 'completed'


def test_translated_selection_display_context_survives_without_changing_evidence_identity(client):
    add_paper(client)
    context = {'page': 2, 'chunk_id': 'chunk-paper-one', 'selected_text': 'verifier', 'visual': False}
    created = client.post('/api/conversations', json={'kind': 'explanation', 'paper_id': 'paper-one',
        'context': {**context, 'translated_text': '这里的验证器'}}).json()
    assert created['context']['translated_text'] == '这里的验证器'
    result = client.post('/api/papers/paper-one/explain', json={'conversation_id': created['id'],
        'question': 'What is this?', 'chunk_id': context['chunk_id'], 'selected_text': 'verifier',
        'translated_text': '这里的验证器'})
    assert result.status_code == 200
    matches = client.get('/api/conversations', params={'kind': 'explanation', 'paper_id': 'paper-one',
        'context': json.dumps(context)}).json()['items']
    assert matches[0]['id'] == created['id']
    assert matches[0]['context']['translated_text'] == '这里的验证器'


def test_explanation_can_archive_translated_context_without_a_prior_create(client):
    add_paper(client)
    result = client.post('/api/papers/paper-one/explain', json={
        'question': 'What is this?', 'page': 2, 'chunk_id': 'chunk-paper-one',
        'selected_text': 'verifier', 'translated_text': '这里的验证器'})
    assert result.status_code == 200
    saved = client.get('/api/conversations/' + result.json()['conversation_id']).json()
    assert saved['context']['translated_text'] == '这里的验证器'
    assert saved['context']['selected_text'] == 'verifier'
