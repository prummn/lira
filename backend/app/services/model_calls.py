"""Short-lived transactions wrap request-exact cache lookup and persistence."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy import delete
from ..db import Database
from ..models import ModelCallCache
from ..providers.usage import sanitize_usage


@dataclass(frozen=True)
class CallResult:
    data: dict
    usage: dict
    cached: bool
    model: str


def request_signature(provider, system: str, payload: dict, operation: str, max_output_tokens: int = 6000, reasoning_effort: str | None = None) -> str:
    resolve_effort = getattr(provider, 'effective_reasoning_effort', None)
    effort = resolve_effort(reasoning_effort) if callable(resolve_effort) else reasoning_effort or getattr(provider, 'reasoning_effort', None)
    value = {'operation': operation, 'system': system, 'payload': payload, 'max_output_tokens': max_output_tokens,
        'provider': provider.name, 'base_url': getattr(provider, 'base_url', ''), 'model': getattr(provider, 'model', ''),
        'wire_api': getattr(provider, 'wire_api', ''), 'reasoning_effort': effort,
        'completion_parameter': getattr(provider, 'completion_parameter', ''), 'json_mode': getattr(provider, 'json_mode', '')}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def cached_call(database: Database, provider, system: str, payload: dict, operation: str, max_output_tokens: int = 6000, reasoning_effort: str | None = None) -> CallResult | None:
    key = request_signature(provider, system, payload, operation, max_output_tokens, reasoning_effort)
    with database.sessions() as session:
        cached = session.get(ModelCallCache, key)
        if cached:
            saved = json.loads(cached.usage_json)
            return CallResult(json.loads(cached.response_json), {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0, 'saved_usage': saved}, True, cached.model)


def cache_validated_call(database: Database, provider, system: str, payload: dict, operation: str,
                        result: CallResult, max_output_tokens: int = 6000, reasoning_effort: str | None = None) -> None:
    """Save a locally revalidated correction under a distinct pipeline operation."""
    from datetime import datetime, timezone
    key = request_signature(provider, system, payload, operation, max_output_tokens, reasoning_effort)
    with database.sessions() as session:
        session.execute(insert(ModelCallCache).values(key=key, operation=operation[:100],
            response_json=json.dumps(result.data, ensure_ascii=False), usage_json=json.dumps(result.usage),
            model=result.model[:200], created_at=datetime.now(timezone.utc)).on_conflict_do_nothing(index_elements=['key']))
        session.commit()


def json_call(database: Database, provider, system: str, payload: dict, operation: str, max_output_tokens: int = 6000, reasoning_effort: str | None = None) -> CallResult:
    cached = cached_call(database, provider, system, payload, operation, max_output_tokens, reasoning_effort)
    if cached:
        return cached
    key = request_signature(provider, system, payload, operation, max_output_tokens, reasoning_effort)
    # No ORM transaction or connection is held during the potentially long network call.
    data = provider.complete_json(system, payload, max_output_tokens=max_output_tokens, reasoning_effort=reasoning_effort)
    usage = sanitize_usage(getattr(provider, 'last_usage', {}))
    model = getattr(provider, 'response_model', None) or getattr(provider, 'model', '')
    from datetime import datetime, timezone
    with database.sessions() as session:
        session.execute(insert(ModelCallCache).values(key=key, operation=operation[:100], response_json=json.dumps(data, ensure_ascii=False), usage_json=json.dumps(usage), model=model[:200], created_at=datetime.now(timezone.utc)).on_conflict_do_nothing(index_elements=['key']))
        session.commit()
    return CallResult(data, usage, False, model)


def evict_call(database: Database, provider, system: str, payload: dict, operation: str, max_output_tokens: int = 6000, reasoning_effort: str | None = None) -> None:
    """A syntactically readable response is reusable only after its consumer validates it."""
    key = request_signature(provider, system, payload, operation, max_output_tokens, reasoning_effort)
    with database.sessions() as session:
        session.execute(delete(ModelCallCache).where(ModelCallCache.key == key))
        session.commit()
