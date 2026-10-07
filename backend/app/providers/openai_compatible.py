"""Optional OpenAI-compatible HTTP adapter with strict local citation validation."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
from typing import Any
import httpx
from ..models import PaperChunk
from .base import AnalysisResult, AnswerResult, ProviderError, VerifiedCitation
from .validation import canonical_quote

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

    def __init__(self, *, api_key: str, base_url: str = 'https://api.openai.com/v1', model: str = 'gpt-4.1-mini', transport: httpx.BaseTransport | None = None, timeout: float = 45.0) -> None:
        try:
            url = httpx.URL(base_url)
        except (httpx.InvalidURL, ValueError):
            raise ValueError('模型 base URL 无效') from None
        if url.scheme not in {'http','https'} or not url.host or url.userinfo or url.query or url.fragment:
            raise ValueError('模型地址必须是没有凭证或查询参数的 HTTP(S) base URL')
        if not api_key.strip() or not model.strip():
            raise ValueError('模型配置缺少 API key 或 model name')
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip('/')
        self.model = model.strip()
        self._transport = transport
        self.timeout = timeout
        self.response_model: str | None = None

    @staticmethod
    def _prompt(name: str) -> str:
        return (PROMPTS_DIR / name).read_text(encoding='utf-8-sig')

    @property
    def translation_configuration_version(self) -> str:
        # API keys never enter the persisted configuration fingerprint.
        config = json.dumps([self.name, self.base_url, self.model], separators=(',', ':'))
        return hashlib.sha256(config.encode('utf-8')).hexdigest()

    @property
    def translation_prompt_version(self) -> str:
        return 'translate-sha256:' + hashlib.sha256(self._prompt('paper_translate.txt').encode('utf-8')).hexdigest()

    def _complete(self, system: str, user: str, *, json_output: bool) -> str:
        payload: dict[str, Any] = {'model':self.model,'messages':[{'role':'system','content':system},{'role':'user','content':user}], 'max_completion_tokens':3000}
        if json_output:
            payload['response_format'] = {'type':'json_object'}
        try:
            with httpx.Client(transport=self._transport, timeout=self.timeout, follow_redirects=False, headers={'Authorization':f'Bearer {self._api_key}', 'Accept-Encoding':'identity'}) as client:
                response = client.post(self.base_url + '/chat/completions', json=payload)
        except httpx.TimeoutException:
            raise ProviderError('模型服务请求超时，请稍后重试；原文和已有结果已保留',504) from None
        except httpx.HTTPError:
            raise ProviderError('无法连接模型服务，请检查模型地址和网络；原文已保留') from None
        if response.status_code in {401,403}:
            raise ProviderError('模型服务认证失败，请检查 API key 与账户权限')
        if response.status_code == 429:
            raise ProviderError('模型服务请求受限，请稍后重试',503)
        if not response.is_success:
            raise ProviderError('模型服务返回错误，请检查所选模型是否支持 Chat Completions 和 JSON 输出')
        if len(response.content) > 256000:
            raise ProviderError('模型服务响应过大，已拒绝处理')
        try:
            data = response.json()
            content = data['choices'][0]['message']['content']
            if not isinstance(content,str) or not content.strip():
                raise ValueError('No model content')
            self.response_model = str(data.get('model') or self.model)[:200]
            return content.strip()
        except (KeyError,IndexError,ValueError,TypeError):
            raise ProviderError('模型服务返回了无法读取的结果，已有结果已保留') from None

    def _json(self, prompt: str, data: dict[str, Any]) -> dict[str, Any]:
        content = self._complete(prompt, json.dumps(data,ensure_ascii=False), json_output=True)
        try:
            result = json.loads(content)
            if not isinstance(result,dict):
                raise ValueError('Expected object')
            return result
        except (json.JSONDecodeError,ValueError):
            raise ProviderError('模型返回的结构化 JSON 无效，已有结果已保留') from None

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
                verified.append(VerifiedCitation(original,source,claim,'explicit' if claim == source else 'llm_summary'))
        return verified,valid and bool(verified)

    def analyze(self, chunks: list[PaperChunk]) -> AnalysisResult:
        from .cards import CARD_ALIASES, LIST_FIELDS, SINGLE_FIELDS
        from .base import CardEntry
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
        return AnswerResult(answer.strip(),[],False,citations)

    def translate(self, chunk: PaperChunk) -> str:
        if len(chunk.content) > MAX_TRANSLATION_CHARS:
            raise ProviderError('该原文块过长，请选择较短的段落后翻译',422)
        return self._complete(self._prompt('paper_translate.txt'),chunk.content,json_output=False)
