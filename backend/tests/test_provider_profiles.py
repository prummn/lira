from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from app.providers.base import ProviderError


def connection(name='Official', **extra):
    return dict(name=name, base_url='https://model.example/v1', model='research-model',
                api_key=f'{name}-secret', wire_api='responses', test_connection=False, **extra)


def test_migrates_existing_connection_and_keeps_secrets_on_server(client, monkeypatch):
    monkeypatch.setenv('PAPER_READER_MODEL_API_KEY', 'legacy-secret')
    monkeypatch.setenv('PAPER_READER_MODEL_BASE_URL', 'https://legacy.example/v1')
    monkeypatch.setenv('PAPER_READER_MODEL_NAME', 'legacy-model')
    result = client.get('/api/settings/profiles')
    assert result.status_code == 200
    body = result.json()
    assert len(body['profiles']) == 1
    assert body['active_id'] == body['profiles'][0]['id']
    assert body['profiles'][0]['model'] == 'legacy-model'
    assert body['profiles'][0]['api_key_configured'] is True
    assert 'legacy-secret' not in result.text


@pytest.mark.parametrize('explicit', [True, False])
def test_openai_environment_key_migrates_only_with_explicit_application_settings(client, monkeypatch, explicit):
    monkeypatch.setenv('OPENAI_API_KEY', 'shell-secret')
    if explicit:
        monkeypatch.setenv('PAPER_READER_MODEL_BASE_URL', 'https://explicit.example/v1')
    before = client.get('/api/settings').json()
    state = client.get('/api/settings/profiles').json()
    assert before['configured'] is explicit
    assert bool(state['profiles']) is explicit
    assert client.get('/api/settings').json()['configured'] is explicit
    assert 'shell-secret' not in json.dumps(state)


def test_profile_crud_switch_and_key_isolation(client):
    first = client.post('/api/settings/profiles', json=connection()).json()
    assert 'id' in first
    second = client.post('/api/settings/profiles', json=connection('Relay', timeout=120)).json()
    assert second['id'] != first['id']
    assert client.get('/api/settings').json()['profile_id'] == first['id']
    switched = client.put('/api/settings/routing', json={'active_id': second['id'], 'fallback_ids': [first['id']], 'auto_fallback': True})
    assert switched.status_code == 200
    assert client.get('/api/settings').json()['profile_id'] == second['id']
    update = connection('Relay renamed', timeout=130)
    update['api_key'] = None
    assert client.put(f"/api/settings/profiles/{second['id']}", json=update).status_code == 200
    store = client.app.state.model_profiles
    assert store.provider(second['id'])._api_key == 'Relay-secret'
    assert store.provider(first['id'])._api_key == 'Official-secret'
    assert 'secret' not in client.get('/api/settings/profiles').text
    assert client.delete(f"/api/settings/profiles/{first['id']}").status_code == 200
    assert client.get('/api/settings/profiles').json()['fallback_ids'] == []


def test_new_profile_cannot_reuse_another_profiles_key(client):
    client.post('/api/settings/profiles', json=connection())
    payload = connection('Missing')
    payload['api_key'] = None
    assert client.post('/api/settings/profiles', json=payload).status_code == 422
    assert len(client.get('/api/settings/profiles').json()['profiles']) == 1


def test_restart_retains_profiles_and_failed_save_does_not_change_active_state(client, monkeypatch):
    from app.providers.profiles import ProfileStore
    profile = client.post('/api/settings/profiles', json=connection()).json()
    store = client.app.state.model_profiles
    restored = ProfileStore(store.path)
    assert restored.public()['active_id'] == profile['id']
    assert restored.provider(profile['id'])._api_key == 'Official-secret'
    def fail(*args):
        raise OSError('disk unavailable')
    monkeypatch.setattr(store, '_write', fail)
    response = client.put('/api/settings/routing', json={'active_id': None, 'fallback_ids': [], 'auto_fallback': False})
    assert response.status_code == 500
    assert store.public()['active_id'] == profile['id']


def test_profiles_validate_route_and_options_without_altering_saved_state(client):
    first = client.post('/api/settings/profiles', json=connection()).json()
    for body in ({'active_id': 'absent'}, {'active_id': first['id'], 'fallback_ids': [first['id']]},
                 {'active_id': first['id'], 'fallback_ids': ['absent']}):
        assert client.put('/api/settings/routing', json=body).status_code == 422
    assert client.post('/api/settings/profiles', json=connection('Bad', max_concurrency=0)).status_code == 422


def test_request_switch_is_visible_at_next_analysis_boundary_and_cache_tracks_actual_provider(client, monkeypatch):
    from app.providers import get_model_provider
    from app.providers.profiles import current_store
    from app.services.model_calls import json_call
    first = client.post('/api/settings/profiles', json=connection()).json()
    second = client.post('/api/settings/profiles', json=connection('Relay', json_mode='none')).json()
    store = client.app.state.model_profiles
    original = store.provider
    seen = []
    def build(profile_id):
        provider = original(profile_id)
        def respond(request):
            seen.append(profile_id)
            return httpx.Response(200, json={'status': 'completed', 'model': provider.model,
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'source': profile_id})}]}]})
        provider._transport = httpx.MockTransport(respond)
        return provider
    monkeypatch.setattr(store, 'provider', build)
    token = current_store.set(store)
    try:
        provider = get_model_provider()
        from app.providers.harness import analysis_fingerprint
        original_fingerprint = analysis_fingerprint(provider, [])
        db = client.app.state.database
        one = json_call(db, provider, 'JSON', {}, 'fixture')
        assert one.provenance['profile_id'] == first['id']
        client.put('/api/settings/routing', json={'active_id': second['id']})
        assert analysis_fingerprint(provider, []) == original_fingerprint
        assert analysis_fingerprint(get_model_provider(), []) != original_fingerprint
        two = json_call(db, provider, 'JSON', {}, 'fixture')
        assert two.data['source'] == second['id']
        assert not two.cached
        assert json_call(db, provider, 'JSON', {}, 'fixture').cached
        assert seen == [first['id'], second['id']]
    finally:
        current_store.reset(token)


@pytest.mark.parametrize('status,uses_backup', [(429, True), (503, True), (401, False), (400, False)])
def test_explicit_fallback_only_for_transient_failures(client, monkeypatch, status, uses_backup):
    from app.providers import get_model_provider
    from app.providers.profiles import current_store
    from app.services.model_calls import json_call
    first = client.post('/api/settings/profiles', json=connection()).json()
    second = client.post('/api/settings/profiles', json=connection('Relay')).json()
    client.put('/api/settings/routing', json={'active_id': first['id'], 'fallback_ids': [second['id']], 'auto_fallback': True})
    store = client.app.state.model_profiles
    original = store.provider
    seen = []
    def build(profile_id):
        provider = original(profile_id)
        def respond(request):
            seen.append(profile_id)
            if profile_id == first['id']:
                return httpx.Response(status)
            return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]})
        provider._transport = httpx.MockTransport(respond)
        return provider
    monkeypatch.setattr(store, 'provider', build)
    token = current_store.set(store)
    try:
        provider = get_model_provider()
        if uses_backup:
            result = json_call(client.app.state.database, provider, 'JSON', {}, 'fallback')
            assert result.provenance['profile_id'] == second['id']
            assert len(result.attempts) == 1
            assert result.attempts[0].provenance['failure']['code'] in {'rate_limit', 'upstream_error'}
        else:
            with pytest.raises(ProviderError):
                json_call(client.app.state.database, provider, 'JSON', {}, 'fallback')
        assert seen == [first['id']] + ([second['id']] if uses_backup else [])
    finally:
        current_store.reset(token)


def test_capacity_gate_covers_different_instances_of_same_profile(client):
    profile = client.post('/api/settings/profiles', json=connection(max_concurrency=1)).json()
    store = client.app.state.model_profiles
    entered, release, second_entered = Event(), Event(), Event()
    def run(first):
        with store.capacity(profile['id'], 1):
            (entered if first else second_entered).set()
            assert release.wait(3)
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(run, True)
        assert entered.wait(1)
        b = pool.submit(run, False)
        assert not second_entered.wait(.1)
        release.set()
        a.result()
        b.result()
    assert second_entered.is_set()


def test_legacy_settings_endpoints_update_and_remove_active_profile(client):
    profile = client.post('/api/settings/profiles', json=connection()).json()
    result = client.put('/api/settings/model', json={k:v for k,v in connection('Changed').items() if k!='name'})
    assert result.status_code == 200
    assert client.app.state.model_profiles.provider(profile['id'])._api_key == 'Changed-secret'
    assert client.delete('/api/settings/model').status_code == 200
    assert client.get('/api/settings').json()['configured'] is False
    client.post('/api/settings/profiles', json=connection('Inactive'))
    assert client.get('/api/settings').json()['configured'] is True
    active = client.get('/api/settings/profiles').json()['active_id']
    client.post('/api/settings/profiles', json=connection('Other'))
    client.delete(f'/api/settings/profiles/{active}')
    result = client.put('/api/settings/model', json={k:v for k,v in connection('Recovered').items() if k!='name'})
    assert result.status_code == 200
    assert result.json()['configured'] is True


def test_connection_test_does_not_block_existing_route_or_overwrite_concurrent_change(client, monkeypatch):
    from app.schemas import ModelProfileUpdate, ModelRoutingUpdate
    from app.providers.openai_compatible import OpenAICompatibleProvider
    first = client.post('/api/settings/profiles', json=connection()).json()
    second = client.post('/api/settings/profiles', json=connection('Relay')).json()
    store = client.app.state.model_profiles
    entered, release = Event(), Event()
    def test_connection(self):
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(OpenAICompatibleProvider, 'test_connection', test_connection)
    payload = ModelProfileUpdate(**{**connection('Edited'), 'test_connection': True})
    with ThreadPoolExecutor(2) as pool:
        saving = pool.submit(store.save, payload, first['id'])
        assert entered.wait(1)
        switching = pool.submit(store.route, ModelRoutingUpdate(active_id=second['id']))
        try:
            assert switching.result(timeout=.3)['active_id'] == second['id']
        finally:
            release.set()
        saving.result()
    assert store.public()['active_id'] == second['id']


@pytest.mark.parametrize('setting,value', [('TIMEOUT', 'invalid'), ('WIRE_API', 'invalid'), ('BASE_URL', 'not a url')])
def test_invalid_legacy_settings_remain_a_configuration_error_without_persisting(client, monkeypatch, setting, value):
    monkeypatch.setenv('PAPER_READER_MODEL_API_KEY', 'legacy-secret')
    monkeypatch.setenv('PAPER_READER_MODEL_' + setting, value)
    result = client.get('/api/settings')
    assert result.status_code == 200
    assert result.json()['configured'] is False
    assert result.json()['configuration_error']
    assert not client.app.state.model_profiles.path.exists()
    profiles = client.get('/api/settings/profiles')
    assert profiles.status_code == 200
    assert profiles.json()['configuration_error']
    assert profiles.json()['profiles'] == []
    assert client.post('/api/settings/profiles', json=connection()).status_code == 201
    assert client.get('/api/settings').json()['configured'] is True


def test_local_capacity_uses_backup_without_counting_a_remote_failure(client, monkeypatch):
    from app.providers import get_model_provider
    from app.providers.profiles import current_store
    from app.providers.harness import _usage
    from app.services.model_calls import json_call
    from contextlib import contextmanager
    first = client.post('/api/settings/profiles', json=connection()).json()
    second = client.post('/api/settings/profiles', json=connection('Relay')).json()
    client.put('/api/settings/routing', json={'active_id': first['id'], 'fallback_ids': [second['id']], 'auto_fallback': True})
    store = client.app.state.model_profiles
    original = store.provider
    @contextmanager
    def busy():
        raise ProviderError('Busy', 503, code='local_capacity', retryable=True, diagnostics={'request_sent': False})
        yield
    def build(profile_id):
        provider = original(profile_id)
        if profile_id == first['id']:
            provider._capacity = busy
        provider._transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
            'status': 'completed', 'usage': {'input_tokens': 10, 'output_tokens': 5},
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]}))
        return provider
    monkeypatch.setattr(store, 'provider', build)
    token = current_store.set(store)
    try:
        result = json_call(client.app.state.database, get_model_provider(), 'JSON', {}, 'capacity')
        report = _usage([*result.attempts, result])
        assert result.provenance['profile_id'] == second['id']
        assert report['remote_calls'] == 1
        assert report['unknown_usage_calls'] == 0
        assert report['cache_hits'] == 0
        assert report['input_tokens'] == 10
    finally:
        current_store.reset(token)
