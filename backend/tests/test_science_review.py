from copy import deepcopy
import importlib

import pytest

from app.models import PaperChunk
from app.providers.base import AnalysisResult, CardEntry, VerifiedCitation
from app.providers.harness import pack_windows, source_passages
from app.providers.harness import _card
from app.providers.base import ProviderError


@pytest.fixture
def review():
    return importlib.import_module('app.providers.science_review')


def example():
    chunks = [
        PaperChunk(id='header', paper_id='paper', page=7, section='Results', content='Table 2. FLAN-T5-XL. SQuAD / NQ / TriviaQA F1.'),
        PaperChunk(id='baseline', paper_id='paper', page=7, section='Results', content='Single-step Approach: 39.30 / 47.30 / 62.40.'),
        PaperChunk(id='ours', paper_id='paper', page=7, section='Results', content='Adaptive-RAG: 38.30 / 47.30 / 60.70.'),
        PaperChunk(id='appendix', paper_id='paper', page=15, section='Appendix', content='GPT-3.5: ours 34.40 / 52.00 / 73.80; single-step 33.80 / 46.80 / 66.50.'),
    ]
    parts = {p.part_id: p for w in pack_windows(chunks) for p in source_passages(w).values()}
    def entry(content, index=2):
        chunk = chunks[index]
        return CardEntry(content, [VerifiedCitation(chunk, chunk.content, content, 'llm_summary')], chunk.section)
    card = AnalysisResult()
    card.card = {'one_sentence_summary': entry('按问题复杂度选择检索策略。'),
        'main_results': entry('FLAN-T5-XL单跳F1未超过单步方法。'),
        'tldr': [entry('路由无检索、单步和多步。'), entry('复杂度标签自动生成。'),
                 entry('单跳F1未超过单步基线。')],
        'claims': [entry('保留这条未安排复核的内容。')],
        'section_summaries': [entry('GPT-3.5的F1结果需要单独比较。', 3)]}
    return card, parts


def test_review_includes_real_model_condition_and_missing_baseline_row(review):
    card, parts = example()
    batches, report = review.prepare_reviews(card, parts)
    assert report['scheduled_items'] >= 5
    payload = batches[0].payload
    assert payload['stage'] == 'review_card_science'
    assert any(item['field'] == 'tldr[2]' for item in payload['items'])
    sources = [source['source_text'] for source in payload['sources']]
    assert any('Table 2. FLAN-T5-XL' in source for source in sources)
    assert any('Single-step Approach: 39.30' in source for source in sources)
    assert all(source in [part.content for part in parts.values()] for source in sources)


def test_review_includes_cross_page_continuation_without_treating_it_as_old_evidence(review):
    first = PaperChunk(id='start', paper_id='paper', page=9, section='Analysis',
        content='Increasing the support weight improves citation precision.')
    continuation = PaperChunk(id='continuation', paper_id='paper', page=10, section='Analysis',
        content='A larger weight results in lower MAUVE scores.')
    parts = {p.part_id: p for w in pack_windows([first, continuation])
             for p in source_passages(w).values()}
    entry = CardEntry('引用精度提高，但MAUVE下降。',
        [VerifiedCitation(first, first.content, '', 'llm_summary')], 'Analysis')
    batch = review.prepare_reviews(AnalysisResult(card={'ablation_findings': [entry]}), parts)[0][0]
    refs = batch.payload['items'][0]['citation_ids']
    assert [batch.sources[sid]['source_text'] for sid in refs] == [first.content]
    assert any(source['source_text'] == continuation.content and source['id'] not in refs
               for source in batch.payload['sources'])


def test_review_budget_keeps_cited_sources_and_reports_omitted_context(review):
    card, parts = example()
    huge = PaperChunk(id='unrelated', paper_id='paper', page=7, section='Results', content='x' * 30000)
    for window in pack_windows([huge]):
        parts.update({p.part_id: p for p in source_passages(window).values()})
    batches, report = review.prepare_reviews(card, parts, max_payload_chars=5000)
    assert all(len(review.encoded(batch.payload)) <= 5000 for batch in batches)
    assert report['context_partial']
    for batch in batches:
        available = {source['id'] for source in batch.payload['sources']}
        assert all(set(item['citation_ids']) <= available for item in batch.payload['items'])


def test_review_is_bounded_and_deferred_slots_are_visible(review):
    card, parts = example()
    original = card.card['claims'][0]
    card.card['ablation_findings'] = [CardEntry(f'条件{i}下F1超过基线。', original.citations) for i in range(40)]
    batches, report = review.prepare_reviews(card, parts, max_batches=2, max_items=3)
    assert len(batches) == 2
    assert sum(len(batch.payload['items']) for batch in batches) == 6
    assert report['deferred_items'] >= 40


def test_default_review_covers_a_realistic_thirty_four_risky_slots(review):
    card, parts = example()
    original = card.card['claims'][0]
    card.card = {'claims': [CardEntry(f'Condition {i}: F1 38.30.', original.citations)
                            for i in range(34)]}
    batches, report = review.prepare_reviews(card, parts)
    assert report['scheduled_items'] == 34
    assert report['deferred_items'] == 0
    assert len(batches) == 3


def test_default_review_caps_very_large_cards_and_discloses_all_deferred_slots(review):
    card, parts = example()
    original = card.card['claims'][0]
    card.card = {'claims': [CardEntry(f'Condition {i}: F1 38.30.', original.citations)
                            for i in range(80)]}
    batches, report = review.prepare_reviews(card, parts)
    assert len(batches) == 4
    assert report['scheduled_items'] == 48
    assert report['deferred_items'] == 32


def test_late_sample_restriction_and_uncertainty_are_prioritized_over_routine_numbers(review):
    card, parts = example()
    restricted = PaperChunk(id='restricted', paper_id='paper', page=8, section='Confidence',
        content='For QA-A we only consider samples answered correctly without contexts but wrongly with edited contexts.')
    for window in pack_windows([restricted]):
        parts.update({p.part_id: p for p in source_passages(window).values()})
    original = card.card['claims'][0]
    card.card['section_summaries'] = [CardEntry(f'F1数值{i}。', original.citations) for i in range(40)]
    card.card['section_summaries'].append(CardEntry('ChatGLM2的QA置信度下降。',
        [VerifiedCitation(restricted, restricted.content, 'ChatGLM2的QA置信度下降。', 'llm_summary')], restricted.section))
    batches, _ = review.prepare_reviews(card, parts, max_items=3)
    scheduled = [item['field'] for batch in batches for item in batch.payload['items']]
    assert 'section_summaries[40]' in scheduled


@pytest.mark.parametrize('content,source', [
    ('The method outperforms its baseline.', 'An observed comparison.'),
    ('The method is significantly better.', 'An observed comparison.'),
    ('All interventions improve robustness.', 'An observed comparison.'),
    ('错误由实体表面连贯性导致。', 'A possible explanation is the consistency of the entity edits.'),
    ('作者观察到置信度下降。', 'We only consider correctly answered no-context samples.'),
    ('这是错误产生的原因。', 'We hypothesize that incoherent edits affect trust.'),
])
def test_english_overclaims_and_source_qualifiers_enter_review(review, content, source):
    chunk = PaperChunk(id='scope', paper_id='paper', page=5, section='Analysis', content=source)
    parts = {p.part_id: p for w in pack_windows([chunk]) for p in source_passages(w).values()}
    card = AnalysisResult()
    card.card = {'claims': [CardEntry(content, [VerifiedCitation(chunk, source, content, 'llm_summary')], chunk.section)]}
    batches, report = review.prepare_reviews(card, parts)
    assert report['scheduled_items'] == 1
    assert batches[0].payload['items'][0]['field'] == 'claims[0]'


def responses(batch, replacements=None):
    replacements = replacements or {}
    return {'items': [replacements.get(item['field'], {'field': item['field'], 'decision': 'supported'})
                      for item in batch.payload['items']]}


def test_corrected_tldr_keeps_condition_and_both_rows_without_touching_other_slots(review):
    card, parts = example()
    batches, _ = review.prepare_reviews(card, parts)
    batch = batches[0]
    raw = review.serialize_card(card, parts)
    original = deepcopy(raw)
    ids = [source['id'] for source in batch.payload['sources'] if any(term in source['source_text']
            for term in ['Table 2. FLAN', 'Single-step Approach:', 'Adaptive-RAG:'])]
    fixed = {'field': 'tldr[2]', 'decision': 'corrected', 'value': {
        'content': '在FLAN-T5-XL的表2设置下，单跳F1未超过单步基线。', 'citation_ids': ids}}
    patched, report = review.apply_review(raw, batch, responses(batch, {'tldr[2]': fixed}), lambda field, value, sources: True)
    assert patched['card']['tldr'][2]['content'].startswith('在FLAN-T5-XL')
    assert len(patched['card']['tldr'][2]['citations']) == 3
    assert patched['card']['claims'] == original['card']['claims']
    assert patched['card']['tldr'][:2] == original['card']['tldr'][:2]
    assert report['corrected_fields'] == ['tldr[2]']
    assert not report['rejected_fields']


@pytest.mark.parametrize('decision', ['missing', 'duplicate', 'foreign', 'empty', 'wrong_type', 'bad_section', 'validator_reject'])
def test_invalid_review_cannot_preserve_a_suspect_claim_or_edit_another_slot(review, decision):
    card, parts = example()
    batch = review.prepare_reviews(card, parts)[0][0]
    raw = review.serialize_card(card, parts)
    body = responses(batch)
    wanted = 'tldr[2]'
    if decision == 'missing':
        body['items'] = [item for item in body['items'] if item['field'] != wanted]
    elif decision == 'duplicate':
        body['items'].append({'field': wanted, 'decision': 'supported'})
    else:
        sid = batch.payload['sources'][0]['id']
        value = {'content': '在特定条件下比较结果。', 'citation_ids': [sid]}
        if decision == 'foreign': value['citation_ids'] = ['R99999']
        if decision == 'empty': value['content'] = ''
        if decision == 'wrong_type': value['citation_ids'] = sid
        target = wanted
        if decision == 'bad_section':
            target = 'section_summaries[0]'
            value['section'] = 'Invented section'
        body['items'] = [item if item['field'] != target else {'field': target, 'decision': 'corrected', 'value': value} for item in body['items']]
    body['items'].append({'field': 'claims[0]', 'decision': 'corrected', 'value': {'content': '不允许改写。', 'citation_ids': []}})
    patched, result = review.apply_review(raw, batch, body,
        lambda field, value, sources: decision != 'validator_reject')
    rejected = 'section_summaries[0]' if decision == 'bad_section' else wanted
    assert rejected in result['rejected_fields']
    if rejected == wanted: assert patched['card']['tldr'][2] is None
    assert patched['card']['claims'] == raw['card']['claims']


def test_reviewed_support_preserves_exact_content_quotes_and_order(review):
    card, parts = example()
    batches, _ = review.prepare_reviews(card, parts)
    raw = review.serialize_card(card, parts)
    for batch in batches:
        patched, result = review.apply_review(raw, batch, responses(batch), lambda *args: True)
        assert patched == raw
        assert result['supported_fields'] == [item['field'] for item in batch.payload['items']]


def test_review_distinguishes_exact_old_quote_from_supplemental_table(review):
    ours = 'Adaptive-RAG: 38.30.'
    table = 'Table 2. FLAN-T5-XL. Single-step: 39.30. ' + ours
    chunk = PaperChunk(id='table', paper_id='paper', page=7, section='Results', content=table)
    parts = {p.part_id: p for w in pack_windows([chunk]) for p in source_passages(w).values()}
    content = 'FLAN-T5-XL F1 does not exceed the single-step baseline.'
    def card(quote):
        return AnalysisResult(card={'main_results': CardEntry(content,
            [VerifiedCitation(chunk, quote, content, 'llm_summary')], chunk.section)})
    narrow = review.prepare_reviews(card(ours), parts)[0][0]
    complete = review.prepare_reviews(card(table), parts)[0][0]
    assert narrow.payload != complete.payload
    cited = narrow.payload['items'][0]['citation_ids']
    assert [narrow.sources[sid]['source_text'] for sid in cited] == [ours]
    assert any(source['source_text'] == table and source['id'] not in cited
               for source in narrow.payload['sources'])
    assert narrow.sources[cited[0]]['start'] == table.index(ours)
    assert narrow.sources[cited[0]]['end'] == len(table)
    # Full quotes reuse the existing source ID; don't spend tokens repeating it.
    assert len(complete.payload['sources']) == 1
    assert complete.payload['items'][0]['citation_ids'] == [complete.payload['sources'][0]['id']]


def test_repeated_narrow_quotes_share_one_stable_source_id(review):
    chunk = PaperChunk(id='table', paper_id='paper', page=7, section='Results',
        content='Table 2. FLAN-T5-XL. Ours: 38.30. Baseline: 39.30.')
    parts = {p.part_id: p for w in pack_windows([chunk]) for p in source_passages(w).values()}
    entry = CardEntry('FLAN-T5-XL F1 38.30.',
        [VerifiedCitation(chunk, 'Ours: 38.30.', '', 'llm_summary')], chunk.section)
    card = AnalysisResult(card={'main_results': entry, 'limitations': entry})
    first = review.prepare_reviews(card, parts)[0][0]
    second = review.prepare_reviews(card, parts)[0][0]
    assert first.payload == second.payload
    assert first.payload['items'][0]['citation_ids'] == first.payload['items'][1]['citation_ids']
    assert len(first.payload['sources']) == 2


def test_review_no_remote_stage_when_card_has_no_overview_or_scientific_risk(review):
    card, parts = example()
    card.card = {'method': card.card['claims'][0]}
    batches, report = review.prepare_reviews(card, parts)
    assert batches == []
    assert report['scheduled_items'] == 0


def local_validator(parts):
    facts = [{'citations': [{'part_id': p.part_id, 'chunk_id': p.chunk_id, 'source_text': p.content}
                           for p in parts.values()], 'citation_ids': []}]
    chunks = [PaperChunk(id=p.chunk_id, paper_id='paper', page=p.page, section=p.section,
                        content=p.content) for p in parts.values()]
    return lambda raw, sources: _card(raw, facts, parts, chunks, 'model', 'prompt')


def test_review_orchestration_revalidates_corrected_whole_card(review):
    card, parts = example()
    calls = []
    def call(payload):
        calls.append(payload)
        items = [{'field': item['field'], 'decision': 'supported'} for item in payload['items']]
        for reply in items:
            if reply['field'] == 'tldr[2]':
                refs = [source['id'] for source in payload['sources'] if source['page'] == 7]
                reply.update(decision='corrected', value={'content': 'FLAN-T5-XL表2的单跳F1未超过单步基线。', 'citation_ids': refs})
        return {'items': items}
    result, report = review.run_science_review(card, parts, call, local_validator(parts))
    assert result.card['tldr'][2].content.startswith('FLAN-T5-XL')
    assert report['corrected_items'] == 1
    assert report['checked_items'] == report['scheduled_items']
    assert not report['partial']
    assert 1 <= len(calls) <= 2


def test_review_outage_keeps_original_card_and_reports_all_pending(review):
    card, parts = example()
    attempts = []
    def call(payload):
        attempts.append(payload)
        raise ProviderError('Safe failure', code='upstream_error', retryable=True)
    result, report = review.run_science_review(card, parts, call, local_validator(parts))
    assert result is card
    assert len(attempts) == 1
    assert report['pending_items'] == report['scheduled_items']
    assert report['checked_items'] == 0
    assert report['partial']


def test_unsupported_tldr_cannot_survive_cardinality_validation(review):
    card, parts = example()
    def call(payload):
        return {'items': [{'field': item['field'], 'decision': 'unsupported' if item['field'] == 'tldr[2]' else 'supported'}
                          for item in payload['items']]}
    result, report = review.run_science_review(card, parts, call, local_validator(parts))
    assert result.card['tldr'] == []
    assert report['partial'] and report['rejected_items'] == 1
    assert report['card_invalid_entries'] == 2
    assert result.card['claims'][0].content == card.card['claims'][0].content


@pytest.mark.parametrize('malformed', [False, True])
def test_no_supported_summary_returns_empty_diagnostics_without_restoring_rejected_text(review, malformed):
    card, parts = example()
    card.card = {'one_sentence_summary': card.card['one_sentence_summary']}
    def call(payload):
        return {} if malformed else {'items': [{'field': 'one_sentence_summary', 'decision': 'unsupported'}]}
    result, report = review.run_science_review(card, parts, call, local_validator(parts))
    assert report['partial'] and report['no_supported_card']
    assert report['rejected_items'] == 1
    assert report['checked_items'] == (0 if malformed else 1)
    assert result.card['one_sentence_summary'] is None and result.citations == []


def test_only_tldr_losing_required_cardinality_returns_explicit_empty_result(review):
    card, parts = example()
    card.card = {'tldr': card.card['tldr']}
    def call(payload):
        return {'items': [{'field': item['field'], 'decision': 'unsupported' if item['field'] == 'tldr[2]' else 'supported'}
                          for item in payload['items']]}
    result, report = review.run_science_review(card, parts, call, local_validator(parts))
    assert result.card['tldr'] == [] and result.citations == []
    assert report['partial'] and report['no_supported_card']
    assert report['card_invalid_entries'] == 2
