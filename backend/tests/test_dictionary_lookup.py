from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException


def test_quick_dictionary_lookup_returns_chinese_translation_and_caches_it() -> None:
    from app.services.dictionary import lookup, clear_cache

    clear_cache()
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.url.host == 'dict.youdao.com'
        assert request.url.params['q'] == 'attention'
        return httpx.Response(200, json={
            'ec': {'word': {
                'usphone': 'əˈtenʃ(ə)n',
                'trs': [{'pos': 'n.', 'tran': '注意；注意力；关注'}],
                'return-phrase': 'attention',
            }},
        })

    first = lookup('  Attention, ', transport=httpx.MockTransport(respond))
    second = lookup('attention', transport=httpx.MockTransport(respond))

    assert first.query == 'Attention,'
    assert first.normalized_query == 'attention'
    assert first.translation == '注意；注意力；关注'
    assert first.phonetic == 'əˈtenʃ(ə)n'
    assert first.source == 'youdao'
    assert first.cached is False
    assert second.cached is True
    assert len(calls) == 1


def test_quick_dictionary_falls_back_to_free_dictionary_when_youdao_is_unavailable() -> None:
    from app.services.dictionary import lookup, clear_cache

    clear_cache()
    hosts: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host or '')
        if request.url.host == 'dict.youdao.com':
            return httpx.Response(503)
        return httpx.Response(200, json=[{
            'word': 'retrieval',
            'phonetic': '/rɪˈtriːvəl/',
            'meanings': [{
                'partOfSpeech': 'noun',
                'definitions': [{'definition': 'the act of finding something'}],
            }],
        }])

    result = lookup('retrieval', transport=httpx.MockTransport(respond))

    assert hosts == ['dict.youdao.com', 'api.dictionaryapi.dev']
    assert result.source == 'dictionaryapi'
    assert result.phonetic == '/rɪˈtriːvəl/'
    assert result.translation is None
    assert result.definitions[0].text == 'the act of finding something'


def test_quick_dictionary_reads_youdao_phrase_translation_when_no_word_entry_exists() -> None:
    from app.services.dictionary import lookup, clear_cache

    clear_cache()
    result = lookup('pay attention', transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        'ec': None,
        'web_trans': {'web-translation': [{
            'key': 'pay attention',
            'trans': [{'value': '注意'}, {'value': '留心'}],
        }]},
    })))

    assert result.translation == '注意；留心'
    assert result.definitions[0].text == '注意；留心'


def test_quick_dictionary_rejects_long_passages_before_network() -> None:
    from app.services.dictionary import lookup, clear_cache

    clear_cache()
    with pytest.raises(HTTPException) as failure:
        lookup('This is a complete sentence selected from the paper and not a word.', transport=httpx.MockTransport(lambda _: pytest.fail('network call')))

    assert failure.value.status_code == 422


def test_quick_dictionary_failure_is_safe_and_does_not_cache_error() -> None:
    from app.services.dictionary import DictionaryUnavailable, lookup, clear_cache

    clear_cache()
    calls = 0

    def fail(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout('secret upstream detail', request=request)

    for _ in range(2):
        with pytest.raises(DictionaryUnavailable) as failure:
            lookup('unknownword', transport=httpx.MockTransport(fail))
        assert 'secret' not in str(failure.value)
    assert calls == 4


def test_dictionary_endpoint_returns_a_credential_free_contract(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dictionary import DictionaryDefinition, QuickTranslation

    monkeypatch.setattr('app.api.dictionary.lookup', lambda text: QuickTranslation(
        query=text,
        normalized_query='attention',
        translation='注意；注意力',
        phonetic='əˈtenʃ(ə)n',
        definitions=(DictionaryDefinition('n.', '注意；注意力'),),
        source='youdao',
    ))
    response = client.post('/api/dictionary/lookup', json={'text': 'attention'})

    assert response.status_code == 200
    assert response.json() == {
        'query': 'attention',
        'normalized_query': 'attention',
        'translation': '注意；注意力',
        'phonetic': 'əˈtenʃ(ə)n',
        'definitions': [{'part_of_speech': 'n.', 'text': '注意；注意力', 'example': None}],
        'source': 'youdao',
        'cached': False,
    }
