from copy import deepcopy

import pytest

from app.db import Database
from app.models import PaperChunk
from app.providers.base import ProviderError
from app.providers.harness import AnalysisCancelled, analyze_full_paper


class ScienceProvider:
    name = 'ScienceTestProvider'
    model = 'science-model'
    reasoning_effort = 'high'

    def __init__(self, review=None):
        self.review = review
        self.calls = []
        self.last_usage = {}
        self.response_model = self.model

    def complete_json(self, system, payload, **options):
        self.calls.append(deepcopy(payload))
        self.last_usage = {}
        if payload.get('stage') == 'review_card_science':
            result = self.review(payload) if self.review else self.correct(payload)
        elif 'chunks' in payload:
            sid = next(part['source_id'] for part in payload['chunks'] if part['content'].startswith('Adaptive-RAG:'))
            result = {'facts': [{'content': 'FLAN-T5-XL单跳F1不超过单步方法。', 'source_ids': [sid]}]}
        else:
            refs = payload['facts'][0]['citation_ids']
            entry = lambda content: {'content': content, 'citation_ids': refs}
            result = {'card': {'one_sentence_summary': entry('方法根据问题复杂度选择检索策略。'),
                'main_results': entry('FLAN-T5-XL的单跳F1未超过单步基线。'),
                'tldr': [entry('按复杂度路由。'), entry('标签自动生成。'), entry('单跳F1未超过单步基线。')]}}
        self.last_usage = {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120}
        return result

    @staticmethod
    def correct(payload):
        refs = [source['id'] for source in payload['sources']]
        items = [{'field': item['field'], 'decision': 'supported'} for item in payload['items']]
        for item in items:
            if item['field'] in ['tldr[2]', 'main_results']:
                item.update(decision='corrected', value={'content': '在FLAN-T5-XL的表2条件下，单跳F1未超过单步基线。', 'citation_ids': refs})
        return {'items': items}


def setup(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'science.db').as_posix()}")
    db.migrate()
    chunks = [PaperChunk(id='header', paper_id='paper', page=7, section='Results', content='Table 2. FLAN-T5-XL. SQuAD / NQ / TriviaQA F1.'),
        PaperChunk(id='baseline', paper_id='paper', page=7, section='Results', content='Single-step Approach: 39.30 / 47.30 / 62.40.'),
        PaperChunk(id='ours', paper_id='paper', page=7, section='Results', content='Adaptive-RAG: 38.30 / 47.30 / 60.70.')]
    return db, chunks


def test_real_missing_scope_and_baseline_are_corrected_without_repeat_extraction(tmp_path):
    db, chunks = setup(tmp_path)
    provider = ScienceProvider()
    first = analyze_full_paper(db, provider, chunks)
    assert first.analysis.card['tldr'][2].content.startswith('在FLAN-T5-XL')
    assert {cite.chunk.id for cite in first.analysis.card['tldr'][2].citations} == {'header', 'baseline', 'ours'}
    assert first.report['science_review']['corrected_items'] == 2
    assert first.report['usage']['remote_calls'] == 3
    assert not first.report['partial']
    calls = len(provider.calls)
    repeated = analyze_full_paper(db, provider, chunks)
    assert len(provider.calls) == calls
    assert repeated.report['usage']['remote_calls'] == 0
    assert repeated.report['usage']['cache_hits'] == 3
    assert repeated.analysis.card == first.analysis.card


def test_semantic_rejection_removes_tldr_and_counts_partial(tmp_path):
    db, chunks = setup(tmp_path)
    def review(payload):
        return {'items': [{'field': item['field'], 'decision': 'unsupported' if item['field'] == 'tldr[2]' else 'supported'} for item in payload['items']]}
    result = analyze_full_paper(db, ScienceProvider(review), chunks)
    assert result.report['partial']
    assert result.analysis.card['tldr'] == []
    assert result.analysis.card['main_results']
    assert result.report['invalid_entries'] == 3
    assert any(item['reason'] == 'science_support' for item in result.report['rejections'])


def test_science_service_outage_preserves_usable_card_and_reports_usage(tmp_path):
    db, chunks = setup(tmp_path)
    def review(payload):
        raise ProviderError('Safe failure', code='authentication')
    result = analyze_full_paper(db, ScienceProvider(review), chunks)
    assert result.analysis.card['tldr']
    assert result.report['partial']
    assert result.report['science_review']['pending_items'] == 5
    assert result.report['usage']['remote_calls'] == 3
    assert result.report['usage']['unknown_usage_calls'] == 1


def test_science_transient_retries_use_existing_bounds_and_keep_pending(tmp_path, monkeypatch):
    db, chunks = setup(tmp_path)
    monkeypatch.setattr('app.providers.harness.time.sleep', lambda _: None)
    def review(payload):
        raise ProviderError('Safe failure', code='upstream_error', retryable=True, retry_after=0)
    result = analyze_full_paper(db, ScienceProvider(review), chunks)
    assert result.report['partial']
    assert result.report['usage']['remote_calls'] == 5
    assert result.report['usage']['unknown_usage_calls'] == 3
    assert len([item for item in result.report['recoveries'] if item['kind'] == 'transport_retry']) == 2


def test_cancellation_after_science_response_never_continues_network(tmp_path):
    db, chunks = setup(tmp_path)
    provider = ScienceProvider()
    with pytest.raises(AnalysisCancelled):
        analyze_full_paper(db, provider, chunks, cancelled=lambda: len(provider.calls) == 3)
    assert len(provider.calls) == 3


def test_all_scientific_entries_rejected_publish_diagnostics_before_failure(tmp_path):
    db, chunks = setup(tmp_path)
    reports = []
    def review(payload):
        return {'items': [{'field': item['field'], 'decision': 'unsupported'} for item in payload['items']]}
    with pytest.raises(ProviderError) as error:
        analyze_full_paper(db, ScienceProvider(review), chunks,
            progress=lambda phase, done, total, report: reports.append(deepcopy(report)))
    assert error.value.code == 'science_support' and not error.value.retryable
    assert reports[-1]['science_review']['no_supported_card']
    assert reports[-1]['science_review']['rejected_items'] == 5
    assert reports[-1]['usage']['remote_calls'] == 3
    assert len(reports[-1]['rejections']) == 5


def test_unresolved_science_decision_replays_without_paid_resampling(tmp_path):
    db, chunks = setup(tmp_path)
    def review(payload):
        return {'items': [{'field': item['field'], 'decision': 'unsupported' if item['field'] == 'tldr[2]' else 'supported'} for item in payload['items']]}
    provider = ScienceProvider(review)
    first = analyze_full_paper(db, provider, chunks)
    called = len(provider.calls)
    repeated = analyze_full_paper(db, provider, chunks)
    assert first.report['partial'] and repeated.report['partial']
    assert len(provider.calls) == called
    assert repeated.report['usage']['remote_calls'] == 0
    assert repeated.report['usage']['cache_hits'] == 3
    assert repeated.report['science_review']['rejected_items'] == 1
