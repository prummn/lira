"""Small, credential-free dictionary lookups for short PDF selections.

The reader uses this path for a word or a short term only.  It deliberately
does not call the configured model provider: common terminology should be
available immediately and without spending model tokens.  The two upstreams
are fixed public dictionary services; redirects and proxy environment values
are disabled and failures are collapsed into a safe local error.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import html
import re
import threading
import time
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
import httpx


MAX_QUERY_LENGTH = 80
MAX_QUERY_WORDS = 4
CACHE_TTL_SECONDS = 24 * 60 * 60
CACHE_MAX_ENTRIES = 512
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[’'][A-Za-z0-9]+)?(?:[-/][A-Za-z0-9]+)*")
_TAG = re.compile(r"<[^>]+>")


class DictionaryUnavailable(RuntimeError):
    """Both public dictionary services failed or returned unusable data."""


@dataclass(frozen=True)
class DictionaryDefinition:
    part_of_speech: str | None
    text: str
    example: str | None = None


@dataclass(frozen=True)
class QuickTranslation:
    query: str
    normalized_query: str
    translation: str | None
    phonetic: str | None
    definitions: tuple[DictionaryDefinition, ...]
    source: str
    cached: bool = False


@dataclass(frozen=True)
class _CacheEntry:
    value: QuickTranslation
    created_at: float


_cache: OrderedDict[str, _CacheEntry] = OrderedDict()
_cache_lock = threading.RLock()


def clear_cache() -> None:
    """Clear the process-local dictionary cache (used by tests and restarts)."""

    with _cache_lock:
        _cache.clear()


def normalize_query(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise HTTPException(422, '请选择一个英文单词或短词')
    query = re.sub(r"\s+", " ", value).strip()
    if not query:
        raise HTTPException(422, '请选择一个英文单词或短词')
    if len(query) > MAX_QUERY_LENGTH or any(ord(char) < 32 or ord(char) == 127 for char in query):
        raise HTTPException(422, '速译仅支持不超过 80 个字符的英文短词')
    # Text selections often include a trailing comma, period, or quote. Keep
    # the original query for display while trimming that visual punctuation.
    normalized = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", query)
    words = _WORD.findall(normalized)
    if not normalized or not words or len(words) > MAX_QUERY_WORDS or ' '.join(words).casefold() != normalized.casefold():
        raise HTTPException(422, '速译仅支持一个英文单词或不超过四个词的短语')
    return query, normalized.casefold()


def _clean(value: Any, limit: int = 400) -> str:
    if not isinstance(value, str):
        return ''
    value = html.unescape(_TAG.sub('', value))
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _youdao(response: httpx.Response, query: str, normalized: str) -> QuickTranslation | None:
    if response.status_code == 404:
        return None
    if not response.is_success:
        raise DictionaryUnavailable()
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    ec = payload.get('ec') if isinstance(payload, dict) else None
    word = ec.get('word', {}) if isinstance(ec, dict) else {}
    if not isinstance(word, dict):
        word = {}
    terms = word.get('trs', [])
    definitions: list[DictionaryDefinition] = []
    if isinstance(terms, list):
        for term in terms:
            if not isinstance(term, dict):
                continue
            text = _clean(term.get('tran'))
            if text:
                definitions.append(DictionaryDefinition(_clean(term.get('pos')) or None, text))
    translation = definitions[0].text if definitions else None
    phonetic = _clean(word.get('usphone')) or _clean(word.get('ukphone')) or None
    if not translation and not phonetic and isinstance(payload, dict):
        # Youdao places multi-word terms in web_trans instead of ec.word.
        web = payload.get('web_trans')
        rows = web.get('web-translation') if isinstance(web, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or _clean(row.get('key')).casefold() != normalized:
                    continue
                values: list[str] = []
                terms = row.get('trans')
                if isinstance(terms, list):
                    for term in terms:
                        if isinstance(term, dict):
                            value = _clean(term.get('value'))
                            if value and value not in values:
                                values.append(value)
                if values:
                    translation = '；'.join(values[:8])
                    definitions = [DictionaryDefinition(None, translation)]
                    break
    if not translation and not phonetic:
        return None
    return QuickTranslation(query, normalized, translation, phonetic, tuple(definitions[:8]), 'youdao')


def _free_dictionary(response: httpx.Response, query: str, normalized: str) -> QuickTranslation | None:
    if response.status_code == 404:
        return None
    if not response.is_success:
        raise DictionaryUnavailable()
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, list):
        return None
    phonetic: str | None = None
    definitions: list[DictionaryDefinition] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        phonetic = phonetic or _clean(entry.get('phonetic'))
        phonetics = entry.get('phonetics')
        if not phonetic and isinstance(phonetics, list):
            for item in phonetics:
                if isinstance(item, dict) and _clean(item.get('text')):
                    phonetic = _clean(item.get('text'))
                    break
        meanings = entry.get('meanings')
        if not isinstance(meanings, list):
            continue
        for meaning in meanings:
            if not isinstance(meaning, dict):
                continue
            pos = _clean(meaning.get('partOfSpeech')) or None
            records = meaning.get('definitions')
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                text = _clean(record.get('definition'))
                if text:
                    definitions.append(DictionaryDefinition(pos, text, _clean(record.get('example')) or None))
                if len(definitions) >= 8:
                    break
            if len(definitions) >= 8:
                break
        if len(definitions) >= 8:
            break
    if not definitions and not phonetic:
        return None
    return QuickTranslation(query, normalized, None, phonetic, tuple(definitions), 'dictionaryapi')


def lookup(query: str, *, transport: httpx.BaseTransport | None = None) -> QuickTranslation:
    original, normalized = normalize_query(query)
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(normalized)
        if entry and now - entry.created_at < CACHE_TTL_SECONDS:
            _cache.move_to_end(normalized)
            return replace(entry.value, query=original, cached=True)
        if entry:
            _cache.pop(normalized, None)

    client_transport = transport or httpx.HTTPTransport(retries=0, trust_env=False)
    try:
        with httpx.Client(
            transport=client_transport,
            timeout=httpx.Timeout(5.0, connect=2.0),
            follow_redirects=False,
            trust_env=False,
            headers={'Accept': 'application/json', 'User-Agent': 'ResearchIntelligenceWorkspace/1.0'},
        ) as client:
            try:
                response = client.get('https://dict.youdao.com/jsonapi_s', params={'doctype': 'json', 'jsonversion': '4', 'q': normalized})
                result = _youdao(response, original, normalized)
            except (httpx.HTTPError, OSError, DictionaryUnavailable):
                result = None
            if result is None:
                try:
                    response = client.get('https://api.dictionaryapi.dev/api/v2/entries/en/' + quote(normalized, safe=''))
                    result = _free_dictionary(response, original, normalized)
                except (httpx.HTTPError, OSError, DictionaryUnavailable):
                    result = None
    except (httpx.HTTPError, OSError):
        result = None
    if result is None:
        raise DictionaryUnavailable('dictionary service unavailable')
    with _cache_lock:
        _cache[normalized] = _CacheEntry(result, now)
        _cache.move_to_end(normalized)
        while len(_cache) > CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)
    return result
