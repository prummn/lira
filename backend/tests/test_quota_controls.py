from app.research_schemas import ResearchSettings
from app.services.research_policy import quota_decision
import time
import pytest


def test_quota_patch_preserves_other_settings_and_persists(client):
    worker = client.app.state.research_worker
    worker.stop()
    worker.settings(ResearchSettings.model_validate({'idle_seconds':321, 'calls_per_hour':17,
                                                     'maintenance_enabled':True}))
    worker._retry_at = time.time() + 600
    worker._research_pool.wake_event.clear()
    worker._translation_pool.wake_event.clear()
    response = client.patch('/api/research/quota-policy', json={'long_reserve': 0})
    assert response.status_code == 200
    saved = response.json()
    assert saved['long_reserve'] == 0
    assert saved['idle_seconds'] == 321 and 'calls_per_hour' not in saved
    assert saved['maintenance_enabled'] and not saved['enabled']
    assert saved['start_remaining'] == 50 and saved['stop_remaining'] == 35
    assert worker.settings().long_reserve == 0 and worker._retry_at == 0
    assert worker._research_pool.wake_event.is_set()
    assert worker._translation_pool.wake_event.is_set()


@pytest.mark.parametrize('short_used,long_used', [(0, 77), (0, 100), (100, 0), (100, 100)])
def test_zero_reserve_patch_disables_local_gate_and_positive_reserves_restore_it(client, short_used, long_used):
    response = client.patch('/api/research/quota-policy', json={'start_remaining': 1, 'stop_remaining': 0, 'long_reserve': 0})
    assert response.status_code == 200
    worker = client.app.state.research_worker
    windows = [dict(used_percent=short_used, window_minutes=300, resets_at=time.time() + 3600),
               dict(used_percent=long_used, window_minutes=10080, resets_at=time.time() + 86400)]

    def decision():
        settings = worker.settings()
        return quota_decision(windows, age=0, running=True,
                              stop_remaining=settings.stop_remaining, long_reserve=settings.long_reserve)

    # Zero removes the application's reserve gate, including a reported 0%
    # balance; actual provider limit errors remain authoritative.
    assert decision() == {'allowed': True, 'reason': 'ready'}
    response = client.patch('/api/research/quota-policy', json={'start_remaining': 50, 'stop_remaining': 35, 'long_reserve': 30})
    assert response.status_code == 200
    assert decision() == {'allowed': False, 'reason': 'quota_reserve'}


def test_invalid_quota_patch_is_atomic_and_cannot_change_unrelated_controls(client):
    for data in ({'long_reserve': -1}, {'long_reserve': 101}, {'start_remaining': 20, 'stop_remaining': 30}, {'enabled': True}, {'long_reserve': None}):
        assert client.patch('/api/research/quota-policy', json=data).status_code == 422
        assert client.app.state.research_worker.settings() == ResearchSettings()
