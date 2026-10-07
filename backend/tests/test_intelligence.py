from __future__ import annotations

import json
import httpx
import pytest
from sqlalchemy import select

from app.db import Database
from app.models import PaperChunk
from app.providers.base import ProviderError
from app.providers.openai_compatible import OpenAICompatibleProvider


def database(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'intelligence.db').as_posix()}")
    db.migrate()
    return db


def test_responses_transport_uses_confirmed_wire_and_preserves_usage():
    seen = []
    def respond(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert str(request.url) == 'https://model.example/responses'
        assert payload['store'] is False
        assert payload['text']['format'] == {'type': 'json_object'}
        assert payload['reasoning'] == {'effort': 'high'}
        assert payload['max_output_tokens'] == 6000
        assert 'JSON' in payload['input'][0]['content'][0]['text']
        return httpx.Response(200, json={'status': 'completed', 'model': 'actual-model', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}], 'usage': {'input_tokens': 25, 'output_tokens': 7, 'total_tokens': 32, 'output_tokens_details': {'reasoning_tokens': 4}}})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', model='model', wire_api='responses', reasoning_effort='xhigh', transport=httpx.MockTransport(respond))
    assert provider.complete_json('Return JSON.', {'data': 'paper'}, max_output_tokens=6000, reasoning_effort='high') == {'ok': True}
    assert provider.last_usage['output_tokens_details']['reasoning_tokens'] == 4
    assert provider.response_model == 'actual-model'
    assert len(seen) == 1


@pytest.mark.parametrize('wire,status', [('responses', 'incomplete'), ('chat_completions', 'length')])
def test_truncated_model_outputs_fail_safely(wire, status):
    def respond(request):
        if wire == 'responses':
            return httpx.Response(200, json={'status': status, 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]})
        return httpx.Response(200, json={'choices': [{'finish_reason': status, 'message': {'content': '{"ok":true}'}}]})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', wire_api=wire, transport=httpx.MockTransport(respond))
    with pytest.raises(ProviderError):
        provider.complete_json('JSON', {}, max_output_tokens=100)


def test_cache_is_credential_free_and_keeps_actual_saved_usage(tmp_path):
    from app.services.model_calls import json_call, request_signature
    from app.models import ModelCallCache
    db = database(tmp_path)
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"ok":true}'}}], 'usage': {'prompt_tokens': 40, 'completion_tokens': 9, 'total_tokens': 49, 'secret': 'secret'}, 'model': 'actual'})
    first = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example/v1', model='model', transport=httpx.MockTransport(respond))
    second = OpenAICompatibleProvider(api_key='different-secret', base_url=first.base_url, model=first.model, transport=httpx.MockTransport(respond))
    result = json_call(db, first, 'JSON', {'source': 'full text'}, 'extract')
    cached = json_call(db, second, 'JSON', {'source': 'full text'}, 'extract')
    assert result.usage['prompt_tokens'] == 40
    assert cached.cached is True
    assert cached.usage['input_tokens'] == 0
    assert cached.usage['saved_usage']['completion_tokens'] == 9
    assert len(calls) == 1
    assert request_signature(first, 'JSON', {}, 'extract') != request_signature(first, 'changed JSON', {}, 'extract')
    with db.sessions() as session:
        record = session.scalar(select(ModelCallCache))
        assert 'secret' not in record.usage_json
        assert 'secret' not in record.key


def test_windows_cover_oversized_source_and_late_page_exactly():
    from app.providers.harness import pack_windows
    chunks = [PaperChunk(id='early', paper_id='p', page=1, content='A' * 45000), PaperChunk(id='late', paper_id='p', page=30, content='Late-page decisive result.')]
    windows = pack_windows(chunks, max_chars=20000)
    parts = [part for window in windows for part in window]
    assert ''.join(part.content for part in parts if part.chunk_id == 'early') == chunks[0].content
    assert parts[-1].chunk_id == 'late'
    assert all(sum(len(part.content) for part in window) <= 20000 for window in windows)
    assert [(part.start, part.end) for part in parts if part.chunk_id == 'early'] == [(0, 20000), (20000, 40000), (40000, 45000)]


def test_staged_analysis_validates_submitted_slice_and_all_windows(tmp_path):
    from app.providers.harness import analyze_full_paper
    db = database(tmp_path)
    chunks = [PaperChunk(id='first', paper_id='p', page=1, section='Method', content='EARLY CLAIM ' + 'x' * 44000), PaperChunk(id='last', paper_id='p', page=50, section='Results', content='Late evaluation achieves 71 correct passages.')]
    requests = []
    def respond(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        requests.append(payload)
        if 'chunks' in payload:
            part = payload['chunks'][-1]
            facts = [{'content': 'A supported fact.', 'citations': [{'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content'][:45]}]}]
            if payload['window_index'] == 1:
                facts.append({'content': 'Forged out-of-slice claim.', 'citations': [{'part_id': part['part_id'], 'chunk_id': 'first', 'source_text': 'EARLY CLAIM'}]})
            answer = {'facts': facts}
        else:
            assert all(fact['content'] != 'Forged out-of-slice claim.' for fact in payload['facts'])
            late_id = next(source['id'] for source in payload['evidence'] if source['chunk_id'] == 'last')
            answer = {'main_results': {'content': 'The late evaluation reports 71 correct passages.', 'citation_ids': [late_id]}}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example/v1', transport=httpx.MockTransport(respond))
    result = analyze_full_paper(db, provider, chunks)
    assert result.analysis.findings == 'The late evaluation reports 71 correct passages.'
    assert result.analysis.citations[0].chunk.page == 50
    assert result.report['coverage']['processed_chars'] == sum(len(c.content) for c in chunks)
    assert result.report['invalid_entries'] == 1
    assert result.report['rejections'] == [{'phase': 'extract', 'window_index': 1,
        'field': 'facts[1]', 'reason': 'quote_not_found'}]
    assert len([payload for payload in requests if 'chunks' in payload]) == 3
    calls = len(requests)
    again = analyze_full_paper(db, provider, chunks)
    assert len(requests) == calls + 1
    assert requests[-1]['window_index'] == 1
    assert again.report['usage']['remote_calls'] == 1
    assert again.report['usage']['cache_hits'] == 3


def test_extraction_uses_local_source_ids_without_retyping_pdf_words(tmp_path):
    from app.providers.harness import analyze_full_paper
    db = database(tmp_path)
    original = 'We evaluate retrieval-\naugmented generation; accuracy is 71%. '
    long_text = original + ('Original scientific discussion.\n' * 90)
    seen = []
    def respond(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        if 'chunks' in payload:
            seen.extend(payload['chunks'])
            assert all(len(p['content']) <= 1000 for p in payload['chunks'])
            source = next(p for p in payload['chunks'] if original in p['content'])
            answer = {'facts': [
                {'content': 'Reported accuracy is 71%.', 'source_ids': [source['source_id']]},
                {'content': 'Forged source must not fall back to quotations.', 'source_ids': ['unknown'],
                 'citations': [{'part_id': source['part_id'], 'chunk_id': source['chunk_id'], 'source_text': original}]}]}
        else:
            assert original in payload['evidence'][0]['source_text']
            answer = {'main_results': {'content': 'Reported accuracy is 71%.', 'citation_ids': payload['facts'][0]['citation_ids']}}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', transport=httpx.MockTransport(respond))
    chunk = PaperChunk(id='real-source', paper_id='p', page=5, section='Results', content=long_text)
    result = analyze_full_paper(db, provider, [chunk])
    assert ''.join(part['content'] for part in seen) == long_text
    assert result.analysis.citations[0].source_text == seen[0]['content']
    assert result.report['invalid_entries'] == 1
    assert result.report['rejections'][0]['reason'] == 'invalid_source_ids'


def test_structure_records_observed_captions_not_invented_chart_values():
    from app.services.structure import extract_structure
    chunks = [PaperChunk(id='figure', paper_id='p', page=3, section='4 Results', content='Figure 2: Accuracy across retrieval depths.\nTable 1. Dataset statistics.'), PaperChunk(id='ref', paper_id='p', page=8, section='References', content='[12] A. Author. Retrieval study. 2024.')]
    structure = extract_structure(chunks)
    assert structure['figures'][0]['source_text'].startswith('Figure 2:')
    assert structure['tables'][0]['source_text'].startswith('Table 1.')
    assert structure['references'][0]['chunk_id'] == 'ref'
    assert 'values' not in structure['figures'][0]


def test_failure_retains_actual_billed_usage_in_progress(tmp_path):
    from app.providers.harness import analyze_full_paper
    db = database(tmp_path)
    reports = []
    def respond(request):
        return httpx.Response(200, json={'status': 'incomplete', 'model': 'actual', 'usage': {'input_tokens': 30, 'output_tokens': 100}, 'output': []})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', wire_api='responses', transport=httpx.MockTransport(respond))
    with pytest.raises(ProviderError):
        analyze_full_paper(db, provider, [PaperChunk(id='chunk', paper_id='p', content='Actual source text.')], progress=lambda phase, completed, total, report: reports.append(json.loads(json.dumps(report))))
    assert reports[-1]['usage']['input_tokens'] == 30
    assert reports[-1]['usage']['output_tokens'] == 100
    assert reports[-1]['usage']['calls'][0]['model'] == 'actual'


def test_analysis_fingerprint_changes_with_source_geometry_and_provider():
    from app.providers.harness import analysis_fingerprint
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', model='first')
    chunk = PaperChunk(id='a', paper_id='p', page=1, content='Source', bbox_json='[1,2,3,4]')
    original = analysis_fingerprint(provider, [chunk])
    chunk.bbox_json = '[2,3,4,5]'
    assert analysis_fingerprint(provider, [chunk]) != original
    chunk.bbox_json = '[1,2,3,4]'
    provider.model = 'second'
    assert analysis_fingerprint(provider, [chunk]) != original


def test_invalid_stage_is_not_reused_as_successful_cache(tmp_path):
    from app.providers.harness import analyze_full_paper
    db = database(tmp_path)
    attempts = []
    def respond(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        attempts.append(payload)
        if len(attempts) == 1:
            answer = {}
        elif 'chunks' in payload:
            part = payload['chunks'][0]
            answer = {'facts': [{'content': 'Supported.', 'citations': [{'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content']}]}]}
        else:
            answer = {'method': {'content': 'Supported.', 'citation_ids': payload['facts'][0]['citation_ids']}}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', transport=httpx.MockTransport(respond))
    chunks = [PaperChunk(id='p', paper_id='a', content='Original scientifically meaningful text.')]
    with pytest.raises(ProviderError):
        analyze_full_paper(db, provider, chunks)
    assert analyze_full_paper(db, provider, chunks).analysis.method == 'Supported.'
    assert len(attempts) == 3


def test_window_metadata_is_bounded_without_dropping_small_chunks():
    from app.providers.harness import pack_windows
    chunks = [PaperChunk(id=f'c-{index:05d}', paper_id='p', page=1, content='abc') for index in range(1000)]
    windows = pack_windows(chunks)
    assert max(len(window) for window in windows) <= 128
    assert sum(len(window) for window in windows) == 1000


@pytest.mark.parametrize('body', [[], {'status': 'completed', 'output': [None]}, {'status': 'completed', 'output': [{'type': 'message', 'content': [None]}]}])
def test_malformed_response_shapes_are_safe_provider_failures(body):
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', wire_api='responses', transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
    with pytest.raises(ProviderError):
        provider.complete_json('JSON', {}, max_output_tokens=100)


def test_long_paper_reduction_remains_bounded_and_retains_late_evidence(tmp_path):
    from app.providers.harness import analyze_full_paper
    db = database(tmp_path)
    stages = []
    reductions = []
    def respond(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        if 'chunks' in payload:
            part = payload['chunks'][0]
            citation = {'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content'][:120]}
            answer = {'facts': [{'content': f"Fact {index} from {part['chunk_id']}. " + 'd' * 3400, 'citations': [citation]} for index in range(10)]}
        elif payload.get('stage') == 'reduce':
            reductions.append(payload)
            assert len(json.dumps({'facts': payload['facts'], 'evidence': payload['evidence']}, ensure_ascii=False)) <= 48000
            assert payload['max_facts'] <= (len(payload['facts']) + 1) // 2
            answer = {'facts': [{'content': 'Compressed relevant evidence.', 'fact_ids': [fact['id'] for fact in payload['facts']], 'citation_ids': list(dict.fromkeys(citation_id for fact in payload['facts'] for citation_id in fact['citation_ids']))}]}
        else:
            answer = {'main_results': {'content': 'Late evidence remains available.', 'citation_ids': payload['facts'][-1]['citation_ids'][-1:]}}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', transport=httpx.MockTransport(respond))
    chunks = [PaperChunk(id=f'page-{index}', paper_id='p', page=index + 1, content=f'Original experiment on page {index + 1}. ' + 'x' * 18000) for index in range(6)]
    result = analyze_full_paper(db, provider, chunks, progress=lambda phase, *args: stages.append(phase))
    assert reductions and 'reduce' in stages
    assert result.analysis.citations[0].chunk.page == 6
    assert result.report['coverage']['processed_windows'] == 6
    assert result.report['coverage']['processed_chars'] == sum(len(chunk.content) for chunk in chunks)
    assert result.report['missing_fields']
    assert result.report['semantic_verification'] == 'not_automatically_proven'


@pytest.mark.parametrize('bad_stage', ['extract', 'reduce', 'synthesize'])
def test_partial_stage_retry_replaces_rejected_output_and_reuses_valid_stages(tmp_path, bad_stage):
    from collections import Counter
    from app.providers.harness import analyze_full_paper
    db = database(tmp_path)
    calls = Counter()
    failed_once = False
    def respond(request):
        nonlocal failed_once
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        stage = 'extract' if 'chunks' in payload else payload.get('stage', 'synthesize')
        calls[stage] += 1
        if stage == 'extract':
            part = payload['chunks'][0]
            citation = {'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content'][:80]}
            count = 12 if bad_stage == 'reduce' else 1
            answer = {'facts': [{'content': f"Fact {index} from {part['chunk_id']}. " + ('d' * 3300 if bad_stage == 'reduce' else ''),
                'citations': [citation]} for index in range(count)]}
        elif stage == 'reduce':
            answer = {'facts': [{'content': 'Compressed supported fact.', 'fact_ids': [fact['id'] for fact in payload['facts']], 'citation_ids': list(dict.fromkeys(citation_id for fact in payload['facts'] for citation_id in fact['citation_ids']))}]}
        else:
            answer = {'method': {'content': 'A supported method.', 'citation_ids': payload['facts'][-1]['citation_ids']}}
        if stage == bad_stage and not failed_once:
            failed_once = True
            invalid = {'content': 'Rejected claim.', 'citations': [
                {'part_id': 'missing', 'chunk_id': 'missing', 'source_text': 'Invented source.'}]}
            if stage == 'synthesize':
                answer['main_results'] = invalid
            else:
                answer['facts'].append(invalid)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', transport=httpx.MockTransport(respond))
    chunks = [PaperChunk(id=f'page-{index}', paper_id='p', page=index + 1,
        content=f'Original method from page {index + 1}. ' + 'x' * 11000) for index in range(2)]
    first = analyze_full_paper(db, provider, chunks)
    assert first.report['partial'] and first.report['invalid_entries'] == 1
    assert first.report['rejections'][0]['phase'] == bad_stage
    assert first.report['rejections'][0]['reason'] in {'unknown_source', 'invalid_parent_ids'}
    first_calls = calls.copy()
    retry = analyze_full_paper(db, provider, chunks)
    assert not retry.report['partial'] and retry.report['invalid_entries'] == 0
    assert retry.report['rejections'] == []
    assert calls[bad_stage] == first_calls[bad_stage] + 1
    assert all(calls[stage] == count for stage, count in first_calls.items() if stage != bad_stage)
    assert retry.report['usage']['remote_calls'] == 1
    assert retry.report['usage']['cache_hits'] > 0
    again = analyze_full_paper(db, provider, chunks)
    assert again.report['usage']['remote_calls'] == 0


def test_synthesis_resolves_immutable_ids_to_exact_original_quotes(tmp_path):
    from app.providers.harness import analyze_full_paper
    db = database(tmp_path)
    quote = 'The system fails on contradictory evidence despite a 71 percent score.'
    def respond(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        if 'chunks' in payload:
            part = payload['chunks'][0]
            answer = {'facts': [{'content': 'The method has a measured weakness.', 'citations': [{'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': quote}]}]}
        else:
            assert len(payload['evidence']) == 1
            assert payload['evidence'][0]['source_text'] == quote
            assert 'citations' not in payload['facts'][0]
            citation_id = payload['facts'][0]['citation_ids'][0]
            answer = {'limitations': {'content': 'Contradictory evidence remains a failure case at the reported score.', 'citation_ids': [citation_id]}}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', transport=httpx.MockTransport(respond))
    chunk = PaperChunk(id='late', paper_id='p', page=40, section='Limitations', content=quote, bbox_json='[1,2,3,4]')
    result = analyze_full_paper(db, provider, [chunk])
    assert result.analysis.limitations
    assert result.analysis.citations[0].source_text == quote
    assert result.analysis.citations[0].chunk.page == 40
    assert result.report['fact_coverage'] == {'total': 1, 'retained': 1, 'complete': True}


def test_reduction_preserves_negative_and_late_facts_and_rejects_foreign_ids():
    from app.providers.harness import _citation_pool, _reduce_facts
    from app.providers.harness import SourcePart, _facts
    parts = {'first:0:38': SourcePart('first:0:38', 'first', 0, 38, 1, 'Method', 'The method improves normal retrieval.'),
             'late:0:49': SourcePart('late:0:49', 'late', 0, 49, 30, 'Limitations', 'It fails when evidence contains contradictions.')}
    raw = [{'content': 'Positive experiment.', 'citations': [{'part_id': part.part_id, 'chunk_id': part.chunk_id, 'source_text': part.content}]} for part in parts.values()]
    facts, _ = _facts(raw, parts)
    facts[-1]['content'] = 'Negative experiment with contradictory evidence.'
    pool = _citation_pool(facts, parts)
    refs = list(pool)
    merged = [{'content': 'Normal retrieval improves, but contradictory evidence fails.', 'fact_ids': [fact['id'] for fact in facts], 'citation_ids': refs}]
    reduced, invalid = _reduce_facts(merged, facts, pool, parts, max_facts=1)
    assert invalid == 0
    assert len(reduced) == 1
    assert len(reduced[0]['citations']) == 2
    assert set(reduced[0]['source_fact_ids']) == {fact['id'] for fact in facts}
    with pytest.raises(ProviderError):
        _reduce_facts([{'content': 'Positive only.', 'fact_ids': [facts[0]['id']], 'citation_ids': [refs[0]]}], facts, pool, parts, max_facts=1)
    with pytest.raises(ProviderError):
        _reduce_facts([{'content': 'Invalid.', 'fact_ids': [fact['id'] for fact in facts], 'citation_ids': ['foreign']}], facts, pool, parts, max_facts=1)
    with pytest.raises(ProviderError):
        _reduce_facts(merged, facts[:1], pool, parts, max_facts=1)
    with pytest.raises(ProviderError):
        _reduce_facts([{'content': 'Foreign group quote.', 'fact_ids': [facts[0]['id']], 'citation_ids': [refs[-1]]}], facts[:1], pool, parts, max_facts=1)


def test_fingerprint_uses_prompts_loaded_at_start_even_when_files_change(tmp_path, monkeypatch):
    import app.providers.harness as harness
    prompt_dir = tmp_path / 'prompts'
    prompt_dir.mkdir()
    for name in ('paper_extract.txt', 'paper_reduce.txt', 'paper_synthesize.txt'):
        original = harness.PROMPTS_DIR / name
        (prompt_dir / name).write_text(original.read_text(encoding='utf-8-sig') if original.exists() else 'Reduce facts and return JSON.', encoding='utf-8')
    monkeypatch.setattr(harness, 'PROMPTS_DIR', prompt_dir)
    db = database(tmp_path)
    captured_systems = []
    def respond(request):
        body = json.loads(request.content)
        captured_systems.append(body['messages'][0]['content'])
        payload = json.loads(body['messages'][-1]['content'])
        if 'chunks' in payload:
            (prompt_dir / 'paper_synthesize.txt').write_text('A new synthesis prompt that this job did not use.', encoding='utf-8')
            part = payload['chunks'][0]
            answer = {'facts': [{'content': 'Supported.', 'citations': [{'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content']}]}]}
        else:
            fact = payload['facts'][0]
            answer = {'method': {'content': 'Supported.', **({'citation_ids': fact['citation_ids']} if 'citation_ids' in fact else {'citations': fact['citations']})}}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', transport=httpx.MockTransport(respond))
    chunks = [PaperChunk(id='p', paper_id='a', content='An original scientific method.')]
    expected = harness.analysis_fingerprint(provider, chunks)
    result = harness.analyze_full_paper(db, provider, chunks)
    assert result.report['result_fingerprint'] == expected
    assert result.report['result_fingerprint'] != harness.analysis_fingerprint(provider, chunks)
    assert 'A new synthesis prompt' not in captured_systems[-1]


def test_card_ids_cannot_reach_evidence_outside_final_submitted_pool():
    from app.providers.harness import _card, _citation_pool, _facts, pack_windows
    chunks = [PaperChunk(id='method', paper_id='p', page=1, content='The model improves standard retrieval.'),
              PaperChunk(id='negative', paper_id='p', page=30, content='It fails on contradictory retrieved evidence.')]
    parts = {part.part_id: part for window in pack_windows(chunks) for part in window}
    facts, _ = _facts([{'content': part.content, 'citations': [{'part_id': part.part_id, 'chunk_id': part.chunk_id, 'source_text': part.content}]} for part in parts.values()], parts)
    pool = _citation_pool(facts, parts)
    valid, foreign = list(pool)
    with pytest.raises(ProviderError):
        _card({'method': {'content': 'A foreign negative claim.', 'citation_ids': [foreign]}}, facts[:1], parts, chunks, 'test', 'prompt', pool)
    with pytest.raises(ProviderError):
        _card({'method': {'content': 'Unknown IDs cannot fall back to a valid quote.', 'citation_ids': ['unknown'], 'citations': facts[0]['citations']}}, facts[:1], parts, chunks, 'test', 'prompt', pool)
    accepted, invalid = _card({'method': {'content': 'A supported method.', 'citation_ids': [valid]}}, facts[:1], parts, chunks, 'test', 'prompt', pool)
    assert invalid == 0 and accepted.citations[0].chunk.id == 'method'


def test_nonconvergent_id_reduction_fails_without_repeating_levels(tmp_path, monkeypatch):
    import app.providers.harness as harness
    monkeypatch.setattr(harness, 'REDUCE_CHARS', 1000)
    db = database(tmp_path)
    calls = []
    def respond(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        calls.append(payload)
        if 'chunks' in payload:
            part = payload['chunks'][0]
            answer = {'facts': [{'content': 'Observed scientific result. ' + 's' * 180, 'citations': [{'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content'][:450]}]}]}
        else:
            assert payload['stage'] == 'reduce'
            answer = {'facts': [{'content': fact['content'], 'fact_ids': [fact['id']], 'citation_ids': fact['citation_ids']} for fact in payload['facts']]}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', transport=httpx.MockTransport(respond))
    chunks = [PaperChunk(id=f'c-{index}', paper_id='p', page=index + 1, content=f'Original {index}. ' + 'x' * 19500) for index in range(2)]
    with pytest.raises(ProviderError, match='未缩减'):
        harness.analyze_full_paper(db, provider, chunks)
    assert len([payload for payload in calls if payload.get('stage') == 'reduce']) == 2
    assert not any(payload.get('stage') == 'synthesize' for payload in calls)


def test_dense_reduction_groups_have_capacity_for_every_mandatory_fact():
    from app.providers.harness import _citation_pool, _context_groups, _facts, _reduce_facts, SourcePart
    parts, facts = {}, []
    for index in range(147):
        source = f'Observed unique result {index}.'
        part = SourcePart(f'c{index}:0:{len(source)}', f'c{index}', 0, len(source), index + 1, 'Results', source)
        parts[part.part_id] = part
        verified, invalid = _facts([{'content': f'Result {index}.', 'citations': [{'part_id': part.part_id, 'chunk_id': part.chunk_id, 'source_text': source}]}], parts)
        assert invalid == 0
        facts.extend(verified)
    pool = _citation_pool(facts, parts)
    groups = _context_groups(facts, pool)
    assert max(len(group) for group in groups) <= 24
    preserved = set()
    for group in groups:
        merged = [{'content': 'Both observed results are retained.', 'fact_ids': [fact['id'] for fact in group[index:index + 2]],
                   'citation_ids': [fact['citation_ids'][0] for fact in group[index:index + 2]]} for index in range(0, len(group), 2)]
        reduced, invalid = _reduce_facts(merged, group, pool, parts, max_facts=12)
        assert invalid == 0
        preserved.update(source_id for fact in reduced for source_id in fact['source_fact_ids'])
    assert preserved == {fact['id'] for fact in facts}


def test_two_maximum_length_quotes_fit_each_reduction_output_entry():
    from app.providers.harness import _citation_pool, _context_groups, _facts, _reduce_facts, SourcePart
    parts, facts = {}, []
    for index in range(24):
        source = f'Result {index:02d} ' + 'x' * 3990
        assert len(source) == 4000
        part = SourcePart(f'c{index}:0:4000', f'c{index}', 0, 4000, index + 1, 'Results', source)
        parts[part.part_id] = part
        verified, _ = _facts([{'content': f'Result {index}.', 'citations': [{'part_id': part.part_id, 'chunk_id': part.chunk_id, 'source_text': source}]}], parts)
        facts.extend(verified)
    pool = _citation_pool(facts, parts)
    for group in _context_groups(facts, pool):
        max_facts = max(1, min(12, (len(group) + 1) // 2))
        merged = [{'content': 'The paired observations remain supported.', 'fact_ids': [fact['id'] for fact in group[index:index + 2]],
                   'citation_ids': [fact['citation_ids'][0] for fact in group[index:index + 2]]} for index in range(0, len(group), 2)]
        reduced, invalid = _reduce_facts(merged, group, pool, parts, max_facts=max_facts)
        assert invalid == 0 and len(reduced) <= max_facts


def test_many_short_facts_that_fit_synthesis_do_not_need_reduction(tmp_path):
    from app.providers.harness import analyze_full_paper
    db = database(tmp_path)
    calls = []
    def respond(request):
        payload = json.loads(json.loads(request.content)['messages'][-1]['content'])
        calls.append(payload)
        if 'chunks' in payload:
            part = payload['chunks'][0]
            answer = {'facts': [{'content': f'Scientific clause {index}.', 'citations': [{'part_id': part['part_id'], 'chunk_id': part['chunk_id'], 'source_text': part['content']}]} for index in range(37)]}
        else:
            assert payload.get('stage') != 'reduce'
            answer = {'method': {'content': 'A supported method.', 'citation_ids': payload['facts'][0]['citation_ids']}}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAICompatibleProvider(api_key='secret', base_url='https://model.example', transport=httpx.MockTransport(respond))
    result = analyze_full_paper(db, provider, [PaperChunk(id='p', paper_id='a', content='Scientifically meaningful evidence for multiple reported clauses.')])
    assert result.report['fact_coverage'] == {'total': 37, 'retained': 37, 'complete': True}
    assert len(calls) == 2
