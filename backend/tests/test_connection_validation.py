import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from app.providers.openai_compatible import OpenAICompatibleProvider
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
        assert payload.get('max_output_tokens', payload.get('max_completion_tokens')) >= 16
        if wire == 'responses':
            return httpx.Response(200, json={'status': 'completed', 'output': [
                {'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}]})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'OK'}}]})
    provider = OpenAICompatibleProvider(api_key='fixture-secret', model='gpt-6.1-sol',
        wire_api=wire, reasoning_effort=effort, transport=httpx.MockTransport(respond))
    provider.test_connection()
    assert len(requests) == 1


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
