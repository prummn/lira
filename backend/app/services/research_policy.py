"""Quota decisions use reported durations and reset times, never plan names."""
import math
import time


def quota_decision(windows, *, age, running=False, now=None, start_remaining=50, stop_remaining=35, long_reserve=30):
    def denied(reason):
        return {'allowed': False, 'reason': reason}
    if not windows or age > 120:
        return denied('quota_unknown')
    now = time.time() if now is None else now
    for window in windows:
        values = [window.get('used_percent'), window.get('window_minutes'), window.get('resets_at')]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in values):
            return denied('quota_unknown')
        used, minutes, reset = values
        if not 0 <= used <= 100 or minutes <= 0 or reset <= now:
            return denied('quota_stale')
        remaining = 100 - used
        reserve = long_reserve if minutes >= 1440 else (stop_remaining if running else start_remaining)
        # Zero explicitly disables this application's reserve gate. Reported
        # exhaustion is still subject to the provider's actual request limits.
        if reserve > 0 and remaining <= reserve:
            return denied('quota_reserve')
    return {'allowed': True, 'reason': 'ready'}
