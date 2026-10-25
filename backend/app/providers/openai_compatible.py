"""Optional OpenAI-compatible HTTP adapter with strict local citation validation."""
from __future__ import annotations
import json
import hashlib
import math
import time
import ssl
from contextlib import nullcontext
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
import httpx
from ..models import PaperChunk
from .base import AnalysisResult, AnswerResult, ProviderError, VerifiedCitation
from .validation import canonical_quote
from .usage import sanitize_usage

PROMPTS_DIR = Path(__file__).resolve().parents[3] / 'prompts'
MAX_CONTEXT_CHARS = 24000
MAX_CHUNK_CHARS = 4000
MAX_TRANSLATION_CHARS = 12000
ABSTENTION = '当前提供的原文中没有足够且可验证的证据，无法回答这个问题。'


class OpenAICompatibleProvider:
    name = 'OpenAICompatibleProvider'
    mode = 'remote'
    configured = True
    translation_available = True

    def __init__(self, *, api_key: str, base_url: str = 'https://api.openai.com/v1', model: str = 'gpt-4.1-mini', transport: httpx.BaseTransport | None = None, timeout: float = 600.0, wire_api: str = 'chat_completions', reasoning_effort: str = 'disabled', completion_parameter: str = 'max_completion_tokens', json_mode: str = 'json_object') -> None:
        try:
            url = httpx.URL(base_url)
        except (httpx.InvalidURL, ValueError):
            raise ValueError('模型 base URL 无效') from None
        if url.scheme not in {'http','https'} or not url.host or url.userinfo or url.query or url.fragment:
            raise ValueError('模型地址必须是没有凭证或查询参数的 HTTP(S) base URL')
        if not api_key.strip() or not model.strip():
            raise ValueError('模型配置缺少 API key 或 model name')
        if wire_api not in {'chat_completions', 'responses'} or completion_parameter not in {'max_tokens', 'max_completion_tokens'} or json_mode not in {'json_object', 'none'}:
            raise ValueError('模型协议配置无效')
        if (reasoning_effort not in {'disabled', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh'}
                or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 1800):
            raise ValueError('模型请求配置无效')
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip('/')
        self.model = model.strip()
        self._transport = transport
        self.timeout = timeout
        self.wire_api = wire_api
        self.reasoning_effort = reasoning_effort
        self.completion_parameter = completion_parameter
        self.json_mode = json_mode
        self.response_model: str | None = None
        self.last_usage: dict = {}
        self.last_http_status: int | None = None

    def _http_diagnostics(self) -> dict:
        return {'http_status': self.last_http_status} if self.last_http_status is not None else {}

    def _transport_diagnostics(self, error: Exception) -> dict:
        known = {'ConnectError', 'ReadError', 'WriteError', 'CloseError', 'ConnectTimeout',
                 'ReadTimeout', 'WriteTimeout', 'PoolTimeout', 'RemoteProtocolError'}
        return {**self._http_diagnostics(), 'transport_type':
                type(error).__name__ if type(error).__name__ in known else 'unknown'}

    @staticmethod
    def _certificate_error(error: Exception) -> ssl.SSLCertVerificationError | None:
        pending, seen = [error], set()
        while pending and len(seen) < 12:
            current = pending.pop()
            if id(current) in seen:
                continue
            seen.add(id(current))
            if isinstance(current, ssl.SSLCertVerificationError):
                return current
            pending.extend(value for value in (current.__cause__, current.__context__, *current.args)
                           if isinstance(value, BaseException))
        return None

    @staticmethod
    def _prompt(name: str) -> str:
        return (PROMPTS_DIR / name).read_text(encoding='utf-8-sig')

    @property
    def translation_configuration_version(self) -> str:
        # API keys never enter the persisted configuration fingerprint.
        config = json.dumps([self.name, self.base_url, self.model, self.wire_api, self.reasoning_effort, self.completion_parameter, self.json_mode], separators=(',', ':'))
        return hashlib.sha256(config.encode('utf-8')).hexdigest()

    @property
    def translation_prompt_version(self) -> str:
        return 'translate-sha256:' + hashlib.sha256(self._prompt('paper_translate.txt').encode('utf-8')).hexdigest()

    def effective_reasoning_effort(self, requested: str | None = None) -> str | None:
        # Nonreasoning endpoints must omit the parameter even when a stage requests it.
        return None if self.reasoning_effort == 'disabled' else requested or self.reasoning_effort

    def test_connection(self) -> None:
        """Make a tiny uncached request so the settings form can verify the profile."""
        self._complete(
            'Reply with the single word OK.',
            'OK',
            json_output=False,
            max_output_tokens=8,
            reasoning_effort='minimal',
        )

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get('retry-after', '').strip()
        if not value:
            return None
        if value.isascii() and value.isdecimal():
            return min(float(value), 30.0)
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return None
            return min(max(date.timestamp() - time.time(), 0.0), 30.0)
        except (ValueError, TypeError, OverflowError, OSError):
            return None

    def _record_response_metadata(self, data: dict) -> None:
        # A later event without usage must not erase actual earlier usage.
        if 'usage' in data:
            self.last_usage = sanitize_usage(data['usage'])
        if data.get('model'):
            self.response_model = str(data['model'])[:200]

    @staticmethod
    def _upstream_failure(error: object) -> ProviderError:
        # Error envelopes may carry a type with code=null. An explicit unknown
        # code remains authoritative: don't turn arbitrary provider errors into
        # paid retries based on a broad type or untrusted message.
        public = {'rate_limit', 'rate_limit_error', 'rate_limit_exceeded', 'server_error',
            'api_error', 'overloaded_error', 'invalid_api_key', 'authentication_error',
            'permission_denied', 'invalid_request_error'}
        raw_code = error.get('code') if isinstance(error, dict) else None
        error_type = error.get('type') if isinstance(error, dict) else None
        def category(value):
            return value if isinstance(value, str) and value in public else 'missing' if value is None else 'unknown'
        diagnostics = {'upstream_code': category(raw_code), 'upstream_type': category(error_type)}
        code = raw_code if raw_code is not None else error_type
        code = code if isinstance(code, str) else None
        if code in {'rate_limit', 'rate_limit_error', 'rate_limit_exceeded'}:
            return ProviderError('模型服务请求受限，请稍后重试', 503, code='rate_limit', retryable=True, diagnostics=diagnostics)
        if code in {'server_error', 'api_error', 'overloaded_error'}:
            return ProviderError('模型服务暂时失败，请稍后重试；已有结果已保留', code='upstream_error', retryable=True, diagnostics=diagnostics)
        if code in {'invalid_api_key', 'authentication_error', 'permission_denied'}:
            return ProviderError('模型服务认证失败，请检查 API key 与账户权限', code='authentication', diagnostics=diagnostics)
        if code == 'invalid_request_error':
            return ProviderError('模型服务拒绝请求，请检查模型与接口配置', code='invalid_request', diagnostics=diagnostics)
        return ProviderError('模型服务请求失败（服务端未提供可识别的错误分类），已有结果已保留', code='upstream_error', diagnostics=diagnostics)

    @classmethod
    def _response_failure(cls, data: dict) -> ProviderError:
        if data.get('status') == 'failed':
            return cls._accepted_failure(data.get('error'), 'response.failed')
        if data.get('status') == 'incomplete':
            details = data.get('incomplete_details')
            if isinstance(details, dict) and details.get('reason') == 'max_output_tokens':
                return ProviderError('模型输出预算不足，请提高输出预算；已有结果已保留', code='output_budget')
            return ProviderError('模型输出未完整完成，已有结果已保留', code='output_incomplete')
        return ProviderError('模型服务响应格式无效，已有结果已保留', code='invalid_response')

    @classmethod
    def _accepted_failure(cls, error: object, event_type: str) -> ProviderError:
        failure = cls._upstream_failure(error)
        failure.diagnostics['event_type'] = event_type
        # A terminal error in an accepted Responses request is a failed
        # generation, even when a gateway uses its own error code. Retry it
        # through the caller's existing bounded recovery budget. Known
        # authentication/request errors retain their nonretryable classification.
        if (failure.code == 'upstream_error'
            and failure.diagnostics.get('upstream_code') in {'unknown', 'missing'}
            and failure.diagnostics.get('upstream_type') in {'unknown', 'missing'}):
            failure.retryable = True
        return failure

    @staticmethod
    def _read_json_response(response: httpx.Response, deadline: float) -> bytes:
        content = bytearray()
        for chunk in response.iter_bytes():
            if time.monotonic() > deadline:
                raise ProviderError('模型服务请求超过时限，请重试；已有结果已保留', 504, code='transport_timeout', retryable=True)
            if len(content) + len(chunk) > 1000000:
                raise ProviderError('模型服务响应过大，已拒绝处理', code='invalid_response')
            content.extend(chunk)
        if time.monotonic() > deadline:
            raise ProviderError('模型服务请求超过时限，请重试；已有结果已保留', 504, code='transport_timeout', retryable=True)
        return bytes(content)

    def _stream_response(self, response: httpx.Response, deadline: float) -> dict:
        """Consume SSE while keeping the gateway active; publish only a final envelope."""
        size, field_size, fields, buffer = 0, 0, [], bytearray()
        for chunk in response.iter_bytes():
            size += len(chunk)
            # SSE repeats text in delta/done/final events and carries IDs per token.
            if size > 8000000:
                raise ProviderError('模型服务响应过大，已拒绝处理', code='invalid_response')
            if time.monotonic() > deadline:
                raise ProviderError('模型流式请求超过时限，请重试；已有结果已保留', 504, code='transport_timeout', retryable=True)
            buffer.extend(chunk)
            while (newline := buffer.find(b'\n')) >= 0:
                line = bytes(buffer[:newline]).rstrip(b'\r')
                del buffer[:newline + 1]
                if line.startswith(b'data:'):
                    fields.append(line[5:].lstrip())
                    field_size += len(line)
                    if field_size > 1000000:
                        raise ProviderError('模型服务响应过大，已拒绝处理', code='invalid_response')
                    continue
                if line or not fields:
                    continue
                raw, fields, field_size = b'\n'.join(fields), [], 0
                if raw == b'[DONE]':
                    raise ProviderError('模型流式连接结束但未完成输出，请重试；已有结果已保留', code='stream_interrupted', retryable=True)
                try:
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        raise ValueError()
                except (ValueError, UnicodeDecodeError):
                    raise ProviderError('模型流式响应格式无效，已有结果已保留', code='invalid_response') from None
                event_type = event.get('type')
                if not isinstance(event_type, str) or not event_type:
                    raise ProviderError('模型流式响应格式无效，已有结果已保留', code='invalid_response')
                if isinstance(event.get('response'), dict):
                    self._record_response_metadata(event['response'])
                if event_type == 'error':
                    self._record_response_metadata(event)
                    raise self._accepted_failure(event.get('error', event), 'error')
                if event_type in ('response.completed', 'response.incomplete', 'response.failed'):
                    if not isinstance(event.get('response'), dict):
                        raise ProviderError('模型流式响应格式无效，已有结果已保留', code='invalid_response')
                    if event['response'].get('status') != event_type.removeprefix('response.'):
                        raise ProviderError('模型流式响应格式无效，已有结果已保留', code='invalid_response')
                    if event_type != 'response.completed':
                        raise self._response_failure(event['response'])
                    return event['response']
            # Check incomplete lines before a peer can accumulate unbounded text.
            if len(buffer) > 1000000:
                raise ProviderError('模型服务响应过大，已拒绝处理', code='invalid_response')
        raise ProviderError('模型流式连接结束但未完成输出，请重试；已有结果已保留', code='stream_interrupted', retryable=True)

    def _complete(self, system: str, user: str, *, json_output: bool, max_output_tokens: int = 3000, reasoning_effort: str | None = None, image_data_url: str | None = None) -> str:
        self.last_usage = {}
        self.response_model = None
        gate = self._capacity() if hasattr(self, '_capacity') else nullcontext()
        with gate:
            return self._complete_request(system, user, json_output=json_output,
                max_output_tokens=max_output_tokens, reasoning_effort=reasoning_effort,
                image_data_url=image_data_url)

    def _complete_request(self, system: str, user: str, *, json_output: bool, max_output_tokens: int = 3000, reasoning_effort: str | None = None, image_data_url: str | None = None) -> str:
        self.last_usage = {}
        self.response_model = None
        self.last_http_status = None
        effort = self.effective_reasoning_effort(reasoning_effort)
        if self.wire_api == 'responses':
            content: list[dict[str, Any]] = [{'type': 'input_text', 'text': ('Return JSON for this data:\n' if json_output else '') + user}]
            if image_data_url:
                content.append({'type': 'input_image', 'image_url': image_data_url, 'detail': 'high'})
            payload: dict[str, Any] = {'model': self.model, 'instructions': system, 'input': [{'role': 'user', 'content': content}], 'max_output_tokens': max_output_tokens, 'store': False, 'stream': True}
            if effort is not None:
                payload['reasoning'] = {'effort': effort}
            if json_output and self.json_mode != 'none':
                payload['text'] = {'format': {'type': 'json_object'}}
            endpoint = '/responses'
        else:
            user_content: str | list[dict[str, Any]] = user
            if image_data_url:
                user_content = [{'type': 'text', 'text': ('Return JSON for this data:\n' if json_output else '') + user}, {'type': 'image_url', 'image_url': {'url': image_data_url, 'detail': 'high'}}]
            payload = {'model':self.model,'messages':[{'role':'system','content':system},{'role':'user','content':user_content}], self.completion_parameter: max_output_tokens}
            if effort is not None:
                payload['reasoning_effort'] = effort
            if json_output and self.json_mode != 'none':
                payload['response_format'] = {'type':'json_object'}
            endpoint = '/chat/completions'
        try:
            streamed = None
            response = None
            response_content = b''
            deadline = time.monotonic() + self.timeout
            with httpx.Client(transport=self._transport, timeout=self.timeout, follow_redirects=False, headers={'Authorization':f'Bearer {self._api_key}', 'Accept-Encoding':'identity'}) as client:
                with client.stream('POST', self.base_url + endpoint, json=payload) as response:
                    self.last_http_status = response.status_code
                    if response.is_success:
                        if self.wire_api == 'responses' and 'text/event-stream' in response.headers.get('content-type', ''):
                            streamed = self._stream_response(response, deadline)
                        else:
                            response_content = self._read_json_response(response, deadline)
        except ProviderError as error:
            if response is not None:
                error.diagnostics = {**error.diagnostics, 'http_status': response.status_code}
            raise
        except httpx.TimeoutException as error:
            raise ProviderError('模型服务请求超时，请稍后重试；原文和已有结果已保留',504, code='transport_timeout', retryable=True, diagnostics=self._transport_diagnostics(error)) from None
        except httpx.RemoteProtocolError as error:
            raise ProviderError('模型服务连接中断，请稍后重试；原文和已有结果已保留', code='transport_protocol', retryable=True, diagnostics=self._transport_diagnostics(error)) from None
        except httpx.NetworkError as error:
            diagnostics = self._transport_diagnostics(error)
            certificate = self._certificate_error(error)
            if certificate is not None:
                verify_code = getattr(certificate, 'verify_code', None)
                if isinstance(verify_code, int) and 0 <= verify_code <= 1000:
                    diagnostics['tls_verify_code'] = verify_code
                raise ProviderError('模型服务证书验证失败，请检查服务证书与受信任 CA 配置；已有结果已保留', code='tls_certificate', diagnostics=diagnostics) from None
            raise ProviderError('无法连接模型服务，请稍后重试；原文已保留', code='transport_connection', retryable=True, diagnostics=diagnostics) from None
        except (httpx.LocalProtocolError, httpx.UnsupportedProtocol):
            raise ProviderError('模型请求协议无效，请检查接口配置；原文已保留', code='invalid_request') from None
        except httpx.DecodingError:
            raise ProviderError('模型服务响应格式无效，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics()) from None
        except httpx.HTTPError:
            raise ProviderError('无法连接模型服务，请检查模型地址和网络；原文已保留') from None
        if response.status_code in {401,403}:
            raise ProviderError('模型服务认证失败，请检查 API key 与账户权限', code='authentication', diagnostics={'http_status': response.status_code})
        if response.status_code == 429:
            raise ProviderError('模型服务请求受限，请稍后重试',503, code='rate_limit', retryable=True, retry_after=self._retry_after(response), diagnostics={'http_status': response.status_code})
        if response.status_code in {408, 504, 524}:
            raise ProviderError(f'模型网关等待响应超时（HTTP {response.status_code}），请稍后重试；已有结果已保留', 504, code='upstream_timeout', retryable=True, retry_after=self._retry_after(response), diagnostics={'http_status': response.status_code})
        if not response.is_success:
            retryable = response.status_code in {500, 502, 503}
            raise ProviderError('模型服务返回错误，请检查所选模型、接口协议与 JSON 输出配置',
                code='upstream_error' if response.status_code >= 500 else 'invalid_request', retryable=retryable,
                retry_after=self._retry_after(response) if retryable else None, diagnostics={'http_status': response.status_code})
        try:
            data = streamed if streamed is not None else json.loads(response_content)
            if not isinstance(data, dict):
                raise ValueError('Expected response object')
            self._record_response_metadata(data)
            self.response_model = str(data.get('model') or self.model)[:200]
            if self.wire_api == 'responses':
                if data.get('status') != 'completed':
                    raise self._response_failure(data)
                content = ''.join(block['text'] for output in data['output'] if isinstance(output, dict) and output.get('type') == 'message' for block in output.get('content', []) if isinstance(block, dict) and block.get('type') == 'output_text' and isinstance(block.get('text'), str))
            else:
                choice = data['choices'][0]
                if choice.get('finish_reason') not in {None, 'stop'}:
                    if choice.get('finish_reason') == 'length':
                        raise ProviderError('模型输出预算不足，请提高输出预算；已有结果已保留', code='output_budget')
                    raise ProviderError('模型输出未完整完成，已有结果已保留', code='output_incomplete')
                content = choice['message']['content']
            if not isinstance(content,str) or not content.strip():
                raise ValueError('No model content')
            self.response_model = str(data.get('model') or self.model)[:200]
            return content.strip()
        except ProviderError as error:
            error.diagnostics = {**error.diagnostics, 'http_status': response.status_code}
            raise
        except (KeyError,IndexError,ValueError,TypeError,AttributeError):
            raise ProviderError('模型服务返回了无法读取的结果，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics()) from None

    def _json(self, prompt: str, data: dict[str, Any]) -> dict[str, Any]:
        return self.complete_json(prompt, data, max_output_tokens=3000)

    def audit_knowledge_bundle(self, bundle: dict) -> dict:
        """Ask for bounded maintenance proposals while validating their scope."""
        prompt = self._prompt('knowledge_maintenance.txt')
        data = self.complete_json(prompt, bundle, max_output_tokens=2200, reasoning_effort='minimal')
        raw = data.get('issues')
        if raw is None:
            raw = []
        if not isinstance(raw, list) or len(raw) > 32:
            raise ProviderError('模型返回的维护建议数量无效，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics())
        chunks = {
            str(item.get('chunk_id')): str(item.get('content') or '')
            for item in bundle.get('chunks', []) if isinstance(item, dict) and item.get('chunk_id')
        }
        subjects = {str(item) for item in bundle.get('subject_ids', [])}
        normalized = []
        for item in raw:
            if not isinstance(item, dict):
                raise ProviderError('模型返回的维护建议格式无效，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics())
            kind = item.get('kind')
            if kind not in {'identity', 'relation', 'evidence', 'coverage', 'importance', 'structure'}:
                raise ProviderError('模型返回了未知的维护问题类型，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics())
            raw_subjects = item.get('subject_ids', [])
            if not isinstance(raw_subjects, list) or len(raw_subjects) > 20:
                raise ProviderError('模型返回的维护对象数量无效，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics())
            item_subjects = [str(value) for value in raw_subjects if str(value) in subjects]
            if len(item_subjects) != len(raw_subjects):
                raise ProviderError('模型返回了超出上下文范围的对象，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics())
            citations = item.get('citations', [])
            if not isinstance(citations, list) or len(citations) > 8:
                raise ProviderError('模型返回的维护证据数量无效，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics())
            verified = []
            for citation in citations:
                if not isinstance(citation, dict):
                    raise ProviderError('模型返回的维护证据格式无效，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics())
                chunk_id, quote = citation.get('chunk_id'), citation.get('source_text') or citation.get('quote')
                if not isinstance(chunk_id, str) or chunk_id not in chunks or not isinstance(quote, str) or not quote.strip():
                    raise ProviderError('模型返回了不存在的维护证据，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics())
                if canonical_quote(chunks[chunk_id], quote) is None:
                    raise ProviderError('模型返回的维护引文无法在原文中核验，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics())
                verified.append({'chunk_id': chunk_id, 'quote': quote.strip()})
            confidence = item.get('confidence', 0)
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ProviderError('模型返回的维护置信度无效，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics())
            action = item.get('action') if isinstance(item.get('action'), dict) else {}
            queries = item.get('external_queries', [])
            normalized.append({
                'kind': kind,
                'summary': str(item.get('summary') or '')[:1000],
                'reasoning': str(item.get('reasoning') or '')[:4000],
                'subject_ids': item_subjects,
                'citations': verified,
                'action': action,
                'confidence': float(confidence),
                'confidence_factors': item.get('confidence_factors') if isinstance(item.get('confidence_factors'), dict) else {},
                'external_queries': [str(value)[:300] for value in queries[:4] if isinstance(value, str)] if isinstance(queries, list) else [],
            })
        return {
            'issues': normalized,
            'model_version': self.response_model or self.model,
            'prompt_version': 'maintenance-sha256:' + hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
        }

    def _json_with_image(self, prompt: str, data: dict[str, Any], image_data_url: str) -> dict[str, Any]:
        content = self._complete(
            prompt,
            json.dumps(data, ensure_ascii=False),
            json_output=True,
            max_output_tokens=3000,
            image_data_url=image_data_url,
        )
        try:
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError('Expected object')
            return result
        except (json.JSONDecodeError, ValueError):
            raise ProviderError('模型返回的结构化 JSON 无效，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics()) from None

    def complete_json(self, system: str, payload: dict, *, max_output_tokens: int, reasoning_effort: str | None = None) -> dict:
        content = self._complete(system, json.dumps(payload,ensure_ascii=False), json_output=True, max_output_tokens=max_output_tokens, reasoning_effort=reasoning_effort)
        try:
            result = json.loads(content)
            if not isinstance(result,dict):
                raise ValueError('Expected object')
            return result
        except (json.JSONDecodeError,ValueError):
            raise ProviderError('模型返回的结构化 JSON 无效，已有结果已保留', code='invalid_response', diagnostics=self._http_diagnostics()) from None

    @staticmethod
    def _context(chunks: list[PaperChunk], *, prioritize_sections: bool = True) -> tuple[list[dict[str, str | None]],dict[str,str]]:
        # Prefer major research sections before filling the remaining bounded context.
        ordered = sorted(chunks,key=lambda c: (0 if any(term in (c.section or '').casefold() for term in ('abstract','method','result','limitation','introduction')) else 1, c.page or 0, c.id)) if prioritize_sections else chunks
        remaining = MAX_CONTEXT_CHARS
        context: list[dict[str,str | None]] = []
        sent: dict[str,str] = {}
        for chunk in ordered[:24]:
            if remaining <= 0:
                break
            source = chunk.content[:min(MAX_CHUNK_CHARS,remaining)]
            if source.strip():
                context.append({'chunk_id':chunk.id,'section':chunk.section,'content':source})
                sent[chunk.id] = source
                remaining -= len(source)
        return context,sent

    @staticmethod
    def _citations(raw: Any, sent: dict[str,str], chunks: dict[str,PaperChunk], claim: str) -> tuple[list[VerifiedCitation],bool]:
        if not isinstance(raw,list) or not raw or len(raw) > 10:
            return [],False
        verified: list[VerifiedCitation] = []
        valid = True
        seen: set[tuple[str,str]] = set()
        for item in raw:
            if not isinstance(item,dict):
                valid = False
                continue
            chunk_id,quote = item.get('chunk_id'),item.get('source_text')
            if not isinstance(chunk_id,str) or not isinstance(quote,str) or chunk_id not in sent:
                valid = False
                continue
            sent_quote = canonical_quote(sent[chunk_id],quote)
            original = chunks[chunk_id]
            source = canonical_quote(original.content,quote)
            if sent_quote is None or source is None:
                valid = False
                continue
            key = (chunk_id,source)
            if key not in seen:
                seen.add(key)
                source_type = getattr(original, 'source_type', None) or ('explicit' if claim == source else 'llm_summary')
                verified.append(VerifiedCitation(original,source,claim,source_type))
        return verified,valid and bool(verified)

    @staticmethod
    def _answer_notes(data: dict[str, Any]) -> dict[str, Any]:
        """Keep optional provenance notes bounded and presentation-safe."""
        def values(key: str) -> list[str]:
            raw = data.get(key)
            if not isinstance(raw, list):
                return []
            return [item.strip() for item in raw[:8]
                    if isinstance(item, str) and item.strip() and len(item) <= 1200]
        return {
            'facts': values('facts'),
            'inferences': values('inferences'),
            'unknowns': values('unknowns'),
            'needs_more_context': data.get('needs_more_context') is True,
        }

    def analyze(self, chunks: list[PaperChunk]) -> AnalysisResult:
        from .cards import CARD_ALIASES, LIST_FIELDS, SINGLE_FIELDS
        from .base import CardEntry, KnowledgeCandidateEntry, KnowledgeRelationEntry
        context, sent = self._context(chunks)
        if not context:
            return AnalysisResult()
        data = self._json(self._prompt('paper_analysis.txt'), {'chunks':context,'context_is_partial':sum(len(c.content) for c in chunks) > sum(len(v) for v in sent.values())})
        raw_card = data.get('card') if isinstance(data.get('card'),dict) else data
        lookup = {chunk.id:chunk for chunk in chunks}
        result = AnalysisResult(model_version=self.response_model,prompt_version='paper_card_v1')
        def validated_entry(item: Any, section_summary: bool = False) -> CardEntry | None:
            if not isinstance(item,dict):
                return None
            content = item.get('content')
            if not isinstance(content,str) or not content.strip() or len(content) > 8000:
                return None
            citations,valid = self._citations(item.get('citations'),sent,lookup,content.strip())
            if not valid:
                return None
            section = citations[0].chunk.section
            if section_summary and item.get('section') is not None:
                if any(citation.chunk.section != item['section'] for citation in citations):
                    return None
                section = str(item['section'])
            return CardEntry(content.strip(),citations,section)
        for field in SINGLE_FIELDS:
            raw = raw_card.get(field)
            if raw is None and field in CARD_ALIASES:
                raw = raw_card.get(CARD_ALIASES[field])
            item = validated_entry(raw)
            result.card[field] = item
            if item is not None:
                legacy = CARD_ALIASES.get(field,field)
                if legacy in ('one_liner','problem','method','findings','limitations'):
                    setattr(result,legacy,item.content)
        for field in LIST_FIELDS:
            raw = raw_card.get(field,[])
            items: list[CardEntry] = []
            if isinstance(raw,list):
                for value in raw[:32]:
                    entry = validated_entry(value,field == 'section_summaries')
                    if entry:
                        items.append(entry)
            if field == 'tldr' and not 3 <= len(items) <= 5:
                items = []
            result.card[field] = items
        for value in result.card.values():
            items = value if isinstance(value,list) else [value] if value is not None else []
            for item in items:
                result.citations.extend(item.citations)
        corpus = '\n'.join(sent.values()).casefold()
        concepts = data.get('concepts',[])
        if isinstance(concepts,list):
            result.concepts = list(dict.fromkeys(term for term in concepts[:16] if isinstance(term,str) and 1 <= len(term) <= 100 and term.casefold() in corpus))
        # Legacy one-shot providers may return the optional knowledge fields.
        # Keep the same evidence boundary as Paper Card entries.
        allowed_types = {'paper', 'method', 'dataset', 'benchmark', 'task', 'metric', 'concept', 'venue'}
        allowed_roles = {'proposed', 'used', 'baseline', 'cited', 'compared'}
        for item in data.get('knowledge_candidates', []) if isinstance(data.get('knowledge_candidates'), list) else []:
            if not isinstance(item, dict) or item.get('entity_type') not in allowed_types or item.get('role', 'cited') not in allowed_roles:
                continue
            name = item.get('name'); citations, valid = self._citations(item.get('citations'), sent, lookup, str(item.get('description') or name or ''))
            confidence = item.get('confidence', .5)
            if isinstance(name, str) and name.strip() and valid and isinstance(confidence, (int, float)) and 0 <= confidence <= 1:
                aliases = item.get('aliases', []) if isinstance(item.get('aliases'), list) else []
                result.knowledge_candidates.append(KnowledgeCandidateEntry(item['entity_type'], name.strip(), ' '.join(name.casefold().split()), [a.strip() for a in aliases if isinstance(a, str) and a.strip()], item.get('description') if isinstance(item.get('description'), str) else None, item.get('role', 'cited'), float(confidence), citations))
        allowed_relations = {'builds_on', 'extends', 'compares_with', 'replaces', 'uses_dataset', 'evaluated_on', 'inspired_by', 'contrasts_with', 'requires_concept'}
        for item in data.get('knowledge_relations', []) if isinstance(data.get('knowledge_relations'), list) else []:
            if not isinstance(item, dict) or item.get('relation') not in allowed_relations:
                continue
            source, target = item.get('source_name'), item.get('target_name'); confidence = item.get('confidence', .5)
            citations, valid = self._citations(item.get('citations'), sent, lookup, str(item.get('description') or ''))
            if isinstance(source, str) and isinstance(target, str) and source.strip() and target.strip() and valid and isinstance(confidence, (int, float)) and 0 <= confidence <= 1:
                result.knowledge_relations.append(KnowledgeRelationEntry(item['relation'], source.strip(), ' '.join(source.casefold().split()), target.strip(), ' '.join(target.casefold().split()), item.get('description') if isinstance(item.get('description'), str) else None, float(confidence), citations))
        return result

    def ask(self, question: str, chunks: list[PaperChunk]) -> AnswerResult:
        # Select relevant chunks first so late-paper evidence is not silently omitted.
        from .mock import tokens
        query = tokens(question)
        ordered = sorted(chunks,key=lambda c: (-len(tokens(c.content)&query), c.page or 0, c.id))
        context,sent = self._context(ordered,prioritize_sections=False)
        if not context:
            return AnswerResult(ABSTENTION,[],True)
        data = self._json(self._prompt('paper_ask.txt'), {'question':question,'chunks':context})
        answer = data.get('answer')
        if data.get('insufficient_evidence') is not False or not isinstance(answer,str) or not answer.strip() or len(answer) > 16000:
            return AnswerResult(ABSTENTION,[],True)
        citations,valid = self._citations(data.get('citations'),sent,{c.id:c for c in chunks},answer.strip())
        if not valid:
            return AnswerResult(ABSTENTION,[],True)
        return AnswerResult(answer.strip(),[],False,citations,**self._answer_notes(data))

    def ask_with_image(self, question: str, chunks: list[PaperChunk], image_data_url: str) -> AnswerResult:
        """Ask about a rendered PDF page while preserving text citations.

        Visual observations are intentionally allowed to have no text citation;
        the API marks the response as visual so the reader can distinguish them
        from claims backed by an extracted passage.
        """
        from .mock import tokens
        query = tokens(question)
        ordered = sorted(chunks, key=lambda c: (-len(tokens(c.content) & query), c.page or 0, c.id))
        context, sent = self._context(ordered, prioritize_sections=False)
        # A scanned page or a figure-only page may have no extracted text. The
        # image is still a complete source for a vision-capable connection.
        # Keep the empty text context and let the model answer from the image.
        data = self._json_with_image(self._prompt('paper_ask_visual.txt'), {'question': question, 'chunks': context}, image_data_url)
        answer = data.get('answer')
        if data.get('insufficient_evidence') is not False or not isinstance(answer, str) or not answer.strip() or len(answer) > 16000:
            return AnswerResult(ABSTENTION, [], True)
        raw_citations = data.get('citations')
        if raw_citations == []:
            return AnswerResult(answer.strip(), [], False, [], **self._answer_notes(data))
        citations, valid = self._citations(raw_citations, sent, {c.id: c for c in chunks}, answer.strip())
        if not valid:
            return AnswerResult(ABSTENTION, [], True)
        return AnswerResult(answer.strip(), [], False, citations, **self._answer_notes(data))

    def translate(self, chunk: PaperChunk) -> str:
        if len(chunk.content) > MAX_TRANSLATION_CHARS:
            raise ProviderError('该原文块过长，请选择较短的段落后翻译',422)
        return self._complete(self._prompt('paper_translate.txt'),chunk.content,json_output=False)
