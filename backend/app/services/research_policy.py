"""Quota decisions use reported durations and reset times, never plan names."""
import math
import time
from datetime import datetime, timedelta


def observe_budget(ledger, windows, *, now=None, day=None, reserve=30):
    """Account-wide observed growth limits background work; never bill a request.

    Ledgers use official bucket identity, not a selectable model profile. Daily
    allowances are fixed at first observation and can only shrink until tomorrow.
    """
    now = time.time() if now is None else now
    local = datetime.fromtimestamp(now).astimezone()
    day = day or local.date().isoformat()
    tomorrow = datetime.combine(local.date()+timedelta(days=1), datetime.min.time()).astimezone().timestamp()
    ledger = {key: dict(value) for key, value in ledger.items()}
    decisions = []
    for window in windows:
        used, minutes, reset = [window.get(k) for k in ('used_percent', 'window_minutes', 'resets_at')]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in (used, minutes, reset)):
            continue  # quota_decision separately rejects unknown windows
        if minutes < 1440 or reset <= now or not 0 <= used <= 100:
            continue
        key = f"{window.get('limit_id', 'codex')}:{window.get('name', '')}:{minutes:g}"
        record = ledger.get(key)
        # A changed reset estimate alone is not a new allowance. Only expiry
        # followed by a new official period can retire the old high-water mark.
        new_period = record is None or (now >= record['resets_at'] and
                                        reset-record['resets_at'] > min(600, minutes*30))
        days = max(1, math.ceil((reset-now)/86400))
        if new_period or record['day'] != day:
            peak = used if new_period else max(used, record['peak'])
            allowance = max(0, 100-reserve-peak)/days
            record = dict(day=day, baseline=peak, peak=peak, allowance=allowance, resets_at=reset)
        else:
            record['peak'] = max(used, record['peak'])
            record['allowance'] = min(record['allowance'], max(0, 100-reserve-record['baseline'])/days)
            record['resets_at'] = min(record['resets_at'], reset)
        ledger[key] = record
        spent = record['peak'] - record['baseline']
        allowed = spent < record['allowance']
        decisions.append(dict(allowed=allowed, reason='ready' if allowed else 'daily_budget',
            allowance=round(record['allowance'], 2), observed_use=round(spent, 2),
            remaining=round(max(0, record['allowance']-spent), 2),
            resumes_at=min(tomorrow, reset), resets_at=reset, day=day))
    if not decisions:
        return ledger, dict(allowed=True, reason='short_window_only')
    # The most constrained bucket controls all work, just like quota_decision.
    decision = min(decisions, key=lambda d: (d['allowed'], d['remaining']))
    return ledger, decision


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
        if remaining <= reserve:
            return denied('quota_reserve')
    return {'allowed': True, 'reason': 'ready'}
