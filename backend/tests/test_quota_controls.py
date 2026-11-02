from app.research_schemas import ResearchSettings
from app.services.research_policy import quota_decision
import time


def test_quota_patch_preserves_other_settings_and_persists(client):
    worker = client.app.state.research_worker
    worker.stop()
    worker.settings(ResearchSettings(idle_seconds=321, calls_per_hour=17, maintenance_enabled=True))
    worker._retry_at = time.time() + 600
    response = client.patch('/api/research/quota-policy', json={'long_reserve': 0})
    assert response.status_code == 200
    saved = response.json()
    assert saved['long_reserve'] == 0
    assert saved['idle_seconds'] == 321 and saved['calls_per_hour'] == 17
    assert saved['maintenance_enabled'] and not saved['enabled']
    assert saved['start_remaining'] == 50 and saved['stop_remaining'] == 35
    assert worker.settings().long_reserve == 0 and worker._retry_at == 0
    assert worker._wake.is_set()


def test_zero_reserve_allows_remaining_quota_but_never_exhausted_quota(client):
    response = client.patch('/api/research/quota-policy', json={'start_remaining': 1, 'stop_remaining': 0, 'long_reserve': 0})
    assert response.status_code == 200
    settings = client.app.state.research_worker.settings()
    window = {'used_percent': 77, 'window_minutes': 10080, 'resets_at': time.time() + 86400}
    assert quota_decision([window], age=0, running=True, stop_remaining=settings.stop_remaining, long_reserve=settings.long_reserve)['allowed']
    window['used_percent'] = 100
    assert not quota_decision([window], age=0, running=True, stop_remaining=0, long_reserve=0)['allowed']


def test_invalid_quota_patch_is_atomic_and_cannot_change_unrelated_controls(client):
    for data in ({'long_reserve': -1}, {'long_reserve': 101}, {'start_remaining': 20, 'stop_remaining': 30}, {'enabled': True}, {'long_reserve': None}):
        assert client.patch('/api/research/quota-policy', json=data).status_code == 422
        assert client.app.state.research_worker.settings() == ResearchSettings()
