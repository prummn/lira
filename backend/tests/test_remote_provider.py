from __future__ import annotations
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.models import PaperChunk
from app.providers import get_model_provider


def sample_chunk() -> PaperChunk:
    return PaperChunk(id='real-chunk', paper_id='real-paper', page=2, section='3 Results', content='The method retrieves\n71 of 100 correct passages.', bbox_json='[10,20,300,70]', page_width=600, page_height=800)


def provider_for(content: str | dict):
    from app.providers.openai_compatible import OpenAICompatibleProvider
    message = content if isinstance(content,str) else json.dumps(content)
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url == 'https://model.example/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer test-secret'
        payload = json.loads(request.content)
        assert payload['model'] == 'test-model'
        return httpx.Response(200,json={'choices':[{'message':{'content':message}}], 'model':'test-model-2026'})
    return OpenAICompatibleProvider(api_key='test-secret', base_url='https://model.example/v1', model='test-model', transport=httpx.MockTransport(respond))


def test_env_configuration_is_precise_and_settings_never_echo_secret(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_model_provider().name == 'MockProvider'
    monkeypatch.setenv('PAPER_READER_MODEL_API_KEY','private-key-do-not-echo')
    monkeypatch.setenv('PAPER_READER_MODEL_NAME','chosen-model')
    settings = client.get('/api/settings')
    assert settings.json()['configured'] is True
    assert settings.json()['provider'] == 'OpenAICompatibleProvider'
    assert settings.json()['mode'] == 'remote'
    assert settings.json()['translation_available'] is True
    assert 'private-key-do-not-echo' not in settings.text


def test_generic_host_api_key_does_not_enable_remote_and_ask_stays_local(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('OPENAI_API_KEY', 'unrelated-host-key-do-not-echo')

    def reject_request(*args, **kwargs):
        raise AssertionError('A generic host key alone must never enable remote model requests')

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', reject_request)
    settings = client.get('/api/settings')
    assert settings.status_code == 200
    assert settings.json()['provider'] == 'MockProvider'
    assert settings.json()['mode'] == 'extractive'
    assert settings.json()['configured'] is False
    assert settings.json()['translation_available'] is False
    assert 'unrelated-host-key-do-not-echo' not in settings.text
    paper = import_fixture(client)
    answer = client.post(f"/api/papers/{paper['id']}/ask", json={'question': 'What are the retrieval results?'})
    assert answer.status_code == 200
    assert answer.json()['provider'] == 'MockProvider'
    assert answer.json()['mode'] == 'extractive'
    assert answer.json()['citations']
    assert answer.json()['citations'][0]['source_text'] in paper['chunks'][0]['content']


def test_application_specific_key_alone_enables_remote(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PAPER_READER_MODEL_API_KEY', 'application-key-do-not-echo')
    settings = client.get('/api/settings')
    assert settings.status_code == 200
    assert settings.json()['provider'] == 'OpenAICompatibleProvider'
    assert settings.json()['configured'] is True
    assert settings.json()['mode'] == 'remote'
    assert settings.json()['model'] == 'gpt-4.1-mini'
    assert 'application-key-do-not-echo' not in settings.text


@pytest.mark.parametrize('setting,value', [('PAPER_READER_MODEL_BASE_URL', 'https://model.example/v1'), ('PAPER_READER_MODEL_NAME', 'explicit-model')])
def test_generic_key_is_a_fallback_only_with_application_model_configuration(client: TestClient, monkeypatch: pytest.MonkeyPatch, setting: str, value: str) -> None:
    monkeypatch.setenv('OPENAI_API_KEY', 'generic-fallback-key-do-not-echo')
    monkeypatch.setenv(setting, value)
    settings = client.get('/api/settings')
    assert settings.status_code == 200
    assert settings.json()['provider'] == 'OpenAICompatibleProvider'
    assert settings.json()['configured'] is True
    assert settings.json()['mode'] == 'remote'
    assert settings.json()['translation_available'] is True
    assert 'generic-fallback-key-do-not-echo' not in settings.text


def test_remote_analysis_uses_real_quote_geometry_and_summary_type() -> None:
    chunk = sample_chunk()
    provider = provider_for({'findings': {'content':'The retrieval evaluation reports 71% correct passages.', 'citations':[{'chunk_id':chunk.id,'source_text':'retrieves 71 of 100 correct passages.','page':999,'bbox':[0,0,1,1]}]}})
    result = provider.analyze([chunk])
    assert result.findings == 'The retrieval evaluation reports 71% correct passages.'
    citation = result.citations[0]
    assert citation.chunk.id == chunk.id
    assert citation.source_text == 'retrieves\n71 of 100 correct passages.'
    assert citation.source_type == 'llm_summary'
    assert citation.chunk.page == 2
    assert citation.chunk.bbox_json == '[10,20,300,70]'


@pytest.mark.parametrize('citation',[{'chunk_id':'unknown','source_text':'71 of 100'}, {'chunk_id':'real-chunk','source_text':'The model achieves 99% accuracy.'}])
def test_remote_invalid_evidence_cannot_create_analysis_claim(citation: dict) -> None:
    result = provider_for({'findings':{'content':'Invented result','citations':[citation]}}).analyze([sample_chunk()])
    assert result.findings is None
    assert result.citations == []


def test_remote_answer_abstains_when_any_citation_is_invalid() -> None:
    result = provider_for({'answer':'An invented answer', 'citations':[{'chunk_id':'real-chunk','source_text':'Imaginary text'}], 'insufficient_evidence':False}).ask('What are the results?', [sample_chunk()])
    assert result.insufficient_evidence is True
    assert result.citations == []
    assert 'invented' not in result.answer


def test_remote_valid_answer_is_marked_as_ai_summary() -> None:
    result = provider_for({'answer':'It retrieves 71 of 100 correct passages.', 'citations':[{'chunk_id':'real-chunk','source_text':'71 of 100 correct passages.'}], 'insufficient_evidence':False}).ask('What are the results?', [sample_chunk()])
    assert result.insufficient_evidence is False
    assert result.citations[0].source_type == 'llm_summary'


def test_translation_uses_adapter_and_preserves_input_formula_in_prompt() -> None:
    from app.providers.openai_compatible import OpenAICompatibleProvider
    chunk = sample_chunk()
    chunk.content = 'We define L = a^2 + b^2 [12] using RAG.'
    def respond(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert chunk.content in data['messages'][-1]['content']
        assert '公式' in data['messages'][0]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':'我们使用 RAG 定义 L = a^2 + b^2 [12]。'}}]})
    provider = OpenAICompatibleProvider(api_key='test-secret',base_url='https://model.example/v1',model='test',transport=httpx.MockTransport(respond))
    assert provider.translate(chunk) == '我们使用 RAG 定义 L = a^2 + b^2 [12]。'


@pytest.mark.parametrize('kind',['timeout','upstream','invalid_json'])
def test_provider_errors_never_leak_api_key(kind: str) -> None:
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider
    def respond(request: httpx.Request) -> httpx.Response:
        if kind == 'timeout':
            raise httpx.ReadTimeout('test-secret in unsafe upstream detail',request=request)
        if kind == 'upstream':
            return httpx.Response(401,json={'error':{'message':'test-secret auth failed'}})
        return httpx.Response(200,json={'choices':[{'message':{'content':'invalid test-secret JSON'}}]})
    provider = OpenAICompatibleProvider(api_key='test-secret',base_url='https://model.example/v1',model='test',transport=httpx.MockTransport(respond))
    with pytest.raises(ProviderError) as error:
        provider.analyze([sample_chunk()])
    assert 'test-secret' not in str(error.value)
    assert error.value.status_code in {502,504}


def test_remote_prompt_context_is_bounded() -> None:
    from app.providers.openai_compatible import OpenAICompatibleProvider
    chunk = sample_chunk()
    chunk.content = 'source text '*20000
    def respond(request: httpx.Request) -> httpx.Response:
        assert len(request.content) < 50000
        assert 'real-chunk' in request.content.decode()
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}]})
    provider = OpenAICompatibleProvider(api_key='test-secret',base_url='https://model.example/v1',model='test',transport=httpx.MockTransport(respond))
    provider.analyze([chunk])


def test_import_never_calls_remote_model_even_if_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import fitz
    monkeypatch.setenv('PAPER_READER_MODEL_API_KEY','test-secret')
    def reject_request(*args,**kwargs):
        raise AssertionError('Import must remain local; explicit analyze/ask/translate actions authorize model calls')
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',reject_request)
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50,50),'A real offline import passage with sufficient text.')
        data = document.tobytes()
    response = client.post('/api/papers/import',files={'file':('offline.pdf',data)})
    assert response.status_code == 201
    assert response.json()['analysis']['provider'] == 'MockProvider'


def import_fixture(client: TestClient) -> dict:
    import fitz
    with fitz.open() as document:
        page = document.new_page()
        page.insert_textbox(fitz.Rect(50,50,540,760),'3 Results\nThe method retrieves 71 of 100 correct passages.',fontsize=11)
        data = document.tobytes()
    response = client.post('/api/papers/import',files={'file':('remote.pdf',data)})
    assert response.status_code == 201
    return response.json()


def test_remote_api_persists_only_local_geometry_and_summary_provenance(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = import_fixture(client)
    chunk = paper['chunks'][0]
    provider = provider_for({'findings':{'content':'检索准确率在该评估中为 71%。','citations':[{'chunk_id':chunk['id'],'source_text':'71 of 100 correct passages.','page':999,'bbox':[1,1,2,2]}]}})
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda: provider)
    response = client.post(f"/api/papers/{paper['id']}/analyze")
    assert response.status_code == 200
    result = response.json()
    assert result['analysis']['provider'] == 'OpenAICompatibleProvider'
    assert result['analysis']['mode'] == 'remote'
    assert result['evidence'][0]['source_type'] == 'llm_summary'
    assert result['evidence'][0]['page'] == chunk['page']
    assert result['evidence'][0]['bbox'] == chunk['bbox']
    persisted = client.get(f"/api/papers/{paper['id']}").json()
    assert persisted['analysis']['findings'] == '检索准确率在该评估中为 71%。'
    assert persisted['analysis']['evidence_ids'] == [e['id'] for e in persisted['evidence']]


def test_invalid_remote_analysis_preserves_previous_local_result(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = import_fixture(client)
    provider = provider_for({'findings':{'content':'Unsupported imaginary results','citations':[{'chunk_id':paper['chunks'][0]['id'],'source_text':'the nonexistent phrase'}]}})
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda: provider)
    response = client.post(f"/api/papers/{paper['id']}/analyze")
    assert response.status_code == 502
    assert isinstance(response.json()['detail'],str)
    after = client.get(f"/api/papers/{paper['id']}").json()
    assert after['analysis'] == paper['analysis']
    assert after['evidence'] == paper['evidence']


def test_translate_and_ask_api_go_through_adapter(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = import_fixture(client)
    chunk = paper['chunks'][0]
    provider = provider_for('该方法正确检索了 100 个段落中的 71 个。')
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda: provider)
    response = client.post(f"/api/papers/{paper['id']}/translate",json={'chunk_id':chunk['id']})
    assert response.status_code == 200
    assert response.json()['text'] == '该方法正确检索了 100 个段落中的 71 个。'
    provider = provider_for({'answer':'评估中正确检索了 71 个段落。','citations':[{'chunk_id':chunk['id'],'source_text':'71 of 100 correct passages.'}], 'insufficient_evidence':False})
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda: provider)
    answer = client.post(f"/api/papers/{paper['id']}/ask",json={'question':'结果如何？'})
    assert answer.status_code == 200
    assert answer.json()['citations'][0]['source_type'] == 'llm_summary'
    assert answer.json()['citations'][0]['bbox'] == chunk['bbox']


def test_timeout_api_returns_safe_error_and_keeps_original_pdf(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.openai_compatible import OpenAICompatibleProvider
    paper = import_fixture(client)
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout('test-secret unsafe detail',request=request)
    provider = OpenAICompatibleProvider(api_key='test-secret',base_url='https://model.example/v1',model='test',transport=httpx.MockTransport(timeout))
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda: provider)
    response = client.post(f"/api/papers/{paper['id']}/ask",json={'question':'What are the results?'})
    assert response.status_code == 504
    assert 'test-secret' not in response.text
    assert client.get(f"/api/papers/{paper['id']}/pdf").status_code == 200


def test_invalid_base_url_is_not_reported_as_configured(client: TestClient,monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PAPER_READER_MODEL_API_KEY','test-secret')
    monkeypatch.setenv('PAPER_READER_MODEL_BASE_URL','https://test-secret@model.example/v1')
    settings = client.get('/api/settings')
    assert settings.status_code == 200
    assert settings.json()['configured'] is False
    assert settings.json()['configuration_error']
    assert 'test-secret' not in settings.text
