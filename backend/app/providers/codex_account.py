"""ChatGPT OAuth owned by the official CLI, in LIRA's separate account directory."""
from __future__ import annotations

import json
from copy import deepcopy
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from urllib.parse import urlsplit
from urllib import request as urllib_request
from urllib.request import getproxies

from .base import ProviderError


class CodexAccount:
    def __init__(self, home: Path, *, command: list[str] | None = None):
        self.home = home.resolve()
        executable = shutil.which('codex') if command is None else None
        self.command = list(command) if command else [executable] if executable else []
        self._lock = threading.RLock()
        self._children_lock = threading.RLock()
        self._children = set()
        self._closed = False
        self._process = None
        self._messages = queue.Queue(maxsize=128)
        self._sequence = 0
        self._login_id = self._login_url = None
        self._login_error = None
        self._cached = None
        self._cached_at = 0.0
        self._cached_includes_limits = False
        self._model_cache = None
        self._model_cache_at = 0.0
        self._reset_limits()

    def environment(self) -> dict[str, str]:
        # Only the child receives this home. Never inherit the desktop agent's
        # gateway credentials or edit its configuration/login.
        result = {k: v for k, v in os.environ.items()
                  if not k.upper().startswith(('CODEX_', 'OPENAI_', 'PAPER_READER_'))}
        result['CODEX_HOME'] = str(self.home)
        # Rust HTTP clients do not reliably discover the Windows system proxy.
        # Apply it only to this child; explicit environment routes always win.
        # urllib's combined lookup skips the registry when NO_PROXY alone is
        # present, so obtain Windows routes independently before merging.
        routes = dict(getattr(urllib_request, 'getproxies_registry', lambda: {})())
        routes.update(getproxies())
        existing = {key.casefold() for key in result}
        for scheme, proxy in routes.items():
            name = {'http': 'HTTP_PROXY', 'https': 'HTTPS_PROXY', 'all': 'ALL_PROXY', 'no': 'NO_PROXY'}.get(scheme)
            if not name or name.casefold() in existing:
                continue
            if scheme in ('http', 'https') and 'all_proxy' in existing:
                continue
            result[name] = proxy if scheme == 'no' or '://' in proxy else 'http://' + proxy
        return result

    def _reset_limits(self):
        self._limits_snapshot, self._limits_identity = [], None
        self._limits_checked_at = self._limits_attempted_at = self._limits_next_refresh = 0
        self._limits_error_code = None
        self._limits_retryable = False

    def _quota_status(self, identity, *, refresh=False, include_limits=True):
        if identity != self._limits_identity:
            self._reset_limits()
            self._limits_identity = identity
        if include_limits and (refresh or time.monotonic() >= self._limits_next_refresh):
            self._limits_attempted_at = time.time()
            try:
                self._limits_snapshot = self._limits(self._request('account/rateLimits/read'))
                self._limits_checked_at = time.time()
                self._limits_error_code, self._limits_retryable = None, False
                self._limits_next_refresh = time.monotonic() + 60
            except ProviderError as error:
                self._limits_error_code, self._limits_retryable = error.code, error.retryable
                if error.code in {'authentication', 'rate_limit'}:
                    self._limits_snapshot, self._limits_checked_at = [], 0
                self._limits_next_refresh = time.monotonic() + 15
        state = {'limits': deepcopy(self._limits_snapshot),
            'limits_checked_at': self._limits_checked_at or None,
            'limits_attempted_at': self._limits_attempted_at or None}
        if self._limits_error_code:
            state.update(limits_error_code=self._limits_error_code, limits_retryable=self._limits_retryable,
                limits_error=('官方额度查询超时' if self._limits_error_code == 'transport_timeout' else '官方额度查询失败') + '；稍后自动重试，已有额度按上次成功读取时间判断有效期。')
        return state

    @staticmethod
    def options(*, https=False) -> list[str]:
        options = ['-c', 'forced_login_method="chatgpt"', '-c', 'cli_auth_credentials_store="file"']
        if not https:
            return [*options, '-c', 'model_provider="openai"']
        # Batch research requests gain no benefit from WebSockets. The built-in
        # provider cannot be overridden; use the CLI's supported provider config
        # to go straight to its official HTTPS endpoint, with CLI-owned OAuth.
        return [*options, '-c', 'model_provider="lira_chatgpt_https"',
            '-c', 'model_providers.lira_chatgpt_https.name="ChatGPT HTTPS"',
            '-c', 'model_providers.lira_chatgpt_https.base_url="https://chatgpt.com/backend-api/codex"',
            '-c', 'model_providers.lira_chatgpt_https.wire_api="responses"',
            '-c', 'model_providers.lira_chatgpt_https.requires_openai_auth=true',
            '-c', 'model_providers.lira_chatgpt_https.supports_websockets=false']

    def spawn(self, arguments: list[str], *, cwd: Path):
        if not self.command:
            raise ProviderError('未找到 Codex CLI，请先安装官方 Codex CLI 后重启 LIRA', 409, code='codex_unavailable')
        self.home.mkdir(parents=True, exist_ok=True)
        try:
            with self._children_lock:
                if self._closed:
                    raise ProviderError('LIRA 的 Codex 连接已关闭，请重启服务', 503,
                        code='codex_unavailable', diagnostics={'request_sent': False})
                process = subprocess.Popen([*self.command, *arguments], cwd=cwd, env=self.environment(),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding='utf-8', errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self._children.add(process)
                return process
        except OSError:
            raise ProviderError('无法启动官方 Codex CLI，请检查安装后重试', 503, code='codex_unavailable') from None

    def stop(self, process):
        if process is None:
            return
        with self._children_lock:
            if process not in self._children:
                return
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for pipe in (process.stdin, process.stdout):
                if pipe:
                    pipe.close()
            self._children.discard(process)

    def _start(self):
        if self._process is not None and self._process.poll() is None:
            return
        self._stop_server()
        self.home.mkdir(parents=True, exist_ok=True)
        process = self.spawn(['app-server', '--stdio', *self.options()], cwd=self.home)
        messages = self._messages = queue.Queue(maxsize=128)
        self._process = process

        def read():
            try:
                while line := process.stdout.readline(1_000_001):
                    if len(line) > 1_000_000:
                        break
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(value, dict):
                        messages.put(value, timeout=1)
            except (OSError, ValueError, queue.Full):
                pass
            finally:
                try:
                    messages.put(None, timeout=1)
                except queue.Full:
                    pass

        threading.Thread(target=read, name='lira-codex-account', daemon=True).start()
        try:
            self._request('initialize', {'clientInfo': {'name': 'lira', 'version': '0.1.0'}})
            self._send({'method': 'initialized'})
        except ProviderError:
            self._stop_server()
            raise

    def _send(self, value):
        try:
            self._process.stdin.write(json.dumps(value) + '\n')
            self._process.stdin.flush()
        except (OSError, ValueError, AttributeError):
            raise ProviderError('Codex 登录服务已断开，请刷新后重试', 503, code='transport_error', retryable=True) from None

    def _notification(self, value):
        if not isinstance(value, dict):
            return
        method, params = value.get('method'), value.get('params') or {}
        if method == 'account/login/completed' and params.get('loginId') == self._login_id:
            self._model_cache = None
            self._login_id = self._login_url = None
            self._login_error = None if params.get('success') else '登录未完成，请重新登录'
            self._cached_at = 0
        elif method in {'account/updated', 'account/rateLimits/updated'}:
            self._cached_at = 0
            self._limits_next_refresh = 0
            if method == 'account/updated':
                self._model_cache = None
                self._reset_limits()

    def _request(self, method, params=None):
        self._sequence += 1
        identifier = self._sequence
        self._send({'id': identifier, 'method': method, 'params': params or {}})
        deadline = time.monotonic() + 25
        while True:
            try:
                value = self._messages.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                self._stop_server()
                raise ProviderError('Codex 账户服务响应超时，请刷新后重试', 504, code='transport_timeout', retryable=True) from None
            if value is None:
                self._stop_server()
                raise ProviderError('Codex 账户服务已退出，请刷新后重试', 503, code='transport_error', retryable=True)
            if value.get('id') == identifier:
                if 'error' in value:
                    if method == 'account/rateLimits/read':
                        # Classify locally; never return upstream text, URLs or credentials.
                        error = value['error']
                        message = str(error.get('message', '') if isinstance(error, dict) else '').casefold()
                        if any(term in message for term in ('unauthorized', '401', '403', 'authentication')):
                            raise ProviderError('官方额度查询需要重新登录', 401, code='authentication')
                        if any(term in message for term in ('429', 'rate limit', 'usage limit', 'quota exceeded')):
                            raise ProviderError('官方连接暂时受限，稍后重试', 503, code='rate_limit', retryable=True)
                        if any(term in message for term in ('timed out', 'timeout', 'deadline exceeded')):
                            raise ProviderError('官方额度查询超时，稍后自动重试', 504, code='transport_timeout', retryable=True)
                        if any(term in message for term in ('error sending request', 'connection', 'dns', 'network', 'tls')):
                            raise ProviderError('官方额度查询连接失败，稍后自动重试', 503, code='transport_error', retryable=True)
                    raise ProviderError('Codex 账户操作未完成，请刷新账户状态后重试', 502, code='codex_account_error', retryable=True)
                result = value.get('result')
                return result if isinstance(result, dict) else {}
            self._notification(value)
            if time.monotonic() >= deadline:
                self._stop_server()
                raise ProviderError('Codex 账户服务响应超时，请重试', 504, code='transport_timeout', retryable=True)

    @staticmethod
    def _limits(data):
        buckets = data.get('rateLimitsByLimitId')
        if isinstance(buckets, dict) and buckets:
            return [{**window, 'limit_id': str(limit_id)[:200]}
                    for limit_id, bucket in buckets.items() if isinstance(bucket, dict)
                    for window in CodexAccount._limits({'rateLimits': bucket})]
        result = []
        limits = data.get('rateLimits')
        if not isinstance(limits, dict):
            return result
        for name in ('primary', 'secondary'):
            window = limits.get(name)
            if not isinstance(window, dict):
                continue
            percent = window.get('usedPercent')
            if not isinstance(percent, (float, int)) or isinstance(percent, bool) or not math.isfinite(percent):
                percent = None
            def number(key):
                value = window.get(key)
                return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None
            result.append({'name': name, 'used_percent': min(100, max(0, percent)) if percent is not None else None,
                'window_minutes': number('windowDurationMins'), 'resets_at': number('resetsAt')})
        return result

    def status(self, *, refresh=False, include_limits=True):
        with self._lock:
            while not self._messages.empty():
                try:
                    self._notification(self._messages.get_nowait())
                except queue.Empty:
                    break
            if (not refresh and self._cached is not None and time.monotonic() - self._cached_at < 10
                    and (not include_limits or self._cached_includes_limits)):
                return dict(self._cached)
            state = {'available': bool(self.command), 'authenticated': False, 'pending': bool(self._login_id),
                'email': None, 'plan': None, 'limits': [], 'login_url': self._login_url, 'error': self._login_error}
            if not self.command:
                return {**state, 'error': '未找到官方 Codex CLI'}
            try:
                self._start()
                data = self._request('account/read', {'refreshToken': False})
                account = data.get('account') or {}
                state['authenticated'] = account.get('type') == 'chatgpt'
                if state['authenticated']:
                    state['email'] = str(account['email'])[:320] if account.get('email') else None
                    state['plan'] = str(account['planType'])[:60] if account.get('planType') else None
                    self._login_id = self._login_url = None
                    self._login_error = None
                    state.update(self._quota_status((state['email'], state['plan']),
                        refresh=refresh, include_limits=include_limits))
                else:
                    self._reset_limits()
                state.update(pending=bool(self._login_id), login_url=self._login_url, error=self._login_error)
            except ProviderError as error:
                state.update(error=str(error), error_code=error.code, retryable=error.retryable,
                    available=error.code != 'codex_unavailable', pending=False, login_url=None)
            self._cached, self._cached_at = state, time.monotonic()
            self._cached_includes_limits = include_limits
            return dict(state)

    def login(self):
        with self._lock:
            self._start()
            self._model_cache = None
            if self._login_id:
                return self.status()
            self._reset_limits()
            data = self._request('account/login/start', {'type': 'chatgpt'})
            url = data.get('authUrl', '')
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or parsed.netloc != 'auth.openai.com' or not data.get('loginId'):
                raise ProviderError('Codex 未返回官方登录地址，请更新官方 CLI 后重试', code='codex_account_error')
            self._login_id, self._login_url = data['loginId'], url
            self._login_error = None
            self._cached_at = 0
            return self.status(refresh=True)

    def cancel_login(self):
        with self._lock:
            if self._login_id:
                self._start()
                self._request('account/login/cancel', {'loginId': self._login_id})
            self._login_id = self._login_url = None
            self._login_error = None
            self._cached_at = 0
            return self.status(refresh=True)

    def logout(self):
        with self._lock:
            self._start()
            if self._login_id:
                self.cancel_login()
            self._request('account/logout')
            self._reset_limits()
            self._model_cache = None
            self._cached_at = 0
            return self.status(refresh=True)

    def models(self, *, refresh=False):
        """The official catalog is the sole source of picker models and efforts."""
        with self._lock:
            state = self.status(include_limits=False)
            if state.get('error_code'):
                raise ProviderError(state['error'], 503, code=state['error_code'],
                    retryable=bool(state.get('retryable')), diagnostics={'request_sent': False})
            if not state['authenticated']:
                raise ProviderError('请先登录 ChatGPT，再读取官方模型列表', 409,
                    code='authentication', diagnostics={'request_sent': False})
            # status() may be cached when an idle app-server has exited.
            self._start()
            identity = (state.get('email'), state.get('plan'))
            if (not refresh and self._model_cache is not None
                    and self._model_cache[0] == identity and time.monotonic() - self._model_cache_at < 60):
                return deepcopy(self._model_cache[1])
            models, seen, cursors = [], set(), set()
            cursor = None
            for _ in range(20):
                params = {'limit': 100, 'includeHidden': False}
                if cursor: params['cursor'] = cursor
                data = self._request('model/list', params)
                if not isinstance(data.get('data'), list):
                    raise ProviderError('官方 CLI 未返回模型列表，请更新 CLI 后重试', 502, code='codex_catalog_error')
                for item in data['data']:
                    if not isinstance(item, dict) or item.get('hidden'): continue
                    model = item.get('model')
                    if not isinstance(model, str) or not model or len(model) > 200 or any(ord(c) < 32 for c in model) or model in seen: continue
                    efforts = []
                    for option in item.get('supportedReasoningEfforts') or []:
                        if not isinstance(option, dict): continue
                        value = option.get('reasoningEffort')
                        if value not in {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}: continue
                        if any(entry['effort'] == value for entry in efforts): continue
                        efforts.append({'effort': value, 'description': str(option.get('description') or '')[:500]})
                    default = item.get('defaultReasoningEffort')
                    if default not in {option['effort'] for option in efforts}: default = None
                    models.append({'id': model, 'model': model,
                        'display_name': str(item.get('displayName') or model)[:200],
                        'description': str(item.get('description') or '')[:1000],
                        'default_reasoning_effort': default, 'supported_reasoning_efforts': efforts,
                        'is_default': item.get('isDefault') is True})
                    seen.add(model)
                cursor = data.get('nextCursor')
                if cursor is None: break
                if not isinstance(cursor, str) or not cursor or cursor in cursors:
                    raise ProviderError('官方模型目录分页无效，请刷新后重试', 502, code='codex_catalog_error')
                cursors.add(cursor)
            else:
                raise ProviderError('官方模型目录过大，请更新 CLI 后重试', 502, code='codex_catalog_error')
            result = {'models': models, 'default_model': next((m['model'] for m in models if m['is_default']), None)}
            self._model_cache, self._model_cache_at = (identity, result), time.monotonic()
            return deepcopy(result)

    def _stop_server(self):
        process, self._process = self._process, None
        self.stop(process)
        self._cached_at = 0
        self._model_cache = None
        self._login_id = self._login_url = None

    def close(self):
        with self._lock:
            with self._children_lock:
                self._closed = True
                for process in list(self._children):
                    self.stop(process)
            self._stop_server()
