"""ChatGPT OAuth owned by the official CLI, in LIRA's separate account directory."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from urllib.parse import urlsplit

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

    def environment(self) -> dict[str, str]:
        # Only the child receives this home. Never inherit the desktop agent's
        # gateway credentials or edit its configuration/login.
        result = {k: v for k, v in os.environ.items()
                  if not k.upper().startswith(('CODEX_', 'OPENAI_', 'PAPER_READER_'))}
        result['CODEX_HOME'] = str(self.home)
        return result

    @staticmethod
    def options() -> list[str]:
        return ['-c', 'model_provider="openai"', '-c', 'forced_login_method="chatgpt"',
                '-c', 'cli_auth_credentials_store="file"']

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
            self._login_id = self._login_url = None
            self._login_error = None if params.get('success') else '登录未完成，请重新登录'
            self._cached_at = 0
        elif method in {'account/updated', 'account/rateLimits/updated'}:
            self._cached_at = 0

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
                    raise ProviderError('Codex 账户操作未完成，请刷新账户状态后重试', 502, code='codex_account_error', retryable=True)
                result = value.get('result')
                return result if isinstance(result, dict) else {}
            self._notification(value)
            if time.monotonic() >= deadline:
                self._stop_server()
                raise ProviderError('Codex 账户服务响应超时，请重试', 504, code='transport_timeout', retryable=True)

    @staticmethod
    def _limits(data):
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
                continue
            def number(key):
                value = window.get(key)
                return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None
            result.append({'name': name, 'used_percent': min(100, max(0, percent)),
                'window_minutes': number('windowDurationMins'), 'resets_at': number('resetsAt')})
        return result

    def status(self, *, refresh=False):
        with self._lock:
            while not self._messages.empty():
                try:
                    self._notification(self._messages.get_nowait())
                except queue.Empty:
                    break
            if not refresh and self._cached is not None and time.monotonic() - self._cached_at < 10:
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
                    try:
                        state['limits'] = self._limits(self._request('account/rateLimits/read'))
                    except ProviderError:
                        state['limits_error'] = '暂时无法读取额度，可稍后刷新'
                state.update(pending=bool(self._login_id), login_url=self._login_url, error=self._login_error)
            except ProviderError as error:
                state.update(error=str(error), error_code=error.code, retryable=error.retryable,
                    available=error.code != 'codex_unavailable', pending=False, login_url=None)
            self._cached, self._cached_at = state, time.monotonic()
            return dict(state)

    def login(self):
        with self._lock:
            self._start()
            if self._login_id:
                return self.status()
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
            self._cached_at = 0
            return self.status(refresh=True)

    def _stop_server(self):
        process, self._process = self._process, None
        self.stop(process)
        self._cached_at = 0
        self._login_id = self._login_url = None

    def close(self):
        with self._lock:
            with self._children_lock:
                self._closed = True
                for process in list(self._children):
                    self.stop(process)
            self._stop_server()
