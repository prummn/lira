"""Atomic, server-only connection profiles and shared per-profile capacity gates."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

from .base import ProviderError
from .openai_compatible import OpenAICompatibleProvider
from .codex_account import CodexAccount

current_store: ContextVar[ProfileStore | None] = ContextVar('model_profile_store', default=None)


class ProfileStore:
    def __init__(self, path: Path):
        self.path = path
        self.codex = CodexAccount(path.with_name(path.name + '.codex'))
        self._lock = threading.RLock()
        self._condition = threading.Condition()
        self._in_use: dict[str, int] = {}
        self._background_use: dict[str, int] = {}
        self._waiting: dict[str, list] = {}
        self._adaptive: dict[str, dict] = {}
        from .priority import ResearchPriority
        self.priority = ResearchPriority()
        self._state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if self._state is not None and (self._state.get('version') != 1 or not isinstance(self._state.get('profiles'), list)):
            raise ValueError('模型配置文件格式无效')

    def _initial(self) -> dict:
        # Read only explicitly configured application credentials. No implicit
        # migration of unrelated OPENAI_API_KEY shell variables.
        key = self._legacy_key()
        profiles = []
        if key:
            from ..schemas import ModelProfileUpdate
            profile = ModelProfileUpdate(name='当前配置', api_key=key,
                base_url=os.getenv('PAPER_READER_MODEL_BASE_URL', 'https://api.openai.com/v1'),
                model=os.getenv('PAPER_READER_MODEL_NAME', 'gpt-4.1-mini'),
                wire_api=os.getenv('PAPER_READER_MODEL_WIRE_API', 'chat_completions'),
                reasoning_effort=os.getenv('PAPER_READER_MODEL_REASONING_EFFORT', 'disabled'),
                timeout=float(os.getenv('PAPER_READER_MODEL_TIMEOUT', '600')),
                completion_parameter=os.getenv('PAPER_READER_MODEL_COMPLETION_PARAMETER', 'max_completion_tokens'),
                json_mode=os.getenv('PAPER_READER_MODEL_JSON_MODE', 'json_object'), test_connection=False)
            self._build(profile.model_dump())
            profiles.append({'id': 'profile-' + uuid.uuid4().hex, **profile.model_dump(exclude={'test_connection'})})
        return {'version': 1, 'profiles': profiles, 'active_id': profiles[0]['id'] if profiles else None,
                'fallback_ids': [], 'auto_fallback': False}

    @staticmethod
    def _legacy_key() -> str:
        application_key = os.getenv('PAPER_READER_MODEL_API_KEY', '').strip()
        explicitly_configured = any(os.getenv(name, '').strip() for name in (
            'PAPER_READER_MODEL_BASE_URL', 'PAPER_READER_MODEL_NAME'))
        return application_key or (os.getenv('OPENAI_API_KEY', '').strip() if explicitly_configured else '')

    @staticmethod
    def _empty() -> dict:
        return {'version': 1, 'profiles': [], 'active_id': None, 'fallback_ids': [], 'auto_fallback': False}

    def _snapshot(self, *, ignore_invalid_legacy: bool = False) -> dict:
        with self._lock:
            if self._state is not None:
                return deepcopy(self._state)
            try:
                return self._initial()
            except (ValueError, TypeError):
                if not ignore_invalid_legacy:
                    raise
                return self._empty()

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.models-', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
                json.dump(state, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _commit(self, state: dict) -> None:
        self._write(state)
        self._state = state

    def ensure_migrated(self) -> None:
        with self._lock:
            if self._state is None:
                self._commit(self._initial())

    def public(self) -> dict:
        try:
            self.ensure_migrated()
        except (ValueError, TypeError):
            state = self._empty()
            state.pop('version')
            return {**state, 'configuration_error': '旧模型配置无效，请新增连接；原配置文件未改动'}
        state = self._snapshot()
        state.pop('version')
        state.setdefault('codex_max_concurrency', 4)
        state['profiles'] = [{**{k: v for k, v in p.items() if k != 'api_key'},
                              'provider_kind': p.get('provider_kind', 'api'),
                              'api_key_configured': bool(p.get('api_key'))} for p in state['profiles']]
        return state

    def codex_concurrency(self) -> int:
        with self._lock:
            return min(8, max(1, self._snapshot().get('codex_max_concurrency', 4)))

    def set_codex_concurrency(self, limit: int) -> dict:
        if not 1 <= limit <= 8:
            raise ValueError('官方账号并发请选择 1 至 8')
        with self._lock:
            state = self._snapshot()
            state['codex_max_concurrency'] = limit
            self._commit(state)
        with self._condition:
            self._condition.notify_all()
        return self.public()

    def worker_parallelism(self):
        """Separate API profiles have capacity; official profiles share one account."""
        profiles = self._snapshot()['profiles']
        return min(16, max(1, sum(p.get('max_concurrency', 1) for p in profiles
            if p.get('provider_kind') != 'codex') +
            (self.codex_concurrency() if any(p.get('provider_kind') == 'codex' for p in profiles) else 0)))

    def _effective_limit(self, key, configured):
        adaptive = self._adaptive.get(key)
        if adaptive and time.monotonic() >= adaptive['recover_at']:
            adaptive['limit'] = min(configured, adaptive['limit'] + 1)
            adaptive['recover_at'] = time.monotonic() + 60
        return min(configured, adaptive['limit']) if adaptive else configured

    def capacity_status(self):
        with self._condition:
            configured = self.codex_concurrency()
            return {'official': {'configured': configured,
                'effective': self._effective_limit('codex-subscription', configured),
                'active': self._in_use.get('codex-subscription', 0),
                'waiting': len(self._waiting.get('codex-subscription', []))},
                'active': sum(self._in_use.values()),
                'waiting': sum(len(items) for items in self._waiting.values())}

    def save(self, payload, profile_id: str | None = None) -> dict:
        with self._lock:
            state = self._snapshot(ignore_invalid_legacy=profile_id is None)
            old = next((p for p in state['profiles'] if p['id'] == profile_id), None)
            if profile_id and old is None:
                raise ProviderError('未找到这份模型配置', 404)
            key = (payload.api_key or '').strip() or (old or {}).get('api_key', '')
            if payload.provider_kind == 'api' and not key:
                raise ValueError('请输入这份配置的 API key')
            values = payload.model_dump(exclude={'test_connection'})
            values.update(api_key=key, base_url=payload.base_url.strip(), model=payload.model.strip())
            if payload.provider_kind == 'codex':
                values.pop('api_key', None)
                values.update(base_url='https://chatgpt.com', max_concurrency=1)
            provider = self._build(values)
        # A network test must not block switching or unrelated model work.
        if payload.test_connection:
            if profile_id or payload.provider_kind == 'codex':
                gate_id = 'codex-subscription' if payload.provider_kind == 'codex' else profile_id
                provider._capacity = lambda: self.capacity(gate_id,
                    self.codex_concurrency() if payload.provider_kind == 'codex' else values['max_concurrency'])
            provider.test_connection()
        with self._lock:
            latest = self._snapshot(ignore_invalid_legacy=profile_id is None)
            current = next((p for p in latest['profiles'] if p['id'] == profile_id), None)
            if profile_id and current != old:
                raise ProviderError('测试期间这份配置已改变，请重新载入后保存', 409)
            # Preserve any route/profile change that happened during the test.
            # For first migration retain the original, stable legacy profile ID.
            if self._state is not None:
                state = latest
            item = {'id': profile_id or 'profile-' + uuid.uuid4().hex, **values}
            state['profiles'] = [item if p['id'] == profile_id else p for p in state['profiles']]
            if old is None:
                state['profiles'].append(item)
                if state['active_id'] is None and len(state['profiles']) == 1:
                    state['active_id'] = item['id']
            self._commit(state)
            return next(p for p in self.public()['profiles'] if p['id'] == item['id'])

    @property
    def migrated(self) -> bool:
        with self._lock:
            return self._state is not None

    def route(self, payload) -> dict:
        with self._lock:
            state = self._snapshot()
            ids = {p['id'] for p in state['profiles']}
            if (payload.active_id is not None and payload.active_id not in ids
                or any(p not in ids or p == payload.active_id for p in payload.fallback_ids)
                or len(set(payload.fallback_ids)) != len(payload.fallback_ids)
                or payload.auto_fallback and payload.active_id is None):
                raise ValueError('主配置和备用配置必须存在且互不重复')
            state.update(payload.model_dump())
            if not state['fallback_ids']:
                state['auto_fallback'] = False
            self._commit(state)
            return self.public()

    def delete(self, profile_id: str) -> dict:
        with self._lock:
            state = self._snapshot()
            if not any(p['id'] == profile_id for p in state['profiles']):
                raise ProviderError('未找到这份模型配置', 404)
            state['profiles'] = [p for p in state['profiles'] if p['id'] != profile_id]
            state['fallback_ids'] = [p for p in state['fallback_ids'] if p != profile_id]
            if state['active_id'] == profile_id:
                state.update(active_id=None, auto_fallback=False)
            self._commit(state)
            return self.public()

    def _build(self, values: dict) -> OpenAICompatibleProvider:
        if values.get('provider_kind') == 'codex':
            from .codex_subscription import CodexSubscriptionProvider
            return CodexSubscriptionProvider(account=self.codex, **{key: values[key] for key in (
                'model', 'reasoning_effort', 'timeout')})
        return OpenAICompatibleProvider(**{key: values[key] for key in (
            'api_key', 'base_url', 'model', 'wire_api', 'reasoning_effort', 'timeout', 'completion_parameter', 'json_mode')})

    def provider(self, profile_id: str):
        state = self._snapshot()
        profile = next((p for p in state['profiles'] if p['id'] == profile_id), None)
        if profile is None:
            raise ProviderError('模型配置已被删除，请重新选择', 409)
        provider = self._build(profile)
        provider.profile_id, provider.profile_name = profile['id'], profile['name']
        subscription = profile.get('provider_kind') == 'codex'
        provider.capacity_key = 'codex-subscription' if subscription else profile_id
        provider._capacity = lambda: self.capacity('codex-subscription' if subscription else profile_id,
            self.codex_concurrency() if subscription else profile['max_concurrency'])
        return provider

    def subscription_provider(self, profile_id: str):
        # Validate and build one frozen profile under the same lock. An edit
        # cannot turn optional subscription work into a paid API request.
        with self._lock:
            profile = next((p for p in self._snapshot()['profiles'] if p['id'] == profile_id), None)
            if profile is None or profile.get('provider_kind') != 'codex':
                raise ProviderError('后台研究只使用指定的官方 Codex 连接', 409, code='subscription_required')
            return self.provider(profile_id)

    def selected(self):
        # Before first migration preserve the legacy environment-backed adapter.
        with self._lock:
            if self._state is None:
                if not self._legacy_key():
                    return None
                self.ensure_migrated()
            state = self._snapshot()
            if state['active_id'] is None:
                from .mock import MockProvider
                return MockProvider()
            provider = self.provider(state['active_id'])
            provider.profile_store = self
            ids = [state['active_id']] + (state['fallback_ids'] if state['auto_fallback'] else [])
            # Freeze deduplication identity for this task. Routing itself stays
            # live at each call, but cannot masquerade as a source-text change.
            provider.routing_identity = {'auto_fallback': state['auto_fallback'],
                'profiles': [{k: v for k, v in next(p for p in state['profiles'] if p['id'] == profile_id).items()
                    if k not in {'api_key', 'name', 'max_concurrency', 'timeout'}} for profile_id in ids]}
            return provider

    def candidates(self):
        # Freeze the complete route, including credentials, before any request.
        # Changes made while a request is in flight apply at its next boundary.
        with self._lock:
            state = self._snapshot()
            if not state['active_id']:
                raise ProviderError('请先启用一份模型配置', 409, diagnostics={'request_sent': False})
            ids = [state['active_id']] + (state['fallback_ids'] if state['auto_fallback'] else [])
            return [self.provider(profile_id) for profile_id in ids]

    @contextmanager
    def capacity(self, profile_id: str, limit: int):
        from .priority import check_background, is_background, request_priority
        background = is_background()
        rank = request_priority()
        work = nullcontext(False) if background else self.priority.foreground_work()
        with work:
            # A busy local account is a queue, not a failed upstream request.
            deadline = time.monotonic() + 600
            ticket = object()
            with self._condition:
                waiting = self._waiting.setdefault(profile_id, [])
                waiting.append((ticket, rank))
                try:
                    while True:
                        check_background()
                        configured = self.codex_concurrency() if profile_id == 'codex-subscription' else limit
                        effective_limit = self._effective_limit(profile_id, configured)
                        first = min(waiting, key=lambda item: item[1]() if callable(item[1]) else item[1])[0] is ticket
                        full = self._in_use.get(profile_id, 0) >= effective_limit
                        # Idle capacity is borrowable. Rank-0 requests win the
                        # next slot without cancelling already paid generation.
                        if first and not full:
                            self._in_use[profile_id] = self._in_use.get(profile_id, 0) + 1
                            if background:
                                self._background_use[profile_id] = self._background_use.get(profile_id, 0) + 1
                            break
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ProviderError('等待当前连接超过时限，请重试；已有结果已保留', 503,
                                code='local_capacity', retryable=True, retry_after=1,
                                diagnostics={'request_sent': False})
                        self._condition.wait(timeout=min(.2, remaining))
                finally:
                    waiting.remove((ticket, rank))
                    if not waiting:
                        self._waiting.pop(profile_id, None)
                    self._condition.notify_all()
            try:
                from .priority import check_admission
                check_admission()
                yield
            except ProviderError as error:
                if error.code == 'rate_limit':
                    with self._condition:
                        current = self._adaptive.get(profile_id, {}).get('limit', effective_limit)
                        self._adaptive[profile_id] = {'limit': max(1, min(current, effective_limit) // 2),
                            'recover_at': time.monotonic() + max(60, error.retry_after or 0)}
                raise
            finally:
                with self._condition:
                    self._in_use[profile_id] -= 1
                    if background:
                        self._background_use[profile_id] -= 1
                    self._condition.notify_all()
