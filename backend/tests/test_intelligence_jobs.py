from __future__ import annotations

import json
import fitz
import httpx
import pytest
from sqlalchemy import select
from app.providers.base import ProviderError


class FailingProvider:
    name = 'TestRemote'
    mode = 'remote'
    configured = True
    base_url = 'https://model.example'
    model = 'test'
    wire_api = 'responses'
    reasoning_effort = 'high'
    response_model = None
    last_usage = {}
    def complete_json(self, *args, **kwargs):
        raise ProviderError('Safe model failure')


def import_paper(client, analyze=False):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 50), 'The method retrieves 71 of 100 correct passages.')
        data = doc.tobytes()
    response = client.post('/api/papers/import', files={'file': ('paper.pdf', data)}, data={'analyze': str(analyze).lower()})
    assert response.status_code == 201
    return response.json()


def test_opt_out_import_is_unanalyzed_and_queues_nothing(client):
    paper = import_paper(client)
    assert paper['analysis']['mode'] == 'extractive'
    assert paper['intelligence_status'] == 'unanalyzed'
    assert client.get('/api/intelligence/tasks').json() == {'tasks': []}
    assert client.get('/api/intelligence/overview').json()['unanalyzed'] == 1


def test_opt_in_deduplicates_and_cancel_preserves_ready_analysis(client, monkeypatch):
    client.app.state.intelligence_worker.stop()
    provider = FailingProvider()
    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: provider)
    monkeypatch.setattr('app.api.intelligence.get_model_provider', lambda: provider)
    paper = import_paper(client, analyze=True)
    assert paper['intelligence_status'] == 'queued'
    task = paper['intelligence_task']
    queued = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id'], paper['id']]}).json()['tasks']
    assert len(queued) == 1 and queued[0]['id'] == task['id']
    cancelled = client.post(f"/api/intelligence/tasks/{task['id']}/cancel")
    assert cancelled.json()['status'] == 'cancelled'
    after = client.get(f"/api/papers/{paper['id']}").json()
    assert after['analysis'] == paper['analysis']
    assert after['intelligence_status'] == 'cancelled'
    assert client.app.state.intelligence_worker.process_next(provider) is False


def test_failure_and_retry_leave_existing_card_intact(client, monkeypatch):
    client.app.state.intelligence_worker.stop()
    provider = FailingProvider()
    monkeypatch.setattr('app.api.intelligence.get_model_provider', lambda: provider)
    paper = import_paper(client)
    first = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']]}).json()['tasks'][0]
    assert client.app.state.intelligence_worker.process_next(provider) is True
    after = client.get(f"/api/papers/{paper['id']}").json()
    assert after['analysis'] == paper['analysis'] and after['evidence'] == paper['evidence']
    assert after['intelligence_status'] == 'failed'
    assert after['intelligence_task']['error'] == 'Safe model failure'
    second = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']]}).json()['tasks'][0]
    assert second['id'] != first['id']
    assert second['status'] == 'queued'


def test_restart_recovers_running_task_without_erasing_old_analysis(client, monkeypatch):
    from app.models import IntelligenceTask, Paper
    from app.services.intelligence import recover_interrupted
    client.app.state.intelligence_worker.stop()
    monkeypatch.setattr('app.api.intelligence.get_model_provider', lambda: FailingProvider())
    paper = import_paper(client)
    task = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']]}).json()['tasks'][0]
    db = client.app.state.database
    with db.sessions() as session:
        row = session.get(IntelligenceTask, task['id'])
        row.status, row.phase = 'running', 'extract'
        session.get(Paper, paper['id']).intelligence_status = 'running'
        session.commit()
    recover_interrupted(db)
    with db.sessions() as session:
        assert session.get(IntelligenceTask, task['id']).status == 'queued'
        assert session.get(Paper, paper['id']).intelligence_status == 'queued'
    assert client.get(f"/api/papers/{paper['id']}").json()['analysis'] == paper['analysis']


def test_queue_requires_remote_and_valid_paper_scope(client):
    paper = import_paper(client)
    response = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']]})
    assert response.status_code == 409
    assert client.get('/api/intelligence/tasks').json()['tasks'] == []


def test_completed_result_is_invalidated_by_changed_model(client, monkeypatch):
    from app.models import IntelligenceTask, Paper
    from app.providers.harness import analysis_fingerprint
    client.app.state.intelligence_worker.stop()
    provider = FailingProvider()
    monkeypatch.setattr('app.api.intelligence.get_model_provider', lambda: provider)
    paper = import_paper(client)
    task = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']]}).json()['tasks'][0]
    with client.app.state.database.sessions() as session:
        row = session.get(Paper, paper['id'])
        row.intelligence_status = 'completed'
        row.intelligence_report_json = json.dumps({'result_fingerprint': analysis_fingerprint(provider, list(row.chunks))})
        session.get(IntelligenceTask, task['id']).status = 'completed'
        session.commit()
    same = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']]}).json()['tasks'][0]
    assert same['id'] == task['id']
    provider.model = 'changed-model'
    changed = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']]}).json()['tasks'][0]
    assert changed['id'] != task['id'] and changed['status'] == 'queued'


def test_legacy_analyze_api_uses_full_paper_stages_and_same_ready_contract(client, monkeypatch):
    from app.models import PaperChunk
    from app.providers.openai_compatible import OpenAICompatibleProvider
    client.app.state.intelligence_worker.stop()
    paper = import_paper(client)
    with client.app.state.database.sessions() as session:
        for index in range(30):
            session.add(PaperChunk(id=f'late-{index:03d}', paper_id=paper['id'], page=index + 2, section='Results', content=f'Unique result on page {index + 2}. ' + 'x' * 1000))
        session.commit()
    windows = []
    def respond(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        if payload.get('stage') == 'review_card_science':
            answer = {'items': [{'field': item['field'], 'decision': 'supported'} for item in payload['items']]}
        elif 'chunks' in payload:
            windows.append(payload['chunks'])
            part = payload['chunks'][-1]
            answer = {'facts': [{'content': 'A verified result.', 'citations': [{'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content'][:60]}]}]}
        else:
            answer = {'main_results': {'content': 'A verified late-page result.', 'citation_ids': payload['facts'][-1]['citation_ids']}}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', transport=httpx.MockTransport(respond))
    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: provider)
    result = client.post(f"/api/papers/{paper['id']}/analyze")
    assert result.status_code == 200
    assert result.json()['analysis']['findings'] == 'A verified late-page result.'
    assert result.json()['intelligence_status'] == 'completed'
    assert len(windows) == 2
    assert windows[-1][-1]['page'] == 31


def test_cancellation_during_response_keeps_call_usage_and_old_card(client, monkeypatch):
    import threading
    from app.providers.openai_compatible import OpenAICompatibleProvider
    client.app.state.intelligence_worker.stop()
    paper = import_paper(client)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def respond(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        calls.append(payload)
        entered.set()
        assert release.wait(5)
        part = payload['chunks'][0]
        answer = {'facts': [{'content': 'Supported.', 'citations': [{'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content']}]}]}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}], 'usage': {'prompt_tokens': 25, 'completion_tokens': 9}})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', transport=httpx.MockTransport(respond))
    monkeypatch.setattr('app.api.intelligence.get_model_provider', lambda: provider)
    task = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']]}).json()['tasks'][0]
    thread = threading.Thread(target=client.app.state.intelligence_worker.process_next, args=(provider,))
    thread.start()
    assert entered.wait(5)
    assert client.post(f"/api/intelligence/tasks/{task['id']}/cancel").json()['status'] == 'cancelled'
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    after = client.get(f"/api/papers/{paper['id']}").json()
    assert after['analysis'] == paper['analysis']
    assert after['intelligence_status'] == 'cancelled'
    assert after['intelligence_task']['report']['usage']['input_tokens'] == 25
    assert len(calls) == 1


def test_stale_worker_cannot_change_recovered_task_progress(client, monkeypatch):
    from app.models import IntelligenceTask
    client.app.state.intelligence_worker.stop()
    monkeypatch.setattr('app.api.intelligence.get_model_provider', lambda: FailingProvider())
    paper = import_paper(client)
    task = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']]}).json()['tasks'][0]
    with client.app.state.database.sessions() as session:
        row = session.get(IntelligenceTask, task['id'])
        row.status, row.phase = 'running', 'synthesize'
        row.run_token = 'new-lease'
        row.report_json = '{"owner":"new"}'
        session.commit()
    client.app.state.intelligence_worker._progress(task['id'], 'old-lease', 'extract', 0, 2, {'owner': 'old'})
    current = client.get('/api/intelligence/tasks').json()['tasks'][0]
    assert current['phase'] == 'synthesize'
    assert current['report'] == {'owner': 'new'}


@pytest.mark.parametrize('prior_remote', [True, False])
def test_partial_attempt_retains_previous_remote_card_but_can_publish_first_card(client, monkeypatch, prior_remote):
    from app.models import Paper
    client.app.state.intelligence_worker.stop()
    paper = import_paper(client)
    if prior_remote:
        with client.app.state.database.sessions() as session:
            existing = session.get(Paper, paper['id'])
            existing.analysis.mode = 'remote'
            existing.intelligence_status = 'completed'
            existing.intelligence_report_json = '{"prior":"ready"}'
            session.commit()
        paper = client.get(f"/api/papers/{paper['id']}").json()
    class PartialProvider(FailingProvider):
        def complete_json(self, system, payload, **kwargs):
            if 'chunks' in payload:
                part = payload['chunks'][0]
                return {'facts': [{'content': 'New supported method.', 'citations': [
                    {'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content']}]}]}
            return {'method': {'content': 'New supported method.', 'citation_ids': payload['facts'][0]['citation_ids']},
                'main_results': {'content': 'Rejected result.', 'citations': [
                    {'part_id': 'missing', 'chunk_id': 'missing', 'source_text': 'Invented quote.'}]}}
    provider = PartialProvider()
    monkeypatch.setattr('app.api.intelligence.get_model_provider', lambda: provider)
    task = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']], 'force': True}).json()['tasks'][0]
    assert client.app.state.intelligence_worker.process_next(provider)
    after = client.get(f"/api/papers/{paper['id']}").json()
    assert after['intelligence_status'] == 'partial'
    attempt = after['intelligence_task']
    assert attempt['id'] == task['id'] and attempt['status'] == 'partial'
    assert attempt['report']['partial'] and attempt['report']['invalid_entries'] == 1
    if prior_remote:
        assert after['analysis'] == paper['analysis']
        assert after['evidence'] == paper['evidence']
        assert after['intelligence_report'] == paper['intelligence_report']
        assert after['intelligence_analyzed_at'] == paper['intelligence_analyzed_at']
    else:
        assert after['analysis']['method'] == 'New supported method.'
        assert after['analysis']['mode'] == 'remote'
    assert attempt['report']['retained_previous_card'] is prior_remote


def test_prompt_change_during_job_preserves_previous_ready_result(client, monkeypatch, tmp_path):
    import app.providers.harness as harness
    client.app.state.intelligence_worker.stop()
    paper = import_paper(client)
    prompt_dir = tmp_path / 'job-prompts'
    prompt_dir.mkdir()
    for name in harness.PROMPT_NAMES:
        (prompt_dir / name).write_text((harness.PROMPTS_DIR / name).read_text(encoding='utf-8-sig'), encoding='utf-8')
    monkeypatch.setattr(harness, 'PROMPTS_DIR', prompt_dir)
    class ChangingPromptProvider(FailingProvider):
        def complete_json(self, system, payload, **kwargs):
            if 'chunks' in payload:
                (prompt_dir / 'paper_reduce.txt').write_text('Changed reduction policy during this job.', encoding='utf-8')
                part = payload['chunks'][0]
                return {'facts': [{'content': 'Supported method.', 'citations': [{'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content']}]}]}
            return {'method': {'content': 'Supported method.', 'citation_ids': payload['facts'][0]['citation_ids']}}
    provider = ChangingPromptProvider()
    monkeypatch.setattr('app.api.intelligence.get_model_provider', lambda: provider)
    client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']]})
    assert client.app.state.intelligence_worker.process_next(provider)
    after = client.get(f"/api/papers/{paper['id']}").json()
    assert after['intelligence_status'] == 'failed'
    assert after['analysis'] == paper['analysis'] and after['evidence'] == paper['evidence']
