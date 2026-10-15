"""Official CLI integration is exercised with a temporary, deterministic process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.providers.base import ProviderError


def codex_profile(**extra):
    return dict(name='Codex subscription', provider_kind='codex', base_url='https://chatgpt.com',
                model='gpt-6.1-sol', api_key=None, wire_api='responses', reasoning_effort='high',
                timeout=60, max_concurrency=1, test_connection=False, **extra)


class AccountStub:
    def __init__(self):
        self.signed_in = False
        self.pending = False

    def status(self, **kwargs):
        return dict(available=True, authenticated=self.signed_in, pending=self.pending,
                    email='reader@example.com' if self.signed_in else None, plan='plus' if self.signed_in else None,
                    limits=[], login_url='https://auth.openai.com/authorize?state=fixture' if self.pending else None)

    def login(self):
        self.pending = True
        return self.status()

    def cancel_login(self):
        self.pending = False
        return self.status()

    def logout(self):
        self.signed_in = self.pending = False
        return self.status()

    def close(self):
        pass


def test_subscription_profile_needs_no_api_key_and_preserves_http_profiles(client):
    account = AccountStub()
    client.app.state.model_profiles.codex = account
    created = client.post('/api/settings/profiles', json=codex_profile())
    assert created.status_code == 201
    assert created.json()['provider_kind'] == 'codex'
    assert created.json()['api_key_configured'] is False
    assert client.get('/api/settings').json()['configured'] is False
    account.signed_in = True
    settings = client.get('/api/settings').json()
    assert settings['configured'] is True
    assert settings['translation_available'] is True
    assert settings['api_key_configured'] is False
    assert settings['provider'] == 'CodexSubscriptionProvider'
    assert 'api_key' not in json.loads(client.app.state.model_profiles.path.read_text())['profiles'][0]


def test_subscription_profile_ignores_supplied_api_key_and_uses_shared_capacity(client):
    client.app.state.model_profiles.codex = AccountStub()
    body = codex_profile()
    body['api_key'] = 'wrong-profile-secret'
    body['max_concurrency'] = 2
    result = client.post('/api/settings/profiles', json=body)
    assert result.status_code == 201
    assert result.json()['max_concurrency'] == 1
    assert 'wrong-profile-secret' not in client.app.state.model_profiles.path.read_text()


def test_account_endpoints_show_login_and_allow_cancel_and_logout(client):
    account = AccountStub()
    client.app.state.model_profiles.codex = account
    assert client.get('/api/settings/codex').json()['authenticated'] is False
    start = client.post('/api/settings/codex/login')
    assert start.status_code == 200
    assert start.json()['login_url'].startswith('https://auth.openai.com/')
    assert client.delete('/api/settings/codex/login').json()['pending'] is False
    account.signed_in = True
    assert client.get('/api/settings/codex').json()['email'] == 'reader@example.com'
    assert client.post('/api/settings/codex/logout').json()['authenticated'] is False


@pytest.fixture
def fake_cli(tmp_path):
    script = tmp_path / 'fake_codex.py'
    script.write_text('''import json,os,pathlib,sys,time
home=pathlib.Path(os.environ['CODEX_HOME'])
home.mkdir(parents=True,exist_ok=True)
def send(value):
 print(json.dumps(value),flush=True)
def account():
 path=home/'signed-in'
 return {'type':'chatgpt','email':'reader@example.com','planType':'plus','accessToken':'NEVER-RETURN-THIS'} if path.exists() else None
if 'app-server' in sys.argv:
 for line in sys.stdin:
  request=json.loads(line);method=request.get('method');identifier=request.get('id')
  if identifier is None:continue
  if method=='initialize':result={'userAgent':'fake'}
  elif method=='account/read':
   if (home/'notify-complete').exists():
    (home/'signed-in').touch();(home/'notify-complete').unlink()
    send({'method':'account/login/completed','params':{'loginId':'login-fixture','success':True}})
   if (home/'notify-failed').exists():
    (home/'notify-failed').unlink()
    send({'method':'account/login/completed','params':{'loginId':'login-fixture','success':False,'error':'NEVER-RETURN-THIS'}})
   result={'account':account(),'requiresOpenaiAuth':True,'accessToken':'NEVER-RETURN-THIS'}
  elif method=='account/login/start':result={'type':'chatgpt','loginId':'login-fixture','authUrl':'https://evil.example/authorize' if (home/'unsafe-url').exists() else 'https://auth.openai.com/authorize?state=fixture'}
  elif method=='account/login/cancel':result={}
  elif method=='account/logout':
   (home/'signed-in').unlink(missing_ok=True);result={}
  elif method=='account/rateLimits/read':result={'rateLimits':{'primary':{'usedPercent':25,'windowDurationMins':300,'resetsAt':1800000000,'accessToken':'NEVER-RETURN-THIS'},'secondary':None},'accessToken':'NEVER-RETURN-THIS'}
  else:result={}
  send({'id':identifier,'result':result})
else:
 prompt=sys.stdin.read()
 (home/'last-exec.json').write_text(json.dumps({'argv':sys.argv,'prompt':prompt,'env':{k:v for k,v in os.environ.items() if k.startswith(('OPENAI_','CODEX_','PAPER_READER_'))}}))
 mode=(home/'mode').read_text() if (home/'mode').exists() else 'ok'
 if mode=='timeout':time.sleep(10)
 if mode in ('quota','auth','invalid'):
  message={'quota':'usage limit reached; try again later','auth':'Unauthorized: please log in','invalid':'The model is not supported'}[mode]
  send({'type':'turn.failed','error':{'message':message+' NEVER-RETURN-THIS'}});sys.exit(1)
 if mode=='overflow':print('x'*1000001,flush=True);sys.exit(0)
 if mode=='incomplete':send({'type':'item.completed','item':{'type':'agent_message','text':'{"text":"{}"}'}});sys.exit(0)
 if mode=='recovered':send({'type':'error','message':'Reconnecting... 2/5 (temporary network error)'})
 send({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'text':'{"answer":"ok"}'})}})
 send({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':10}})
''', encoding='utf-8')
    return [sys.executable, str(script)]


def account_for(tmp_path, fake_cli):
    from app.providers.codex_account import CodexAccount
    return CodexAccount(tmp_path / 'account', command=fake_cli)


def test_official_account_rpc_filters_tokens_and_isolates_parent_environment(tmp_path, fake_cli, monkeypatch):
    monkeypatch.setenv('CODEX_API_KEY', 'parent-key')
    monkeypatch.setenv('OPENAI_API_KEY', 'parent-key')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://wrong.example')
    monkeypatch.setenv('PAPER_READER_MODEL_API_KEY', 'parent-key')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'parent-account'))
    account = account_for(tmp_path, fake_cli)
    try:
        assert account.status(refresh=True)['authenticated'] is False
        login = account.login()
        assert login['pending'] is True
        assert login['login_url'].startswith('https://auth.openai.com/')
        assert account.cancel_login()['pending'] is False
        (account.home / 'signed-in').touch()
        state = account.status(refresh=True)
        assert state['authenticated'] is True
        assert state['email'] == 'reader@example.com'
        assert state['limits'][0]['used_percent'] == 25
        assert 'NEVER-RETURN-THIS' not in json.dumps(state)
        environment = account.environment()
        assert environment['CODEX_HOME'] == str(account.home)
        assert not any(name in environment for name in ('CODEX_API_KEY', 'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'PAPER_READER_MODEL_API_KEY'))
        assert os.environ['CODEX_API_KEY'] == 'parent-key'
        assert account.logout()['authenticated'] is False
    finally:
        account.close()


def test_missing_cli_is_reported_without_launching_a_model(tmp_path, monkeypatch):
    from app.providers.codex_account import CodexAccount
    monkeypatch.setattr('app.providers.codex_account.shutil.which', lambda name: None)
    account = CodexAccount(tmp_path / 'no-cli')
    assert account.status()['available'] is False
    with pytest.raises(ProviderError) as caught:
        account.login()
    assert caught.value.code == 'codex_unavailable'


@pytest.mark.parametrize('outcome', ['complete', 'failed'])
def test_account_login_notifications_update_status_without_exposing_errors(tmp_path, fake_cli, outcome):
    account = account_for(tmp_path, fake_cli)
    try:
        assert account.login()['pending']
        (account.home / ('notify-' + outcome)).touch()
        state = account.status(refresh=True)
        assert state['pending'] is False
        assert state['authenticated'] is (outcome == 'complete')
        assert state['login_url'] is None
        assert 'NEVER-RETURN-THIS' not in json.dumps(state)
        if outcome == 'failed':
            assert state['error']
    finally:
        account.close()


def test_account_rejects_unofficial_login_urls(tmp_path, fake_cli):
    account = account_for(tmp_path, fake_cli)
    account.home.mkdir()
    (account.home / 'unsafe-url').touch()
    try:
        with pytest.raises(ProviderError) as caught:
            account.login()
        assert caught.value.code == 'codex_account_error'
        assert 'evil.example' not in str(caught.value)
        assert not account.status()['pending']
    finally:
        account.close()


@pytest.mark.parametrize('mode', ['overflow', 'incomplete'])
def test_subscription_rejects_oversized_and_unfinished_cli_output(tmp_path, fake_cli, mode):
    from app.providers.codex_subscription import CodexSubscriptionProvider
    account = account_for(tmp_path, fake_cli)
    account.home.mkdir()
    (account.home / 'signed-in').touch()
    (account.home / 'mode').write_text(mode)
    try:
        provider = CodexSubscriptionProvider(account=account, model='gpt-6.1-sol', timeout=5)
        with pytest.raises(ProviderError) as caught:
            provider.complete_json('JSON', {}, max_output_tokens=200)
        assert caught.value.code == ('invalid_response' if mode == 'overflow' else 'upstream_error')
    finally:
        account.close()


def test_codex_profiles_share_one_account_capacity_gate(client):
    from app.schemas import ModelProfileUpdate
    store = client.app.state.model_profiles
    store.codex = AccountStub()
    first = store.save(ModelProfileUpdate(**codex_profile()))
    second = store.save(ModelProfileUpdate(**codex_profile()))
    with store.provider(first['id'])._capacity():
        with pytest.raises(ProviderError) as caught:
            with store.provider(second['id'])._capacity():
                pytest.fail('Subscription requests must share account capacity')
        assert caught.value.code == 'local_capacity'


def test_subscription_exec_uses_stdin_no_tools_and_reports_real_usage(tmp_path, fake_cli, monkeypatch):
    from app.providers.codex_subscription import CodexSubscriptionProvider
    monkeypatch.setenv('CODEX_API_KEY', 'parent-key')
    account = account_for(tmp_path, fake_cli)
    account.home.mkdir(parents=True, exist_ok=True)
    (account.home / 'signed-in').touch()
    try:
        provider = CodexSubscriptionProvider(account=account, model='gpt-6.1-sol', reasoning_effort='high', timeout=30)
        result = provider.complete_json('Return JSON.', {'question':'private paper passage'}, max_output_tokens=200)
        assert result == {'answer':'ok'}
        assert provider.last_usage['input_tokens'] == 100
        assert provider.last_usage['output_tokens'] == 10
        captured = json.loads((account.home / 'last-exec.json').read_text())
        assert 'private paper passage' in captured['prompt']
        assert 'private paper passage' not in ' '.join(captured['argv'])
        assert '--ephemeral' in captured['argv'] and '--ignore-user-config' in captured['argv']
        assert 'shell_tool' in captured['argv'] and 'multi_agent' in captured['argv']
        assert 'model_provider="openai"' in captured['argv']
        assert 'web_search="disabled"' in captured['argv']
        assert captured['env'] == {'CODEX_HOME':str(account.home)}
    finally:
        account.close()


@pytest.mark.parametrize('mode,code,retryable', [('quota','rate_limit',True),('auth','authentication',False),('invalid','invalid_request',False)])
def test_subscription_errors_are_safe_and_use_existing_recovery_categories(tmp_path, fake_cli, mode, code, retryable):
    from app.providers.codex_subscription import CodexSubscriptionProvider
    account = account_for(tmp_path, fake_cli)
    account.home.mkdir(parents=True, exist_ok=True)
    (account.home / 'signed-in').touch()
    (account.home / 'mode').write_text(mode)
    try:
        provider = CodexSubscriptionProvider(account=account, model='gpt-6.1-sol', timeout=30)
        with pytest.raises(ProviderError) as caught:
            provider.complete_json('JSON', {}, max_output_tokens=200)
        assert caught.value.code == code
        assert caught.value.retryable is retryable
        assert 'NEVER-RETURN-THIS' not in str(caught.value)
    finally:
        account.close()


def test_subscription_timeout_terminates_the_cli_request(tmp_path, fake_cli):
    from app.providers.codex_subscription import CodexSubscriptionProvider
    account = account_for(tmp_path, fake_cli)
    account.home.mkdir(parents=True, exist_ok=True)
    (account.home / 'signed-in').touch()
    (account.home / 'mode').write_text('timeout')
    try:
        provider = CodexSubscriptionProvider(account=account, model='gpt-6.1-sol', timeout=1)
        with pytest.raises(ProviderError) as caught:
            provider.complete_json('JSON', {}, max_output_tokens=200)
        assert caught.value.code == 'transport_timeout'
        assert caught.value.retryable is True
    finally:
        account.close()


def test_recovered_cli_connection_warning_does_not_discard_a_completed_answer(tmp_path, fake_cli):
    from app.providers.codex_subscription import CodexSubscriptionProvider
    account = account_for(tmp_path, fake_cli)
    account.home.mkdir()
    (account.home / 'signed-in').touch()
    (account.home / 'mode').write_text('recovered')
    try:
        provider = CodexSubscriptionProvider(account=account, model='gpt-6.1-sol', timeout=5)
        assert provider.complete_json('JSON', {}, max_output_tokens=200) == {'answer': 'ok'}
        assert provider.last_usage['output_tokens'] == 10
    finally:
        account.close()


def test_account_shutdown_stops_its_inflight_exec_child(tmp_path, fake_cli, monkeypatch):
    from app.providers.codex_subscription import CodexSubscriptionProvider
    account = account_for(tmp_path, fake_cli)
    account.home.mkdir()
    (account.home / 'signed-in').touch()
    (account.home / 'mode').write_text('timeout')
    provider = CodexSubscriptionProvider(account=account, model='gpt-6.1-sol', timeout=3)
    children = []
    original = account.spawn
    def spawn(args, **kwargs):
        process = original(args, **kwargs)
        if 'exec' in args:
            children.append(process)
        return process
    monkeypatch.setattr(account, 'spawn', spawn)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(provider.complete_json, 'JSON', {}, max_output_tokens=200)
        try:
            deadline = time.monotonic() + 3
            while not children and time.monotonic() < deadline:
                time.sleep(.01)
            assert children
            account.close()
            assert children[0].poll() is not None
            with pytest.raises(ProviderError):
                future.result(timeout=2)
        finally:
            account.close()


@pytest.mark.parametrize('failure_mode,expected_code', [('quota', 'rate_limit'), ('account-timeout', 'transport_timeout')])
def test_subscription_quota_can_route_to_a_saved_http_backup(client, tmp_path, fake_cli, monkeypatch, failure_mode, expected_code):
    from app.providers import get_model_provider
    from app.providers.profiles import current_store
    from app.services.model_calls import json_call
    account = account_for(tmp_path, fake_cli)
    account.home.mkdir(parents=True, exist_ok=True)
    (account.home / 'signed-in').touch()
    (account.home / 'mode').write_text('quota')
    store = client.app.state.model_profiles
    store.codex.close()
    store.codex = account
    if failure_mode == 'account-timeout':
        monkeypatch.setattr(account, 'status', lambda **kwargs: dict(available=True, authenticated=False,
            pending=False, error='Codex account service timed out', error_code='transport_timeout', retryable=True))
    subscription = client.post('/api/settings/profiles',json=codex_profile()).json()
    backup = client.post('/api/settings/profiles',json=dict(name='Relay',base_url='https://relay.example/v1',model='backup',api_key='fixture-secret',test_connection=False)).json()
    client.put('/api/settings/routing',json=dict(active_id=subscription['id'],fallback_ids=[backup['id']],auto_fallback=True))
    original = store.provider
    def build(identifier):
        provider = original(identifier)
        if identifier == backup['id']:
            provider._transport = httpx.MockTransport(lambda request: httpx.Response(200,json={'choices':[{'message':{'content':'{"answer":"backup"}'}}]}))
        return provider
    monkeypatch.setattr(store,'provider',build)
    token = current_store.set(store)
    try:
        assert get_model_provider().configured is True
        result = json_call(client.app.state.database,get_model_provider(),'JSON',{},'subscription-fallback')
        assert result.data == {'answer':'backup'}
        assert result.provenance['profile_id'] == backup['id']
        assert result.attempts[0].provenance['failure']['code'] == expected_code
        if failure_mode == 'account-timeout':
            assert result.attempts[0].request_sent is False
    finally:
        current_store.reset(token)
