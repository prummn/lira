import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.providers.base import ProviderError


def test_policy_requires_fresh_known_windows_and_keeps_reserve():
    from app.services.research_policy import quota_decision
    windows = [{'name': 'primary', 'used_percent': 40, 'window_minutes': 300, 'resets_at': 2000},
               {'name': 'secondary', 'used_percent': 60, 'window_minutes': 10080, 'resets_at': 3000}]
    assert quota_decision(windows, age=0, running=False, now=1000)['allowed']
    assert not quota_decision(windows, age=121, running=False, now=1000)['allowed']
    assert not quota_decision([], age=0, running=False, now=1000)['allowed']
    windows[1]['used_percent'] = 75
    assert not quota_decision(windows, age=0, running=False, now=1000)['allowed']
    windows[1]['used_percent'] = 60
    windows[0]['used_percent'] = 55
    assert not quota_decision(windows, age=0, running=False, now=1000)['allowed']
    assert quota_decision(windows, age=0, running=True, now=1000)['allowed']
    windows[0]['used_percent'] = 66
    assert not quota_decision(windows, age=0, running=True, now=1000)['allowed']


def test_dynamic_windows_are_not_named_five_hours_and_unknown_expiry_blocks():
    from app.services.research_policy import quota_decision
    window = dict(name='secondary', used_percent=20, window_minutes=120, resets_at=2000)
    assert quota_decision([window], age=0, now=1000)['allowed']
    window['resets_at'] = 999
    assert not quota_decision([window], age=0, now=1000)['allowed']
    window['resets_at'] = None
    assert not quota_decision([window], age=0, now=1000)['allowed']


@pytest.mark.parametrize('running', [False, True])
@pytest.mark.parametrize('short_used,long_used', [(0, 100), (100, 0), (100, 100)])
def test_zero_reserve_disables_that_window_reserve_gate(running, short_used, long_used):
    from app.services.research_policy import quota_decision
    windows = [dict(used_percent=short_used, window_minutes=300, resets_at=2000),
               dict(used_percent=long_used, window_minutes=10080, resets_at=3000)]
    result = quota_decision(windows, age=0, now=1000, running=running,
                           start_remaining=50, stop_remaining=0, long_reserve=0)
    # Starting still requires the configured short-window starting balance.
    assert result['allowed'] is (running or short_used == 0)


def test_zero_long_reserve_does_not_disable_positive_short_reserve():
    from app.services.research_policy import quota_decision
    windows = [dict(used_percent=65, window_minutes=300, resets_at=2000),
               dict(used_percent=100, window_minutes=10080, resets_at=3000)]
    assert quota_decision(windows, age=0, now=1000, running=True,
                          stop_remaining=35, long_reserve=0)['reason'] == 'quota_reserve'


def test_foreground_preempts_background_without_account_overlap(tmp_path):
    from app.providers.profiles import ProfileStore
    from app.providers.priority import background_call, check_background
    store = ProfileStore(tmp_path / 'models.json')
    store.set_codex_concurrency(1)
    started, stopped = threading.Event(), threading.Event()
    def background():
        with background_call(store.priority):
            with store.capacity('codex-subscription', 1):
                started.set()
                try:
                    while True:
                        check_background()
                        stopped.wait(.02)
                except ProviderError as error:
                    assert error.code == 'background_preempted'
                finally:
                    stopped.set()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(background)
        assert started.wait(2)
        begin = time.monotonic()
        with store.capacity('codex-subscription', 1):
            assert stopped.is_set()
            assert store._in_use['codex-subscription'] == 1
        assert time.monotonic() - begin < 2
        future.result(2)


def test_multiple_quota_buckets_preserve_identity():
    from app.providers.codex_account import CodexAccount
    windows = CodexAccount._limits({'rateLimits': {'primary': {'usedPercent': 0}},
        'rateLimitsByLimitId': {'codex': {'limitId': 'codex', 'primary': {
            'usedPercent': 34, 'windowDurationMins': 300, 'resetsAt': 2000}},
            'extra': {'limitId': 'extra', 'secondary': {
                'usedPercent': 70, 'windowDurationMins': 10080, 'resetsAt': 3000}}}})
    assert [(w['limit_id'], w['used_percent']) for w in windows] == [('codex', 34), ('extra', 70)]


def test_foreground_request_stays_prioritized_even_with_zero_idle_delay(tmp_path):
    from app.providers.profiles import ProfileStore
    store = ProfileStore(tmp_path/'models.json')
    store.set_codex_concurrency(1)
    assert store.priority.idle(0)
    with store.capacity('codex-subscription', 1):
        assert not store.priority.idle(0)
    assert store.priority.idle(0)


def test_unknown_reported_window_cannot_disappear_from_policy():
    from app.providers.codex_account import CodexAccount
    from app.services.research_policy import quota_decision
    limits = CodexAccount._limits({'rateLimits': {
        'primary': {'usedPercent': None, 'windowDurationMins': 300, 'resetsAt': 2000},
        'secondary': {'usedPercent': 1, 'windowDurationMins': 10080, 'resetsAt': 3000}}})
    assert not quota_decision(limits, age=0, now=1000)['allowed']
