from __future__ import annotations
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.models import PaperChunk
from app.providers import get_model_provider


def test_provider_error_metadata_keeps_existing_constructor_compatible():
    from app.providers.base import ProviderError

    legacy = ProviderError('safe message', 504)
    assert str(legacy) == 'safe message'
    assert legacy.status_code == 504
    assert legacy.code == 'provider_error'
    assert legacy.retryable is False
    assert legacy.retry_after is None
    transient = ProviderError('safe message', code='stream_interrupted', retryable=True, retry_after=3)
    assert (transient.code, transient.retryable, transient.retry_after) == ('stream_interrupted', True, 3)


def test_structured_json_parser_accepts_fences_preamble_and_trailing_prose():
    from app.providers.openai_compatible import parse_json_object

    assert parse_json_object('```json\n{"answer":"ok"}\n```') == {'answer': 'ok'}
    assert parse_json_object('Here is the result:\n{"answer":"ok"}\nDone.') == {'answer': 'ok'}
    assert parse_json_object('\ufeff {"answer":"ok"} trailing') == {'answer': 'ok'}


@pytest.mark.parametrize('failure,code,status,retryable', [
    (httpx.ConnectTimeout, 'transport_timeout', 504, True),
    (httpx.ReadTimeout, 'transport_timeout', 504, True),
    (httpx.WriteTimeout, 'transport_timeout', 504, True),
    (httpx.PoolTimeout, 'transport_timeout', 504, True),
    (httpx.ConnectError, 'transport_connection', 502, True),
    (httpx.ReadError, 'transport_connection', 502, True),
    (httpx.WriteError, 'transport_connection', 502, True),
    (httpx.RemoteProtocolError, 'transport_protocol', 502, True),
    (httpx.LocalProtocolError, 'invalid_request', 502, False),
    (httpx.DecodingError, 'invalid_response', 502, False),
])
@pytest.mark.parametrize('wire', ['chat_completions', 'responses'])
def test_transport_failure_classification_is_safe_and_never_retries_inside_provider(failure, code, status, retryable, wire):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider
    calls = []

    def respond(request):
        calls.append(request)
        raise failure('test-secret https://private.example unsafe upstream detail', request=request)

    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api=wire, transport=httpx.MockTransport(respond))
    provider.last_usage = {'input_tokens': 999}
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert (error.value.code, error.value.status_code, error.value.retryable) == (code, status, retryable)
    assert error.value.retry_after is None
    assert len(calls) == 1
    assert provider.last_usage == {}
    assert not any(private in str(error.value) for private in ('test-secret', 'private.example', 'unsafe upstream'))


@pytest.mark.parametrize('status,code,retryable,api_status', [
    (400, 'invalid_request', False, 502),
    (401, 'authentication', False, 502),
    (403, 'authentication', False, 502),
    (404, 'invalid_request', False, 502),
    (408, 'upstream_timeout', True, 504),
    (422, 'invalid_request', False, 502),
    (429, 'rate_limit', True, 503),
    (500, 'upstream_error', True, 502),
    (501, 'upstream_error', False, 502),
    (502, 'upstream_error', True, 502),
    (503, 'upstream_error', True, 502),
    (504, 'upstream_timeout', True, 504),
    (524, 'upstream_timeout', True, 504),
])
def test_http_failure_classification_uses_status_not_private_body(status, code, retryable, api_status):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider

    class PrivateBody(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError('Error bodies must never be consumed or exposed')
            yield b''

    provider = OpenAICompatibleProvider(api_key='test-secret', transport=httpx.MockTransport(
        lambda request: httpx.Response(status, headers={'retry-after': '4'}, stream=PrivateBody())))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert (error.value.code, error.value.retryable, error.value.status_code) == (code, retryable, api_status)
    assert error.value.retry_after == (4 if retryable else None)
    assert provider.last_usage == {}


@pytest.mark.parametrize('header,delay', [('0', 0), ('5', 5), ('999', 30), ('-1', None), ('NaN', None), ('Inf', None), ('1e3', None), ('private upstream value', None)])
def test_retry_after_delta_seconds_is_bounded_and_invalid_values_are_ignored(header, delay):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(api_key='test', transport=httpx.MockTransport(
        lambda request: httpx.Response(429, headers={'retry-after': header})))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert error.value.retry_after == delay


@pytest.mark.parametrize('header,delay', [('Thu, 08 Oct 2026 12:00:10 GMT', 10), ('Thu, 08 Oct 2026 12:10:00 GMT', 30), ('Thu, 08 Oct 2026 11:59:50 GMT', 0)])
def test_retry_after_http_date_uses_current_utc_time_and_is_bounded(monkeypatch, header, delay):
    from datetime import datetime, timezone
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider

    monkeypatch.setattr('app.providers.openai_compatible.time.time', lambda: datetime(2026, 10, 8, 12, tzinfo=timezone.utc).timestamp())
    provider = OpenAICompatibleProvider(api_key='test', transport=httpx.MockTransport(
        lambda request: httpx.Response(503, headers={'retry-after': header})))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert error.value.retry_after == delay


@pytest.mark.parametrize('ending', [b'', b'data: [DONE]\n\n', 'remote_protocol', 'read_error'])
def test_interrupted_responses_stream_never_accepts_partial_json_and_preserves_only_reported_usage(ending):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider

    class InterruptedStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"type":"response.in_progress","response":{"status":"in_progress","usage":{"input_tokens":12,"private":"test-secret"}}}\n\n'
            yield b'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}\n\n'
            if ending == 'remote_protocol':
                raise httpx.RemoteProtocolError('test-secret private interruption')
            if ending == 'read_error':
                raise httpx.ReadError('test-secret private interruption')
            yield ending

    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api='responses', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=InterruptedStream())))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    expected = {'remote_protocol': 'transport_protocol', 'read_error': 'transport_connection'}.get(ending, 'stream_interrupted')
    assert error.value.code == expected
    assert error.value.retryable is True
    assert provider.last_usage == {'input_tokens': 12}
    assert 'test-secret' not in str(error.value)


@pytest.mark.parametrize('event_type', ['error', 'response.failed'])
@pytest.mark.parametrize('upstream_code,code,retryable', [
    ('server_error', 'upstream_error', True),
    ('rate_limit_exceeded', 'rate_limit', True),
    ('rate_limit_error', 'rate_limit', True),
    ('invalid_api_key', 'authentication', False),
    ('invalid_request_error', 'invalid_request', False),
    ('private-test-secret-error', 'upstream_error', True),
])
def test_responses_stream_failure_classifies_only_known_error_codes(event_type, upstream_code, code, retryable):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider

    failure = {'code': upstream_code, 'message': 'test-secret https://private.example unsafe upstream'}
    event = {'type': event_type}
    if event_type == 'error':
        event.update(failure)
    else:
        event['response'] = {'status': 'failed', 'error': failure, 'usage': {'input_tokens': 12, 'output_tokens': 34}}
    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api='responses', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=('data: '+json.dumps(event)+'\n\n').encode())))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert (error.value.code, error.value.retryable) == (code, retryable)
    assert 'test-secret' not in str(error.value)
    assert 'private.example' not in str(error.value)
    assert provider.last_usage == ({'input_tokens': 12, 'output_tokens': 34} if event_type == 'response.failed' else {})


@pytest.mark.parametrize('wire', ['chat_completions', 'responses', 'responses_stream'])
def test_output_budget_exhaustion_is_not_a_transport_retry_and_keeps_actual_usage(wire):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider

    usage = {'input_tokens': 12, 'output_tokens': 300, 'output_tokens_details': {'reasoning_tokens': 299}}
    if wire == 'chat_completions':
        data = {'choices': [{'finish_reason': 'length', 'message': {'content': '{"ok":true}'}}], 'usage': usage}
    else:
        data = {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}, 'usage': usage,
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]}

    def respond(request):
        if wire == 'responses_stream':
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                content=('data: '+json.dumps({'type': 'response.incomplete', 'response': data})+'\n\n').encode())
        return httpx.Response(200, json=data)

    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api='responses' if wire.startswith('responses') else wire,
        transport=httpx.MockTransport(respond))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert error.value.code == 'output_budget'
    assert error.value.retryable is False
    assert provider.last_usage == usage


@pytest.mark.parametrize('data', [
    {'status': 'failed', 'error': {'code': 'server_error', 'message': 'test-secret'}},
    {'status': 'failed', 'error': {'code': 'rate_limit_exceeded', 'message': 'test-secret'}},
])
def test_nonstream_responses_failure_matches_stream_classification(data):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api='responses', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=data)))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert error.value.code == ('rate_limit' if data['error']['code'] == 'rate_limit_exceeded' else 'upstream_error')
    assert error.value.retryable is True
    assert 'test-secret' not in str(error.value)


@pytest.mark.parametrize('upstream,code,retryable', [
    ({'code': None, 'type': 'server_error'}, 'upstream_error', True),
    ({'type': 'api_error'}, 'upstream_error', True),
    ({'type': 'overloaded_error'}, 'upstream_error', True),
    ({'type': 'authentication_error'}, 'authentication', False),
    ({'type': 'invalid_request_error'}, 'invalid_request', False),
    ({'code': 'invalid_api_key', 'type': 'server_error'}, 'authentication', False),
    ({'code': 'test-secret', 'type': 'server_error'}, 'upstream_error', False),
])
def test_upstream_type_only_errors_are_classified_without_overriding_explicit_code(upstream, code, retryable):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api='responses', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type': 'text/event-stream'},
            content=('data: '+json.dumps({'type': 'response.failed', 'response': {
                'status': 'failed', 'error': {**upstream, 'message': 'test-secret'}}})+'\n\n').encode())))
    with pytest.raises(ProviderError) as caught:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert caught.value.diagnostics['http_status'] == 200
    assert caught.value.diagnostics['upstream_type'] == upstream['type']
    assert 'test-secret' not in json.dumps(caught.value.diagnostics)


@pytest.mark.parametrize('body', ['timeout', 'malformed'])
def test_errors_while_reading_response_keep_known_http_status(body):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider
    class TimedOut(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"type":"response.created","response":{"status":"in_progress"}}\n\n'
            raise httpx.ReadTimeout('test-secret')
    response = (httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=TimedOut())
                if body == 'timeout' else httpx.Response(200, content=b'not JSON'))
    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api='responses',
        transport=httpx.MockTransport(lambda request: response))
    with pytest.raises(ProviderError) as caught:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert caught.value.diagnostics['http_status'] == 200
    assert 'test-secret' not in str(caught.value)


def test_certificate_failure_is_not_retried_as_service_outage():
    import ssl
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider
    def fail(request):
        certificate = ssl.SSLCertVerificationError(1, 'test-secret')
        certificate.verify_code = 18
        raise httpx.ConnectError('test-secret') from certificate
    provider = OpenAICompatibleProvider(api_key='test-secret', transport=httpx.MockTransport(fail))
    with pytest.raises(ProviderError) as caught:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert caught.value.code == 'tls_certificate'
    assert caught.value.retryable is False
    assert caught.value.diagnostics == {'transport_type': 'ConnectError', 'tls_verify_code': 18}
    assert 'test-secret' not in str(caught.value)


def test_connection_and_read_failures_are_distinguishable_without_private_text():
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider(api_key='test-secret', transport=httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError('test-secret'))))
    with pytest.raises(ProviderError) as caught:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert caught.value.diagnostics == {'transport_type': 'ConnectError'}
    assert caught.value.retryable


@pytest.mark.parametrize('event', [
    {'type': []},
    {'type': 'response.completed', 'response': {'status': 'in_progress'}},
    {'type': 'response.failed', 'response': {'status': 'completed', 'error': {'code': 'server_error'}}},
    {'type': 'response.incomplete', 'response': {'status': 'completed'}},
])
def test_malformed_stream_envelopes_are_nonretryable(event):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(api_key='test', wire_api='responses', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=('data: '+json.dumps(event)+'\n\n').encode())))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert (error.value.code, error.value.retryable) == ('invalid_response', False)


def test_model_timeout_defaults_to_600_and_allows_long_synthesis_budget() -> None:
    from app.providers.openai_compatible import OpenAICompatibleProvider

    default = OpenAICompatibleProvider(api_key='test-secret')
    extended = OpenAICompatibleProvider(api_key='test-secret', timeout=1800)
    assert default.timeout == 600
    assert extended.timeout == 1800


@pytest.mark.parametrize('timeout', [0, 1801, float('inf'), float('nan')])
def test_model_timeout_rejects_values_outside_one_to_1800_seconds(timeout: float) -> None:
    from app.providers.openai_compatible import OpenAICompatibleProvider

    with pytest.raises(ValueError):
        OpenAICompatibleProvider(api_key='test-secret', timeout=timeout)


def sample_chunk() -> PaperChunk:
    return PaperChunk(id='real-chunk', paper_id='real-paper', page=2, section='3 Results', content='The method retrieves\n71 of 100 correct passages.', bbox_json='[10,20,300,70]', page_width=600, page_height=800)


@pytest.mark.parametrize('wire', ['chat_completions', 'responses'])
def test_default_nonreasoning_profile_omits_stage_reasoning_parameters(wire):
    from app.providers.openai_compatible import OpenAICompatibleProvider

    def respond(request):
        payload = json.loads(request.content)
        assert payload['model'] == 'gpt-4.1-mini'
        assert 'reasoning_effort' not in payload
        assert 'reasoning' not in payload
        if wire == 'responses':
            return httpx.Response(200, json={'status': 'completed', 'output': [
                {'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]})
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"ok":true}'}}]})

    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api=wire, transport=httpx.MockTransport(respond))
    assert provider.complete_json('JSON', {}, max_output_tokens=300, reasoning_effort='high') == {'ok': True}


@pytest.mark.parametrize('wire', ['chat_completions', 'responses'])
@pytest.mark.parametrize('configured,stage,expected', [('xhigh', None, 'xhigh'), ('xhigh', 'medium', 'medium'), ('none', None, 'none')])
def test_explicit_reasoning_profiles_preserve_configured_and_stage_efforts(wire, configured, stage, expected):
    from app.providers.openai_compatible import OpenAICompatibleProvider

    def respond(request):
        payload = json.loads(request.content)
        if wire == 'responses':
            assert payload['reasoning'] == {'effort': expected}
            return httpx.Response(200, json={'status': 'completed', 'output': [
                {'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]})
        assert payload['reasoning_effort'] == expected
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"ok":true}'}}]})

    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api=wire, reasoning_effort=configured, transport=httpx.MockTransport(respond))
    assert provider.complete_json('JSON', {}, max_output_tokens=300, reasoning_effort=stage) == {'ok': True}


def test_reasoning_disabled_setting_overrides_stages_and_has_a_distinct_cache_key(monkeypatch):
    from app.providers.openai_compatible import OpenAICompatibleProvider
    from app.services.model_calls import request_signature

    monkeypatch.setenv('PAPER_READER_MODEL_API_KEY', 'test-secret')
    monkeypatch.setenv('PAPER_READER_MODEL_REASONING_EFFORT', 'disabled')
    disabled = get_model_provider()
    assert disabled.mode == 'remote'
    enabled = OpenAICompatibleProvider(api_key='test-secret', reasoning_effort='high')
    assert request_signature(disabled, 'JSON', {}, 'extract', reasoning_effort='medium') != request_signature(enabled, 'JSON', {}, 'extract', reasoning_effort='medium')


@pytest.mark.parametrize('wire', ['chat_completions', 'responses'])
def test_json_trickle_enforces_total_deadline_for_both_protocols(monkeypatch, wire):
    from app.providers.openai_compatible import OpenAICompatibleProvider
    from app.providers.base import ProviderError

    now, received = [0.0], []
    monkeypatch.setattr('app.providers.openai_compatible.time.monotonic', lambda: now[0])
    data = {'choices': [{'message': {'content': '{"ok":true}'}}]} if wire == 'chat_completions' else {
        'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]}
    body = json.dumps(data).encode()
    split = len(body) // 3
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for part in (body[:split], body[split:split*2], body[split*2:]):
                received.append(part)
                now[0] += 0.8
                yield part
    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api=wire, timeout=1, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type': 'application/json'}, stream=Stream())))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert error.value.status_code == 504
    assert len(received) == 2


@pytest.mark.parametrize('wire', ['chat_completions', 'responses'])
def test_json_response_size_is_bounded_before_full_body_is_read(wire):
    from app.providers.openai_compatible import OpenAICompatibleProvider
    from app.providers.base import ProviderError

    received = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for index in range(30):
                received.append(index)
                yield b' ' * 500000
    provider = OpenAICompatibleProvider(api_key='test-secret', wire_api=wire, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type': 'application/json'}, stream=Stream())))
    with pytest.raises(ProviderError):
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert len(received) <= 3


def test_responses_stream_waits_for_completed_envelope_and_actual_usage():
    from app.providers.openai_compatible import OpenAICompatibleProvider
    final = {'status': 'completed', 'model': 'real-model', 'usage': {'input_tokens': 12, 'output_tokens': 34},
        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]}
    events = [{'type': 'response.created', 'response': {'status': 'in_progress'}},
              {'type': 'response.output_text.delta', 'delta': '{"wrong":"never parse this partial"}'},
              {'type': 'response.completed', 'response': final}]
    def respond(request):
        assert json.loads(request.content)['stream'] is True
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
            content=''.join('event: ' + e['type'] + '\ndata: ' + json.dumps(e) + '\n\n' for e in events).encode())
    provider = OpenAICompatibleProvider(api_key='test', base_url='https://example.test', model='model', wire_api='responses',
        transport=httpx.MockTransport(respond))
    assert provider.complete_json('JSON', {}, max_output_tokens=300) == {'ok': True}
    assert provider.last_usage == {'input_tokens': 12, 'output_tokens': 34}


def test_responses_stream_protocol_overhead_does_not_limit_small_final_output():
    from app.providers.openai_compatible import OpenAICompatibleProvider
    events = [{'type': 'response.output_text.delta', 'delta': 'x' * 1000} for _ in range(1100)]
    events.append({'type': 'response.completed', 'response': {'status': 'completed', 'output': [
        {'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]}})
    content = ''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode()
    provider = OpenAICompatibleProvider(api_key='test', wire_api='responses', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type':'text/event-stream'},content=content)))
    assert provider.complete_json('JSON', {}, max_output_tokens=6000) == {'ok': True}


def test_malformed_stream_event_type_is_a_safe_failure():
    from app.providers.openai_compatible import OpenAICompatibleProvider
    from app.providers.base import ProviderError
    provider = OpenAICompatibleProvider(api_key='test', wire_api='responses', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type':'text/event-stream'},
            content=b'data: {"type": []}\n\n')))
    with pytest.raises(ProviderError):
        provider.complete_json('JSON', {}, max_output_tokens=300)


@pytest.mark.parametrize('event_type', ['response.failed', 'response.incomplete'])
def test_failed_stream_event_cannot_masquerade_as_completed(event_type):
    from app.providers.openai_compatible import OpenAICompatibleProvider
    from app.providers.base import ProviderError
    event = {'type': event_type, 'response': {'status': 'completed', 'usage': {'input_tokens': 12, 'output_tokens': 34},
        'output': [{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]}}
    provider=OpenAICompatibleProvider(api_key='test', wire_api='responses', transport=httpx.MockTransport(
        lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=('data: '+json.dumps(event)+'\n\n').encode())))
    with pytest.raises(ProviderError):
        provider.complete_json('JSON',{},max_output_tokens=300)
    assert provider.last_usage['output_tokens'] == 34


def test_newline_free_stream_is_bounded_before_entire_line_is_buffered():
    from app.providers.openai_compatible import OpenAICompatibleProvider
    from app.providers.base import ProviderError
    read = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for i in range(30):
                read.append(i)
                yield b'x' * 500000
    provider=OpenAICompatibleProvider(api_key='test',wire_api='responses',transport=httpx.MockTransport(
        lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())))
    with pytest.raises(ProviderError):
        provider.complete_json('JSON',{},max_output_tokens=300)
    assert len(read) <= 4


def test_stream_deadline_includes_header_wait(monkeypatch):
    from app.providers.openai_compatible import OpenAICompatibleProvider
    from app.providers.base import ProviderError
    now = [0.0]
    monkeypatch.setattr('app.providers.openai_compatible.time.monotonic',lambda:now[0])
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            now[0] += 0.8
            yield b'data: {"type":"response.completed","response":{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"{}"}]}]}}\n\n'
    def respond(request):
        now[0] += 0.8
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
    provider=OpenAICompatibleProvider(api_key='test',wire_api='responses',timeout=1,transport=httpx.MockTransport(respond))
    with pytest.raises(ProviderError):
        provider.complete_json('JSON',{},max_output_tokens=300)


def test_newline_free_trickle_checks_deadline_for_each_received_chunk(monkeypatch):
    from app.providers.openai_compatible import OpenAICompatibleProvider
    from app.providers.base import ProviderError
    now, read = [0.0], []
    monkeypatch.setattr('app.providers.openai_compatible.time.monotonic',lambda:now[0])
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for i in range(10):
                read.append(i)
                now[0] += 0.5
                yield b'x'
    provider=OpenAICompatibleProvider(api_key='test',wire_api='responses',timeout=1,transport=httpx.MockTransport(
        lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())))
    with pytest.raises(ProviderError):
        provider.complete_json('JSON',{},max_output_tokens=300)
    assert len(read) <= 3


@pytest.mark.parametrize('events', [
    [{'type':'response.output_text.delta','delta':'{"ok":true}'}],
    [{'type':'error','error':{'message':'private upstream details'}}],
    [{'type':'response.incomplete','response':{'status':'incomplete','output':[],'usage':{'input_tokens':12,'output_tokens':99}}}],
])
def test_responses_stream_truncation_and_error_are_safe_failures(events):
    from app.providers.openai_compatible import OpenAICompatibleProvider
    from app.providers.base import ProviderError
    provider = OpenAICompatibleProvider(api_key='test', wire_api='responses', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type':'text/event-stream'},
            content=''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode())))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert 'private upstream details' not in str(error.value)
    if events[0]['type'] == 'response.incomplete':
        assert provider.last_usage['output_tokens'] == 99


@pytest.mark.parametrize('event', [
    {'type': 'error', 'code': 'private-provider-code', 'message': 'private-secret'},
    {'type': 'response.failed', 'response': {'status': 'failed', 'error': {'code': 'private-provider-code', 'message': 'private-secret'}}},
])
def test_unknown_terminal_error_after_http_acceptance_is_retryable_without_leaking_details(event):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider(api_key='private-secret', wire_api='responses', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type': 'text/event-stream'},
            content=('data: ' + json.dumps(event) + '\n\n').encode())))
    with pytest.raises(ProviderError) as caught:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert caught.value.retryable is True
    assert caught.value.diagnostics['event_type'] == event['type']
    assert 'private-' not in json.dumps(caught.value.diagnostics)


def test_unknown_sse_error_from_successful_stream_is_retryable():
    from app.providers.openai_compatible import OpenAICompatibleProvider
    from app.providers.base import ProviderError
    event = {'type': 'error', 'error': {'message': 'temporary upstream failure'}}
    provider = OpenAICompatibleProvider(api_key='test', wire_api='responses', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type': 'text/event-stream'},
            content=('data: ' + json.dumps(event) + '\n\n').encode())))
    with pytest.raises(ProviderError) as error:
        provider.complete_json('JSON', {}, max_output_tokens=300)
    assert error.value.code == 'upstream_error'
    assert error.value.retryable is True


def provider_for(content: str | dict):
    from app.providers.openai_compatible import OpenAICompatibleProvider
    message = content if isinstance(content,str) else json.dumps(content)
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url == 'https://model.example/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer test-secret'
        payload = json.loads(request.content)
        assert payload['model'] == 'test-model'
        output = message
        data = json.loads(payload['messages'][-1]['content']) if isinstance(content, dict) else {}
        def entries(value):
            if isinstance(value, dict):
                if isinstance(value.get('content'), str) and isinstance(value.get('citations'), list):
                    yield value
                else:
                    for item in value.values():
                        yield from entries(item)
            elif isinstance(value, list):
                for item in value:
                    yield from entries(item)
        if data.get('stage') == 'review_card_science':
            output = json.dumps({'items': [{'field': item['field'], 'decision': 'supported'} for item in data['items']]})
        elif 'chunks' in data and data['chunks'] and 'part_id' in data['chunks'][0]:
            facts = []
            for value in entries(content):
                citations = [{**citation, 'part_id': next((part['part_id'] for part in data['chunks'] if part['chunk_id'] == citation['chunk_id']), data['chunks'][0]['part_id'])} for citation in value['citations']]
                facts.append({'content': value['content'], 'citations': citations})
            output = json.dumps({'facts': facts})
        elif 'facts' in data:
            enhanced = json.loads(message)
            from app.providers.validation import canonical_quote
            for value in entries(enhanced):
                if 'evidence' in data:
                    value['citation_ids'] = [next((source['id'] for source in data['evidence'] if source['chunk_id'] == citation['chunk_id'] and canonical_quote(source['source_text'], citation['source_text']) is not None), 'unknown-evidence') for citation in value.pop('citations')]
                else:
                    value['citations'] = [next((source for fact in data['facts'] for source in fact['citations'] if source['chunk_id'] == citation['chunk_id'] and canonical_quote(source['source_text'], citation['source_text']) is not None), citation) for citation in value['citations']]
            output = json.dumps(enhanced)
        return httpx.Response(200,json={'choices':[{'message':{'content':output}}], 'model':'test-model-2026'})
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


def test_remote_answer_reports_validation_failure_when_any_citation_is_invalid() -> None:
    from app.providers.base import ProviderError
    with pytest.raises(ProviderError) as error:
        provider_for({'answer':'An invented answer', 'citations':[{'chunk_id':'real-chunk','source_text':'Imaginary text'}], 'insufficient_evidence':False}).ask('What are the results?', [sample_chunk()])
    assert error.value.code == 'invalid_response'
    assert 'invented' not in str(error.value)


def test_remote_valid_answer_is_marked_as_ai_summary() -> None:
    result = provider_for({'answer':'It retrieves 71 of 100 correct passages.', 'citations':[{'chunk_id':'real-chunk','source_text':'71 of 100 correct passages.'}], 'insufficient_evidence':False}).ask('What are the results?', [sample_chunk()])
    assert result.insufficient_evidence is False
    assert result.citations[0].source_type == 'llm_summary'


def test_remote_answer_keeps_provenance_notes_and_context_request() -> None:
    chunk = sample_chunk()
    result = provider_for({
        'answer': '模型先解析函数调用，再在 yield 时等待外部事件。',
        'citations': [{'chunk_id': chunk.id, 'source_text': '71 of 100 correct passages.'}],
        'insufficient_evidence': False,
        'facts': ['函数调用由执行器验证后执行。'],
        'inferences': ['普通文字可能通过消息函数发给用户。'],
        'unknowns': ['该论文没有在当前证据中给出完整函数签名。'],
        'needs_more_context': True,
    }).ask('什么时候解析函数参数？', [chunk])
    assert result.needs_more_context is True
    assert result.facts == ['函数调用由执行器验证后执行。']
    assert result.inferences == ['普通文字可能通过消息函数发给用户。']
    assert result.unknowns == ['该论文没有在当前证据中给出完整函数签名。']


def test_remote_visual_ask_sends_page_image_to_chat_completions() -> None:
    from app.providers.openai_compatible import OpenAICompatibleProvider
    seen: dict = {}

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen['content'] = payload['messages'][-1]['content']
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'answer': '图中展示了准确率随步骤增加而上升。',
            'citations': [{'chunk_id': 'visual-chunk', 'source_text': 'Accuracy increases with steps.'}],
            'insufficient_evidence': False,
        })}}], 'model': 'vision-model'})

    provider = OpenAICompatibleProvider(api_key='test-secret', base_url='https://model.example/v1', model='vision-model', transport=httpx.MockTransport(respond))
    chunk = sample_chunk()
    chunk.id = 'visual-chunk'
    chunk.content = 'Accuracy increases with steps.'
    result = provider.ask_with_image('图中展示了什么趋势？', [chunk], 'data:image/png;base64,ZmFrZQ==')
    assert result.insufficient_evidence is False
    assert any(item.get('type') == 'image_url' for item in seen['content'])
    assert result.citations[0].source_text == chunk.content


def test_visual_crop_source_is_not_dropped_when_many_same_page_chunks_tie():
    from app.models import PaperChunk
    from app.providers.openai_compatible import OpenAICompatibleProvider
    seen = {}
    def respond(request):
        content = json.loads(request.content)['messages'][-1]['content']
        text = next(item['text'] for item in content if item['type'] == 'text')
        seen['payload'] = json.loads(text[text.index('{'):])
        return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps({
            'answer':'这是状态方程。','citations':[],'insufficient_evidence':False,
        })}}]})
    provider = OpenAICompatibleProvider(api_key='test', base_url='https://model.example/v1',
        model='vision', transport=httpx.MockTransport(respond))
    selected = PaperChunk(id='z-formula',paper_id='p',page=1,content='P = rho R T')
    irrelevant = [PaperChunk(id=f'a-header-{index:02}',paper_id='p',page=1,content='Running header') for index in range(30)]
    provider.ask_with_image('请解释这些符号。',[selected,*irrelevant],'data:image/png;base64,ZmFrZQ==')
    assert seen['payload']['chunks'][0]['chunk_id'] == 'z-formula'


def test_remote_visual_ask_keeps_a_plain_answer_when_json_format_is_ignored() -> None:
    from app.providers.openai_compatible import OpenAICompatibleProvider
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = 'Apply measures whether the generated patch can be applied.' if calls == 2 else 'The chart shows Apply.'
        return httpx.Response(200, json={'choices': [{'message': {'content': content}}], 'model': 'vision-model'})

    provider = OpenAICompatibleProvider(api_key='test-secret', base_url='https://model.example/v1', model='vision-model', transport=httpx.MockTransport(respond))
    result = provider.ask_with_image('表中的 Apply 指标是什么意思？', [sample_chunk()], 'data:image/png;base64,ZmFrZQ==')
    assert result.insufficient_evidence is False
    assert 'The chart shows Apply' in result.answer
    assert calls == 1


@pytest.mark.parametrize('recover', [True, False])
def test_visual_retry_keeps_the_image_instead_of_silently_answering_from_text(monkeypatch, recover):
    from app.providers.base import ProviderError
    from app.providers.openai_compatible import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(api_key='test-secret', base_url='https://model.example/v1', model='vision')
    seen = []

    def complete(prompt, payload, **options):
        seen.append(options)
        if len(seen) == 1 or not recover:
            raise ProviderError('Visual request failed', code='upstream_error', retryable=True)
        return json.dumps({'answer': '最后一行 C2H4 为 0、1、1。', 'citations': [], 'insufficient_evidence': False})

    monkeypatch.setattr(provider, '_complete', complete)
    image = 'data:image/png;base64,ZmFrZQ=='
    if recover:
        assert 'C2H4' in provider.ask_with_image('表格最后一行是什么？', [sample_chunk()], image).answer
    else:
        with pytest.raises(ProviderError, match='Visual request failed'):
            provider.ask_with_image('表格最后一行是什么？', [sample_chunk()], image)
    assert len(seen) == 2
    assert all(call.get('image_data_url') == image for call in seen)


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


def test_truncated_outer_json_cannot_be_mistaken_for_nested_candidate():
    from app.providers.openai_compatible import parse_json_object
    with pytest.raises(ValueError):
        parse_json_object('{"candidates":[{"name":"File viewer"},')
    with pytest.raises(ValueError):
        parse_json_object('[{"name":"File viewer"}]')
