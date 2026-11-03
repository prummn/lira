import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from app.providers.openai_compatible import OpenAICompatibleProvider, model_ssl_context
from app.providers.base import ProviderError
import ssl
import socket
import errno
from unittest.mock import Mock
from app.providers.priority import scheduled_work
from app.schemas import ModelProfileUpdate
from test_codex_subscription import AccountStub, codex_profile


@pytest.mark.parametrize('wire', ['responses', 'chat_completions'])
@pytest.mark.parametrize('effort', ['xhigh', 'disabled'])
def test_connection_probe_uses_selected_effort_and_enough_output_budget(wire, effort):
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        sent = payload.get('reasoning', {}).get('effort') if wire == 'responses' else payload.get('reasoning_effort')
        assert sent == ('xhigh' if effort == 'xhigh' else None)
        assert payload.get('max_output_tokens', payload.get('max_completion_tokens')) == (4096 if effort == 'xhigh' else 64)
        assert request.extensions['timeout']['connect'] == 15
        assert request.extensions['timeout']['read'] == 120
        if wire == 'responses':
            return httpx.Response(200, json={'status': 'completed', 'output': [
                {'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}]})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'OK'}}]})
    provider = OpenAICompatibleProvider(api_key='fixture-secret', model='gpt-6.1-sol',
        wire_api=wire, reasoning_effort=effort, transport=httpx.MockTransport(respond))
    provider.test_connection()
    assert len(requests) == 1
    assert provider.timeout == 600


@pytest.mark.parametrize('file,directory', [(None, None), ('managed.pem', None),
                                           (None, 'managed-ca'), ('managed.pem', 'managed-ca')])
def test_tls_context_combines_system_certifi_and_environment(monkeypatch, file, directory):
    context = Mock(spec=ssl.SSLContext)
    create = Mock(return_value=context)
    monkeypatch.setattr('app.providers.openai_compatible.ssl.create_default_context', create)
    monkeypatch.setattr('app.providers.openai_compatible.certifi.where', lambda: 'certifi.pem')
    for name, value in [('SSL_CERT_FILE', file), ('SSL_CERT_DIR', directory)]:
        if value:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name, raising=False)
    assert model_ssl_context() is context
    create.assert_called_once_with()
    calls = [{'cafile': 'certifi.pem'}]
    if file or directory:
        calls.append({'cafile': file, 'capath': directory})
    assert [call.kwargs for call in context.load_verify_locations.call_args_list] == calls


def test_actual_tls_context_keeps_verification_enabled(monkeypatch):
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    monkeypatch.delenv('SSL_CERT_DIR', raising=False)
    context = model_ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()['x509_ca'] > 0


def test_tls_configuration_failure_is_safe_and_sends_nothing(monkeypatch):
    monkeypatch.setenv('SSL_CERT_FILE', 'missing-private-secret.pem')
    calls = []
    provider = OpenAICompatibleProvider(api_key='fixture-secret', transport=httpx.MockTransport(
        lambda request: calls.append(request)))
    with pytest.raises(ProviderError) as caught:
        provider.test_connection()
    assert caught.value.code == 'tls_configuration'
    assert caught.value.diagnostics == {'request_sent': False}
    assert 'private-secret' not in json.dumps(caught.value.public_payload())
    assert calls == []


@pytest.mark.parametrize('cause,code,retryable', [
    (socket.gaierror(socket.EAI_NONAME, 'private-secret'), 'transport_dns', True),
    (ConnectionRefusedError(errno.ECONNREFUSED, 'private-secret'), 'transport_refused', True),
    (OSError(10061, 'private-secret'), 'transport_refused', True),
    (ConnectionResetError(errno.ECONNRESET, 'private-secret'), 'transport_reset', True),
    (OSError(errno.ENETUNREACH, 'private-secret'), 'transport_unreachable', True),
    (ssl.SSLCertVerificationError(1, 'private-secret'), 'tls_certificate', False),
    (ssl.SSLError(1, 'private-secret'), 'transport_tls', False),
    (RuntimeError('CERTIFICATE_VERIFY_FAILED DNS ConnectionRefusedError private-secret'), 'transport_connection', True),
])
def test_connection_cause_classification_never_uses_messages_or_retries(cause, code, retryable):
    calls = []
    wrapper = RuntimeError('https://private.example fixture-secret')
    wrapper.__cause__ = cause
    def respond(request):
        calls.append(request)
        raise httpx.ConnectError('private-secret', request=request) from wrapper
    provider = OpenAICompatibleProvider(api_key='fixture-secret', wire_api='responses',
        transport=httpx.MockTransport(respond))
    with pytest.raises(ProviderError) as caught:
        provider.test_connection()
    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert len(calls) == 1
    public = json.dumps(caught.value.public_payload())
    assert all(value not in public for value in ['private-secret', 'private.example', 'fixture-secret'])


def test_http_client_receives_verified_context(monkeypatch):
    original = httpx.Client
    seen = []
    def build(**kwargs):
        context = kwargs['verify']
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        assert kwargs['follow_redirects'] is False
        seen.append(context)
        return original(**kwargs)
    monkeypatch.setattr('app.providers.openai_compatible.httpx.Client', build)
    provider = OpenAICompatibleProvider(api_key='fixture', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'choices': [{'message': {'content': 'OK'}}]})))
    provider.test_connection()
    assert len(seen) == 1


def test_connection_budget_exhaustion_does_not_change_protocol_or_retry():
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url.path == '/v1/responses'
        assert json.loads(request.content)['reasoning'] == {'effort': 'xhigh'}
        return httpx.Response(200, json={'status': 'incomplete',
            'incomplete_details': {'reason': 'max_output_tokens'}})
    provider = OpenAICompatibleProvider(api_key='fixture', wire_api='responses',
        reasoning_effort='xhigh', transport=httpx.MockTransport(respond))
    with pytest.raises(ProviderError) as caught:
        provider.test_connection()
    assert caught.value.code == 'output_budget'
    assert caught.value.retryable is False
    assert len(calls) == 1


def test_connection_small_timeout_is_respected():
    def respond(request):
        assert all(value == 5 for value in request.extensions['timeout'].values())
        return httpx.Response(200, json={'choices': [{'message': {'content': 'OK'}}]})
    OpenAICompatibleProvider(api_key='fixture', timeout=5,
        transport=httpx.MockTransport(respond)).test_connection()


def test_global_provider_error_response_filters_metadata_and_keeps_detail(client):
    @client.app.get('/test-provider-error')
    def fail():
        error = ProviderError('安全提示', 503, code='transport_dns', retryable=True,
            diagnostics={'http_status': 502, 'transport_type': 'ConnectError',
                         'request_sent': False, 'url': 'https://private.example',
                         'key': 'fixture-secret', 'tls_verify_code': 'fixture-secret',
                         'upstream_code': 'fixture-secret', 'event_type': ['secret']})
        raise error
    response = client.get('/test-provider-error')
    assert response.status_code == 503
    assert response.json() == {'detail': '安全提示', 'code': 'transport_dns', 'retryable': True,
        'diagnostics': {'http_status': 502, 'transport_type': 'ConnectError', 'request_sent': False}}


def test_profile_connection_failure_returns_safe_diagnostics_without_saving(client, monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        raise httpx.ConnectError('fixture-secret https://private.example') from socket.gaierror(
            socket.EAI_NONAME, 'private-secret')
    original = client.app.state.model_profiles._build
    def build(values):
        provider = original(values)
        provider._transport = httpx.MockTransport(respond)
        return provider
    monkeypatch.setattr(client.app.state.model_profiles, '_build', build)
    response = client.post('/api/settings/profiles', json={
        'name': 'fixture', 'base_url': 'https://model.example/v1', 'api_key': 'fixture-secret',
        'model': 'gpt-6.1-sol', 'wire_api': 'responses', 'reasoning_effort': 'xhigh',
        'test_connection': True})
    assert response.status_code == 502
    assert response.json()['code'] == 'transport_dns'
    assert response.json()['diagnostics'] == {'transport_type': 'ConnectError'}
    assert len(calls) == 1
    assert not client.app.state.model_profiles.path.exists()
    assert all(value not in response.text for value in ['fixture-secret', 'private.example', 'private-secret'])


def test_public_error_metadata_rejects_unknown_codes_and_wrong_types():
    error = ProviderError('安全提示', code='fixture-secret', retryable='fixture-secret',
        diagnostics={'http_status': True, 'request_sent': 'false', 'transport_type': 'fixture-secret',
                     'tls_verify_code': 1001, 'upstream_type': {'key': 'fixture-secret'}})
    assert error.public_payload() == {'detail': '安全提示', 'code': 'provider_error',
                                      'retryable': False, 'diagnostics': {}}


def test_official_concurrency_is_persisted_account_wide_and_borrows_idle_capacity(client):
    store = client.app.state.model_profiles
    store.codex = AccountStub()
    first = store.save(ModelProfileUpdate(**codex_profile()))
    second = store.save(ModelProfileUpdate(**codex_profile()))
    assert client.put('/api/settings/codex/concurrency', json={'max_concurrency': 2}).status_code == 200
    assert json.loads(store.path.read_text())['codex_max_concurrency'] == 2
    assert client.get('/api/settings/profiles').json()['codex_max_concurrency'] == 2
    entered, release, waiting, entered_second = Event(), Event(), Event(), Event()
    def background(profile, initial=False):
        with scheduled_work(2):
            if not initial:
                waiting.set()
            with store.provider(profile['id'])._capacity():
                if initial:
                    entered.set()
                    assert release.wait(3)
                else:
                    entered_second.set()
    with ThreadPoolExecutor(3) as pool:
        one = pool.submit(background, first, True)
        assert entered.wait(1)
        two = pool.submit(background, second)
        assert waiting.wait(1)
        assert entered_second.wait(1)
        # The second background call finishes; foreground can use its free slot.
        with store.provider(second['id'])._capacity():
            pass
        release.set()
        one.result(2)
        two.result(2)
    assert entered_second.is_set()


@pytest.mark.parametrize('value', [0, 9, 16])
def test_official_concurrency_rejects_values_outside_local_supported_range(client, value):
    assert client.put('/api/settings/codex/concurrency', json={'max_concurrency': value}).status_code == 422


def test_official_limit_lowering_takes_effect_for_already_created_providers(client):
    store = client.app.state.model_profiles
    store.codex = AccountStub()
    first = store.save(ModelProfileUpdate(**codex_profile()))
    second = store.save(ModelProfileUpdate(**codex_profile()))
    store.set_codex_concurrency(2)
    providers = [store.provider(p['id']) for p in (first, second)]
    entered, release, waiting = Event(), Event(), Event()
    def run():
        waiting.set()
        with providers[1]._capacity():
            entered.set()
    # Lowering cannot cancel in-flight work or leave old providers at 2.
    with ThreadPoolExecutor(1) as pool:
        with providers[0]._capacity():
            store.set_codex_concurrency(1)
            task = pool.submit(run)
            assert waiting.wait(1)
            assert not entered.wait(.05)
        task.result(2)
    assert entered.is_set()
    from app.providers.profiles import ProfileStore
    assert ProfileStore(store.path).codex_concurrency() == 1
