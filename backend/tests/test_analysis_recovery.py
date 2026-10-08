from __future__ import annotations

from copy import deepcopy
import json
import time

import pytest

from app.db import Database
from app.models import PaperChunk
from app.providers.base import ProviderError
from app.providers.harness import AnalysisCancelled, analyze_full_paper


class ScriptedProvider:
    name = 'RecoveryTestProvider'
    model = 'recovery-model'
    reasoning_effort = 'high'

    def __init__(self, respond):
        self.respond = respond
        self.calls = []
        self.last_usage = {}
        self.response_model = self.model

    def complete_json(self, system, payload, **options):
        self.calls.append(deepcopy(payload))
        self.last_usage = {}
        answer = ({'items': [{'field': item['field'], 'decision': 'supported'} for item in payload['items']]}
                  if payload.get('stage') == 'review_card_science' else self.respond(payload))
        self.last_usage = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
        return answer


def setup(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'recovery.db').as_posix()}")
    database.migrate()
    chunks = [PaperChunk(id='source', paper_id='paper', page=7, section='Results',
        content='The method achieves 71 percent, but fails on contradictory evidence.',
        bbox_json='[10,20,100,60]', page_width=612, page_height=792)]
    return database, chunks


def normal(payload):
    if 'chunks' in payload:
        return {'facts': [{'content': 'A measured result with a negative condition.',
            'source_ids': [payload['chunks'][0]['source_id']]}]}
    return {'method': {'content': 'Keep this accepted entry.', 'citation_ids': payload['facts'][0]['citation_ids']}}


def transient():
    error = ProviderError('Temporary service failure', 503)
    error.retryable, error.code, error.retry_after = True, 'upstream_error', 0
    return error


def test_transient_failure_retries_only_current_stage_and_counts_unknown_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)
    db, chunks = setup(tmp_path)
    failed = False
    def respond(payload):
        nonlocal failed
        if not failed:
            failed = True
            raise transient()
        return normal(payload)
    provider = ScriptedProvider(respond)
    result = analyze_full_paper(db, provider, chunks)
    assert len(provider.calls) == 3
    assert provider.calls[0] == provider.calls[1]
    assert result.report['usage']['remote_calls'] == 3
    assert result.report['usage']['unknown_usage_calls'] == 1
    assert result.report['usage']['input_tokens'] is None
    assert result.report['recoveries'][0]['code'] == 'upstream_error'
    assert not result.report['partial']
    again = analyze_full_paper(db, provider, chunks)
    assert len(provider.calls) == 3
    assert again.report['usage']['remote_calls'] == 0


def test_persistent_transient_failure_is_bounded_and_publishes_all_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)
    db, chunks = setup(tmp_path)
    provider = ScriptedProvider(lambda payload: (_ for _ in ()).throw(transient()))
    reports = []
    with pytest.raises(ProviderError):
        analyze_full_paper(db, provider, chunks, progress=lambda *args: reports.append(deepcopy(args[-1])))
    assert len(provider.calls) == 3
    assert reports[-1]['usage']['remote_calls'] == 3
    assert reports[-1]['usage']['unknown_usage_calls'] == 3
    assert reports[-1]['coverage']['processed_windows'] == 0


def test_nontransient_error_is_not_retried(tmp_path):
    db, chunks = setup(tmp_path)
    provider = ScriptedProvider(lambda payload: (_ for _ in ()).throw(ProviderError('Authentication failed', 401)))
    with pytest.raises(ProviderError):
        analyze_full_paper(db, provider, chunks)
    assert len(provider.calls) == 1


def test_terminal_failure_records_safe_stage_diagnostics_even_without_retry(tmp_path):
    db, chunks = setup(tmp_path)
    failure = ProviderError('Service refused the request', code='upstream_error')
    failure.diagnostics = {'http_status': 200, 'upstream_code': 'unknown', 'upstream_type': 'missing'}
    provider = ScriptedProvider(lambda payload: (_ for _ in ()).throw(failure))
    reports = []
    with pytest.raises(ProviderError):
        analyze_full_paper(db, provider, chunks, progress=lambda *args: reports.append(deepcopy(args[-1])))
    assert reports[-1]['failures'][-1] == {'phase': 'extract', 'operation': 'paper_extract',
        'attempt': 1, 'code': 'upstream_error', 'retryable': False, 'diagnostics': failure.diagnostics}


def test_cancellation_during_recovery_prevents_another_paid_call(tmp_path, monkeypatch):
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)
    db, chunks = setup(tmp_path)
    provider = ScriptedProvider(lambda payload: (_ for _ in ()).throw(transient()))
    cancel = False
    def progress(*args):
        nonlocal cancel
        cancel = bool(args[-1].get('recoveries'))
    with pytest.raises(AnalysisCancelled):
        analyze_full_paper(db, provider, chunks, progress=progress, cancelled=lambda: cancel)
    assert len(provider.calls) == 1


def test_missing_reduction_lineage_gets_one_group_correction_with_short_ids(tmp_path, monkeypatch):
    import app.providers.harness as harness
    monkeypatch.setattr(harness, 'REDUCE_CHARS', 2500)
    db, chunks = setup(tmp_path)
    bad = False
    def respond(payload):
        nonlocal bad
        if 'chunks' in payload:
            return {'facts': [{'content': f'Condition {i}: ' + 'x' * 1000,
                'source_ids': [payload['chunks'][0]['source_id']]} for i in range(3)]}
        if payload.get('stage') in {'reduce', 'repair_reduce'}:
            if payload['stage'] == 'repair_reduce':
                assert all(fact['id'].startswith('F0') for fact in payload['facts'])
                assert payload['validation_errors']
            refs = list(dict.fromkeys(ref for fact in payload['facts'] for ref in fact['citation_ids']))
            if not bad:
                bad = True
                refs = []
            return {'facts': [{'content': 'The positive and negative conditions remain represented.',
                'fact_ids': [fact['id'] for fact in payload['facts']], 'citation_ids': refs}]}
        return normal(payload)
    provider = ScriptedProvider(respond)
    result = analyze_full_paper(db, provider, chunks)
    assert sum(call.get('stage') == 'repair_reduce' for call in provider.calls) == 1
    assert result.report['fact_coverage'] == {'total': 3, 'retained': 3, 'complete': True}
    assert not result.report['partial']
    assert any(item.get('resolved') for item in result.report['rejections'])
    assert result.analysis.citations[0].chunk.page == 7
    count = len(provider.calls)
    again = analyze_full_paper(db, provider, chunks)
    assert len(provider.calls) == count
    assert again.report['usage']['remote_calls'] == 0


def test_targeted_card_repairs_preserve_accepted_entries_and_replay_without_calls(tmp_path):
    db, chunks = setup(tmp_path)
    def respond(payload):
        if 'chunks' in payload:
            return normal(payload)
        ref = payload['facts'][0]['citation_ids'][0]
        if payload.get('stage') == 'repair_card':
            assert {target['field'] for target in payload['targets']} == {'main_results', 'section_summaries[0]'}
            return {'repairs': [
                {'field': 'method', 'value': {'content': 'Do not overwrite the accepted entry.', 'citation_ids': [ref]}},
                {'field': 'main_results', 'value': {'content': '71 percent, with a contradictory-evidence failure.', 'citation_ids': [ref]}},
                {'field': 'section_summaries[0]', 'value': {'content': 'A qualified result.', 'section': 'Results', 'citation_ids': [ref]}}]}
        return {**normal(payload), 'main_results': 'Wrong field type',
            'section_summaries': [{'content': 'A qualified result.', 'section': 'Wrong section', 'citation_ids': [ref]}]}
    provider = ScriptedProvider(respond)
    result = analyze_full_paper(db, provider, chunks)
    assert result.analysis.method == 'Keep this accepted entry.'
    assert result.analysis.findings.startswith('71 percent')
    assert result.report['invalid_entries'] == 0 and not result.report['partial']
    assert result.report['repaired_entries'] == 2
    assert all(item.get('resolved') for item in result.report['rejections'])
    assert result.analysis.citations[0].chunk.bbox_json == '[10,20,100,60]'
    count = len(provider.calls)
    again = analyze_full_paper(db, provider, chunks)
    assert len(provider.calls) == count
    assert again.report['usage']['remote_calls'] == 0
    assert again.analysis.findings == result.analysis.findings


def test_array_valued_singular_field_gets_explicit_object_contract(tmp_path):
    """CRUD/RECALL returned arrays again because target feedback omitted the shape."""
    db, chunks = setup(tmp_path)
    def respond(payload):
        if 'chunks' in payload:
            return normal(payload)
        ref = payload['facts'][0]['citation_ids'][0]
        if payload.get('stage') == 'repair_card':
            target = payload['targets'][0]
            schema = target['value_schema']
            assert schema['type'] == 'object'
            assert set(schema['required']) == {'content', 'citation_ids'}
            assert schema['properties']['content']['maxLength'] == 8000
            assert schema['properties']['citation_ids']['maxItems'] == 10
            assert target['rejected_value_complete'] is True
            assert 'final condition' in target['rejected_value']
            return {'repairs': [{'field': 'main_results', 'value': {
                'content': '71 percent, but fails on contradictory evidence.', 'citation_ids': [ref]}}]}
        schema = payload['card_schema']['properties']
        assert schema['main_results']['anyOf'][0]['type'] == 'object'
        assert schema['claims']['type'] == 'array'
        return {**normal(payload), 'main_results': [
            {'content': 'x' * 1250, 'citation_ids': [ref]},
            {'content': 'final condition', 'citation_ids': [ref]}]}
    result = analyze_full_paper(db, ScriptedProvider(respond), chunks)
    assert result.analysis.method == 'Keep this accepted entry.'
    assert result.analysis.findings.startswith('71 percent')
    assert result.report['repaired_entries'] == 1
    assert not result.report['partial']


def test_repair_contract_distinguishes_whole_lists_and_indexed_section_slots():
    from app.providers.card_recovery import repair_targets
    targets = repair_targets({'tldr': 'bad', 'section_summaries': [{'content': 'x'}]}, [
        {'field': 'tldr', 'reason': 'invalid_list'},
        {'field': 'section_summaries[0]', 'reason': 'section_mismatch'}])
    tldr, section = targets
    assert tldr['value_schema']['type'] == 'array'
    assert (tldr['value_schema']['minItems'], tldr['value_schema']['maxItems']) == (3, 5)
    assert section['value_schema']['type'] == 'object'
    assert 'section' in section['value_schema']['required']


def test_repair_feedback_has_an_aggregate_text_budget():
    from app.providers.card_recovery import repair_targets
    entries = [{'content': 'x' * 16000} for _ in range(16)]
    targets = repair_targets({'claims': entries}, [
        {'field': f'claims[{i}]', 'reason': 'invalid_content'} for i in range(16)])
    assert sum(len(target['rejected_value']) for target in targets) <= 24000
    assert any(not target['rejected_value_complete'] for target in targets)


@pytest.mark.parametrize('bad_patch', ['null', 'foreign', 'duplicate'])
def test_repair_cannot_hide_missing_evidence_or_loop(tmp_path, bad_patch):
    db, chunks = setup(tmp_path)
    def respond(payload):
        if 'chunks' in payload:
            return normal(payload)
        if payload.get('stage') == 'repair_card':
            value = None if bad_patch == 'null' else {'content': 'An unverified result.',
                'citation_ids': ['E99999' if bad_patch == 'foreign' else payload['facts'][0]['citation_ids'][0]]}
            repairs = [{'field': 'main_results', 'value': value}]
            return {'repairs': repairs * (2 if bad_patch == 'duplicate' else 1)}
        return {**normal(payload), 'main_results': 'Wrong field type'}
    provider = ScriptedProvider(respond)
    result = analyze_full_paper(db, provider, chunks)
    assert result.report['partial'] and result.report['invalid_entries'] == 1
    assert result.analysis.findings is None
    assert sum(call.get('stage') == 'repair_card' for call in provider.calls) == 1
    assert not any(item.get('resolved') for item in result.report['rejections'])


def test_global_recovery_budget_caps_retries_across_windows(tmp_path, monkeypatch):
    import app.providers.harness as harness
    monkeypatch.setattr(harness, 'MAX_RECOVERY_CALLS', 2)
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)
    db, _ = setup(tmp_path)
    chunks = [PaperChunk(id=f'source-{i}', paper_id='paper', page=i + 1,
        content=f'Observation {i}. ' + 'x' * 19985) for i in range(3)]
    failed = set()
    def respond(payload):
        index = payload['window_index']
        if index not in failed:
            failed.add(index)
            raise transient()
        return normal(payload)
    reports = []
    provider = ScriptedProvider(respond)
    with pytest.raises(ProviderError):
        analyze_full_paper(db, provider, chunks, progress=lambda *args: reports.append(deepcopy(args[-1])))
    assert len(provider.calls) == 5
    assert len(reports[-1]['recoveries']) == 2
    assert reports[-1]['coverage']['processed_windows'] == 2


def test_optional_card_repair_failure_keeps_verified_partial_card(tmp_path, monkeypatch):
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)
    db, chunks = setup(tmp_path)
    def respond(payload):
        if payload.get('stage') == 'repair_card':
            raise transient()
        if 'chunks' in payload:
            return normal(payload)
        return {**normal(payload), 'main_results': 'Wrong type'}
    provider = ScriptedProvider(respond)
    result = analyze_full_paper(db, provider, chunks)
    assert result.report['partial']
    assert result.analysis.method == 'Keep this accepted entry.'
    assert result.analysis.findings is None
    assert result.report['usage']['unknown_usage_calls'] == 3
    assert result.report['recoveries'][-1]['kind'] == 'card_correction_failed'


def test_card_repair_cannot_promote_scientific_fact_to_uncited_result(tmp_path):
    db, chunks = setup(tmp_path)
    def respond(payload):
        if 'chunks' in payload:
            return normal(payload)
        if payload.get('stage') == 'repair_card':
            return {'repairs': [{'field': 'main_results', 'value': {'content': 'Claim with no evidence.', 'citation_ids': []}}]}
        return {**normal(payload), 'main_results': 'Wrong type'}
    provider = ScriptedProvider(respond)
    result = analyze_full_paper(db, provider, chunks)
    assert result.report['partial'] and result.report['repaired_entries'] == 0
    assert result.analysis.findings is None


def test_tldr_slot_repair_preserves_three_already_accepted_lines(tmp_path):
    db, chunks = setup(tmp_path)
    def respond(payload):
        if 'chunks' in payload:
            return normal(payload)
        ref = payload['facts'][0]['citation_ids'][0]
        if payload.get('stage') == 'repair_card':
            assert [target['field'] for target in payload['targets']] == ['tldr[3]']
            return {'repairs': [
                {'field': 'tldr', 'value': [{'content': 'Unrequested replacement.', 'citation_ids': [ref]}] * 3},
                {'field': 'tldr[3]', 'value': {'content': 'Repaired fourth line.', 'citation_ids': [ref]}}]}
        return {**normal(payload), 'tldr': [
            {'content': f'Accepted line {i}.', 'citation_ids': [ref]} for i in range(3)] + ['Invalid line']}
    result = analyze_full_paper(db, ScriptedProvider(respond), chunks)
    assert [item.content for item in result.analysis.card['tldr']] == [
        'Accepted line 0.', 'Accepted line 1.', 'Accepted line 2.', 'Repaired fourth line.']
    assert not result.report['partial']


def test_noncompressing_corrections_are_all_evicted_before_explicit_retry(tmp_path, monkeypatch):
    from sqlalchemy import select
    from app.models import ModelCallCache
    import app.providers.harness as harness
    monkeypatch.setattr(harness, 'REDUCE_CHARS', 1500)
    db, chunks = setup(tmp_path)
    def respond(payload):
        if 'chunks' in payload:
            return {'facts': [{'content': f'Original condition {i}: ' + 'x' * 1000,
                'source_ids': [payload['chunks'][0]['source_id']]} for i in range(3)]}
        return {'facts': [{'content': 'Expanded instead of compressed: ' + 'x' * 3700,
            'fact_ids': [fact['id'] for fact in payload['facts']],
            'citation_ids': payload['facts'][0]['citation_ids'] if payload['stage'] == 'repair_reduce' else []}]}
    provider = ScriptedProvider(respond)
    with pytest.raises(ProviderError, match='未缩减'):
        analyze_full_paper(db, provider, chunks)
    with db.sessions() as session:
        assert not session.scalars(select(ModelCallCache).where(ModelCallCache.operation == 'paper_repair_reduce_v1')).all()


def test_partial_failed_usage_remains_unknown_without_erasing_known_input(tmp_path, monkeypatch):
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)
    db, chunks = setup(tmp_path)
    failed = False
    def respond(payload):
        nonlocal failed
        if not failed:
            failed = True
            provider.last_usage = {'input_tokens': 12}
            raise transient()
        return normal(payload)
    provider = ScriptedProvider(respond)
    result = analyze_full_paper(db, provider, chunks)
    assert result.report['usage']['input_tokens'] == 32
    assert result.report['usage']['output_tokens'] is None
    assert result.report['usage']['unknown_usage_calls'] == 1


def test_tldr_repair_cannot_discard_five_accepted_lines_at_upper_bound(tmp_path):
    db, chunks = setup(tmp_path)
    def respond(payload):
        if 'chunks' in payload:
            return normal(payload)
        ref = payload['facts'][0]['citation_ids'][0]
        if payload.get('stage') == 'repair_card':
            return {'repairs': [{'field': 'tldr[5]', 'value': {'content': 'Sixth line.', 'citation_ids': [ref]}}]}
        return {**normal(payload), 'tldr': [
            {'content': f'Accepted line {i}.', 'citation_ids': [ref]} for i in range(5)] + ['Invalid line']}
    result = analyze_full_paper(db, ScriptedProvider(respond), chunks)
    assert [item.content for item in result.analysis.card['tldr']] == [f'Accepted line {i}.' for i in range(5)]
    assert result.report['partial'] and result.report['invalid_entries'] == 1
    assert result.report['repaired_entries'] == 0
