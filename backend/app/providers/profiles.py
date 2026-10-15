"""Atomic, server-only connection profiles and shared per-profile capacity gates."""
from __future__ import annotations

from contextlib import contextmanager
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

current_store: ContextVar[ProfileStore | None] = ContextVar('model_profile_store', default=None)


class ProfileStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._condition = threading.Condition()
        self._in_use: dict[str, int] = {}
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
        state['profiles'] = [{**{k: v for k, v in p.items() if k != 'api_key'},
                              'api_key_configured': bool(p.get('api_key'))} for p in state['profiles']]
        return state

    def save(self, payload, profile_id: str | None = None) -> dict:
        with self._lock:
            state = self._snapshot(ignore_invalid_legacy=profile_id is None)
            old = next((p for p in state['profiles'] if p['id'] == profile_id), None)
            if profile_id and old is None:
                raise ProviderError('未找到这份模型配置', 404)
            key = (payload.api_key or '').strip() or (old or {}).get('api_key', '')
            if not key:
                raise ValueError('请输入这份配置的 API key')
            values = payload.model_dump(exclude={'test_connection'})
            values.update(api_key=key, base_url=payload.base_url.strip(), model=payload.model.strip())
            provider = self._build(values)
        # A network test must not block switching or unrelated model work.
        if payload.test_connection:
            if profile_id:
                provider._capacity = lambda: self.capacity(profile_id, values['max_concurrency'])
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

    @staticmethod
    def _build(values: dict) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(**{key: values[key] for key in (
            'api_key', 'base_url', 'model', 'wire_api', 'reasoning_effort', 'timeout', 'completion_parameter', 'json_mode')})

    def provider(self, profile_id: str):
        state = self._snapshot()
        profile = next((p for p in state['profiles'] if p['id'] == profile_id), None)
        if profile is None:
            raise ProviderError('模型配置已被删除，请重新选择', 409)
        provider = self._build(profile)
        provider.profile_id, provider.profile_name = profile['id'], profile['name']
        provider._capacity = lambda: self.capacity(profile_id, profile['max_concurrency'])
        return provider

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
        deadline = time.monotonic() + 1.0
        with self._condition:
            while self._in_use.get(profile_id, 0) >= limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderError('当前连接已达到同时请求上限，请稍后重试或切换连接', 503,
                        code='local_capacity', retryable=True, retry_after=1,
                        diagnostics={'request_sent': False})
                self._condition.wait(timeout=min(.25, remaining))
            self._in_use[profile_id] = self._in_use.get(profile_id, 0) + 1
        try:
            yield
        finally:
            with self._condition:
                self._in_use[profile_id] -= 1
                self._condition.notify_all()
