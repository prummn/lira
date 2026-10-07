"""Scope, provenance and citation contracts for the local-library assistant."""
import json
import pytest


def test_librarian_requires_explicit_remote_configuration(client):
    response = client.post('/api/intelligence/ask', json={'question': '比较我的论文'})
    assert response.status_code == 503
    assert '模型' in response.json()['detail']


def test_librarian_rejects_empty_question(client):
    assert client.post('/api/intelligence/ask', json={'question': '  '}).status_code == 422


def original_source(pid='a', kind='paper'):
    from app.services.librarian import Source
    return Source('source-' + pid, pid, 'Paper ' + pid,
                  'The retrieval benchmark evaluated noise robustness on real passages.', kind,
                  page=17 if kind == 'paper' else None, chunk_id='chunk-' + pid if kind == 'paper' else None)


def test_quote_id_resolves_exact_bounded_pdf_excerpt_with_geometry():
    from app.services.librarian import Source, validate_answer
    content = ('The models per-\nform classification without redundant informa-\ntion. ' * 100)[:6000]
    source = Source('chunk:a', 'a', 'Paper A', content, 'paper', page=3,
        chunk_id='a', bbox=[60, 80, 280, 140], page_width=600, page_height=800)
    submitted = source.payload()
    items, rejected = validate_answer({'insufficient_evidence': False, 'items': [{
        'content': '原文介绍了分类机制。', 'kind': 'fact',
        'citations': [{'source_id': submitted['source_id'], 'quote_id': submitted.get('quote_id')}]}]}, [source])
    assert rejected == 0 and len(items) == 1
    citation = items[0].citations[0]
    assert citation.source_text == content
    assert citation.chunk_id == 'a' and citation.page == 3
    assert citation.bbox == (60, 80, 280, 140) and citation.page_width == 600 and citation.page_height == 800


def test_quote_id_is_stable_and_bound_to_source_and_exact_submitted_content():
    from app.services.librarian import Source
    source = original_source()
    quote_id = source.payload().get('quote_id')
    assert isinstance(quote_id, str) and quote_id
    assert source.payload()['quote_id'] == quote_id
    changed_id = Source(**{**source.__dict__, 'id': 'different-source'})
    changed_text = Source(**{**source.__dict__, 'content': source.content + '\n'})
    bounded_excerpt = Source(**{**source.__dict__, 'content': source.content[:40]})
    assert len({s.payload()['quote_id'] for s in (source, changed_id, changed_text, bounded_excerpt)}) == 4


@pytest.mark.parametrize('invalid', ['forged', 'cross_source', 'stale', 'out_of_scope', 'malformed', 'valid_text_bad_id'])
def test_quote_ids_reject_forged_stale_cross_source_and_malformed_references(invalid):
    from app.services.librarian import Source, validate_answer
    source, other = original_source(), original_source('b')
    reference = {'source_id': source.id, 'quote_id': source.payload().get('quote_id')}
    if invalid == 'cross_source':
        reference['quote_id'] = other.payload().get('quote_id')
    elif invalid == 'stale':
        reference['quote_id'] = Source(**{**source.__dict__, 'content': 'Previous original source content.'}).payload().get('quote_id')
    elif invalid == 'out_of_scope':
        reference['source_id'] = other.id
    elif invalid == 'malformed':
        reference['quote_id'] = ['not-an-id']
    else:
        reference['quote_id'] = 'forged'
        if invalid == 'valid_text_bad_id':
            reference['source_text'] = source.content
    items, rejected = validate_answer({'insufficient_evidence': False, 'items': [{
        'content': '无效引用。', 'kind': 'fact', 'citations': [reference]}]}, [source])
    assert items == [] and rejected == 1


@pytest.mark.parametrize('source_kind,item_kind,accepted', [
    ('paper', 'fact', True), ('user', 'user_note', True), ('external_metadata', 'metadata', True),
    ('user', 'fact', False), ('ai', 'fact', False), ('external_metadata', 'fact', False),
])
def test_quote_id_resolution_preserves_source_provenance(source_kind, item_kind, accepted):
    from app.services.librarian import validate_answer
    source = original_source(kind=source_kind)
    items, rejected = validate_answer({'insufficient_evidence': False, 'items': [{
        'content': '来源声明。', 'kind': item_kind,
        'citations': [{'source_id': source.id, 'quote_id': source.payload().get('quote_id')}]}]}, [source])
    assert bool(items) is accepted
    assert rejected == (0 if accepted else 1)


def test_quote_id_can_recover_short_literal_equation_fragment():
    from app.services.librarian import Source, validate_answer
    source = Source('equation:denominator', 'a', 'Paper A', 'n', 'paper', page=3)
    items, rejected = validate_answer({'insufficient_evidence': False, 'items': [{
        'content': '该公式除以样本数 n。', 'kind': 'fact',
        'citations': [{'source_id': source.id, 'quote_id': source.payload().get('quote_id')}]}]}, [source])
    assert rejected == 0 and items[0].citations[0].source_text == 'n'


@pytest.mark.parametrize('with_id', [False, True])
@pytest.mark.parametrize('original,rewritten', [
    ('models to per-\nform three classification tasks', 'models to\nperform three classification tasks'),
    ('redundant informa-\ntion is excluded.', 'redundant infor-\nmation is excluded.'),
])
def test_pdf_hyphen_transcription_errors_are_rejected_even_with_valid_quote_id(with_id, original, rewritten):
    from app.services.librarian import Source, validate_answer
    source = Source('chunk:a', 'a', 'Paper A', original, 'paper')
    reference = {'source_id': source.id, 'source_text': rewritten}
    if with_id:
        reference['quote_id'] = source.payload().get('quote_id')
    items, rejected = validate_answer({'insufficient_evidence': False, 'items': [{
        'content': '分类机制。', 'kind': 'fact', 'citations': [reference]}]}, [source])
    assert items == [] and rejected == 1


def test_valid_optional_source_text_remains_strict_and_canonical_with_quote_id():
    from app.services.librarian import Source, validate_answer
    source = Source('chunk:a', 'a', 'Paper A', 'Before. The original\nsource states a fact. After.', 'paper')
    items, rejected = validate_answer({'insufficient_evidence': False, 'items': [{
        'content': '原文陈述事实。', 'kind': 'fact',
        'citations': [{'source_id': source.id, 'quote_id': source.payload().get('quote_id'),
            'source_text': 'The original source states a fact.'}]}]}, [source])
    assert rejected == 0 and items[0].citations[0].source_text == 'The original\nsource states a fact.'


def test_quoted_evidence_is_bound_to_each_paper_and_geometry():
    from app.services.librarian import validate_answer
    a, b = original_source(), original_source('b')
    raw = {'insufficient_evidence': False, 'items': [{
        'content': '两个工作都考察检索鲁棒性。', 'kind': 'comparison',
        'citations': [{'source_id': s.id, 'source_text': s.content} for s in (a, b)]}]}
    items, rejected = validate_answer(raw, [a, b])
    assert rejected == 0
    assert {c.paper_id for c in items[0].citations} == {'a', 'b'}
    assert items[0].citations[0].page == 17
    assert items[0].citations[0].source_type == 'paper'


@pytest.mark.parametrize('bad_reference', [
    {'source_id': 'outside-scope', 'source_text': 'The retrieval benchmark'},
    {'source_id': 'source-a', 'source_text': 'This fabricated score is 100 percent.'},
    {'source_id': ['not-a-string'], 'source_text': 'The retrieval benchmark'},
])
def test_forged_out_of_scope_or_malformed_citation_is_dropped(bad_reference):
    from app.services.librarian import validate_answer
    raw = {'insufficient_evidence': False, 'items': [{'content': '不可信结论', 'kind': 'fact', 'citations': [bad_reference]}]}
    items, rejected = validate_answer(raw, [original_source()])
    assert items == []
    assert rejected == 1


@pytest.mark.parametrize('source_kind,item_kind,accepted', [
    ('user', 'fact', False), ('ai', 'fact', False), ('external_metadata', 'fact', False),
    ('user', 'user_note', True), ('external_metadata', 'metadata', True),
    ('paper', 'user_note', False), ('paper', 'metadata', False),
])
def test_notes_and_ai_cards_cannot_become_original_paper_facts(source_kind, item_kind, accepted):
    from app.services.librarian import validate_answer
    source = original_source(kind=source_kind)
    raw = {'insufficient_evidence': False, 'items': [{'content': '来源声明', 'kind': item_kind,
        'citations': [{'source_id': source.id, 'source_text': source.content}]}]}
    items, _ = validate_answer(raw, [source])
    assert bool(items) is accepted


def test_comparison_requires_two_papers():
    from app.services.librarian import validate_answer
    source = original_source()
    items, rejected = validate_answer({'insufficient_evidence': False, 'items': [
        {'content': '两个工作一样', 'kind': 'comparison', 'citations': [{'source_id': source.id, 'source_text': source.content}]}]}, [source])
    assert not items and rejected == 1


def populate_library(client):
    from app.models import Paper, PaperChunk, Note
    with client.app.state.database.sessions() as session:
        session.add_all([Paper(id='a', title='Noise Robustness Benchmark', year=2023),
                         Paper(id='b', title='Retrieval Evaluation', year=2024),
                         Paper(id='secret', title='Other Collection')])
        session.flush()
        session.add_all([PaperChunk(id='a-late', paper_id='a', page=17, section='Results',
                                     content='The noise robustness benchmark retrieves reliable passages.'),
                         PaperChunk(id='b-late', paper_id='b', page=21, section='Experiments',
                                     content='Retrieval evaluation compares accurate citation support.'),
                         PaperChunk(id='secret-early', paper_id='secret', page=1,
                                     content='Noise robustness retrieval outside the selected papers.'),
                         Note(id='note-a', paper_id='a', content='我想把鲁棒性评测迁移到音频任务。', kind='idea')])
        session.commit()


def test_chinese_planner_retrieves_english_late_sources_within_scope(client, monkeypatch):
    from app.services import librarian
    from app.library_schemas import LibraryQuestion
    from types import SimpleNamespace
    populate_library(client)
    captured = []
    def call(database, provider, system, payload, operation, **kwargs):
        captured.append(payload)
        if operation.startswith('library_plan'):
            assert payload['question'] == '比较鲁棒性评测'
            assert {r['paper_id'] for r in payload['catalog']} == {'a', 'b'}
            result = {'queries': ['noise robustness', 'retrieval evaluation'], 'paper_ids': ['a', 'b', 'secret'], 'intent': 'comparison'}
        else:
            sources = [s for s in payload['sources'] if s['type'] == 'paper']
            assert {s['paper_id'] for s in sources} == {'a', 'b'}
            assert {s['page'] for s in sources} == {17, 21}
            result = {'items': [{'kind': 'comparison', 'content': '两篇从噪声鲁棒性和引用支持角度评测。',
                    'citations': [{'source_id': s['source_id'], 'source_text': s['content']} for s in sources]}],
                    'insufficient_evidence': False, 'limitations': []}
        return SimpleNamespace(data=result, usage={'input_tokens': 100, 'output_tokens': 20}, cached=False, model='test')
    monkeypatch.setattr(librarian, 'json_call', call)
    response = librarian.answer_library(client.app.state.database,
        SimpleNamespace(configured=True, mode='remote', name='TestProvider'),
        LibraryQuestion(question='比较鲁棒性评测', paper_ids=['a', 'b']))
    assert not response.insufficient_evidence
    assert response.usage['total_tokens'] == 240
    assert {c.paper_id for c in response.citations} == {'a', 'b'}
    assert response.coverage['comparison_paper_coverage_complete'] is True
    assert response.coverage['comparison_complete'] is None
    assert response.coverage['comparison_coverage_verification'] == 'paper_ids_only'


def test_explicit_scope_never_falls_back_to_whole_library(client):
    from app.services.librarian import catalog_snapshot
    from app.library_schemas import LibraryQuestion
    from fastapi import HTTPException
    populate_library(client)
    with pytest.raises(HTTPException) as error:
        catalog_snapshot(client.app.state.database, LibraryQuestion(question='查找论文', paper_ids=['missing']))
    assert error.value.status_code == 422


def test_metadata_question_does_not_invent_pdf_locator():
    from app.services.librarian import validate_answer, Source
    source = Source('metadata:a', 'a', 'Paper A', '{"title":"Paper A","year":2023}', 'external_metadata')
    items, rejected = validate_answer({'insufficient_evidence': False, 'items': [{'kind': 'metadata',
        'content': 'Paper A 在本库记为 2023 年。', 'citations': [{'source_id': source.id, 'source_text': '"year":2023'}]}]}, [source])
    assert not rejected
    assert items[0].citations[0].page is None
    assert items[0].citations[0].chunk_id is None


@pytest.mark.parametrize('kind', [[], {}, None])
def test_malformed_item_kind_is_rejected(kind):
    from app.services.librarian import validate_answer
    source = original_source()
    items, rejected = validate_answer({'insufficient_evidence': False, 'items': [
        {'content': '无效格式', 'kind': kind, 'citations': [{'source_id': source.id, 'source_text': source.content}]}]}, [source])
    assert items == [] and rejected == 1


def test_ai_summary_is_not_bibliographic_metadata_evidence(client):
    from app.services.librarian import collect_sources
    populate_library(client)
    records = [{'paper_id': 'a', 'title': 'Paper A', 'year': 2023,
                'summary': 'The model outperforms all baselines with 99 percent accuracy.', 'summary_source': 'ai'}]
    sources, _ = collect_sources(client.app.state.database, records, {'intent': 'metadata'}, 'year')
    metadata = next(s for s in sources if s.kind == 'external_metadata')
    assert '99 percent accuracy' not in metadata.content


def test_note_search_reaches_papers_outside_fallback_six(client):
    from app.models import Paper, Note
    from app.services.librarian import collect_sources
    with client.app.state.database.sessions() as session:
        session.add_all([Paper(id=f'p{i:02}', title='Generic paper') for i in range(10)])
        session.flush()
        session.add(Note(id='target-note', paper_id='p09', content='希望研究音频推理中的可靠性。'))
        session.commit()
    records = [{'paper_id': f'p{i:02}', 'title': 'Generic paper'} for i in range(10)]
    sources, _ = collect_sources(client.app.state.database, records,
        {'intent': 'notes', 'queries': ['音频推理'], 'paper_ids': []}, '有哪些音频笔记')
    assert any(s.id == 'note:target-note' and s.kind == 'user' for s in sources)


def test_fts_matching_tail_is_in_submitted_context(client):
    from app.models import Paper, PaperChunk
    from app.services.librarian import collect_sources
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='long', title='Long paper'))
        session.flush()
        session.add(PaperChunk(id='long-tail', paper_id='long', page=45,
            content='filler ' * 1100 + 'The zebraquasar evaluation improves robustness by 15 percent.'))
        session.commit()
    sources, _ = collect_sources(client.app.state.database,
        [{'paper_id': 'long', 'title': 'Long paper'}],
        {'intent': 'research', 'queries': ['zebraquasar'], 'paper_ids': ['long']}, 'zebraquasar result')
    assert any('zebraquasar' in s.content for s in sources if s.kind == 'paper')


def test_comparison_reports_explicit_paper_missing_even_if_planner_omits_it(client, monkeypatch):
    from app.services import librarian
    from app.library_schemas import LibraryQuestion
    from types import SimpleNamespace
    populate_library(client)
    def call(database, provider, system, payload, operation, **kwargs):
        if operation.startswith('library_plan'):
            data = {'queries': ['noise robustness'], 'paper_ids': ['a'], 'intent': 'comparison'}
        else:
            source = next(s for s in payload['sources'] if s['type'] == 'paper' and s['paper_id'] == 'a')
            data = {'insufficient_evidence': False, 'items': [{'kind': 'fact', 'content': 'A评测噪声。',
                'citations': [{'source_id': source['source_id'], 'source_text': source['content']}]}]}
        return SimpleNamespace(data=data, usage={}, cached=False, model='test')
    monkeypatch.setattr(librarian, 'json_call', call)
    response = librarian.answer_library(client.app.state.database,
        SimpleNamespace(configured=True, mode='remote', name='TestProvider'),
        LibraryQuestion(question='比较A和B', paper_ids=['a', 'b']))
    assert any('完整比较' in s for s in response.limitations)


def test_metadata_target_survives_large_catalog_source_cap(client):
    from app.models import Paper
    from app.services.librarian import collect_sources
    with client.app.state.database.sessions() as session:
        session.add_all([Paper(id=f'p{i:03}', title='Generic paper') for i in range(80)])
        session.commit()
    records = [{'paper_id': f'p{i:03}', 'title': 'Generic paper'} for i in range(80)]
    sources, _ = collect_sources(client.app.state.database, records,
        {'intent': 'metadata', 'paper_ids': ['p079'], 'queries': ['year']}, 'year of p079')
    assert any(s.id == 'metadata:p079' for s in sources)


def test_notes_relevance_precedes_per_paper_limit(client):
    from app.models import Paper, Note
    from app.services.librarian import collect_sources
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='notes', title='Notes paper'))
        session.flush()
        session.add_all([Note(id=f'n{i}', paper_id='notes', content='Unrelated personal note.') for i in range(8)])
        session.add(Note(id='target', paper_id='notes', content='Audio robustness is my planned research direction.'))
        session.commit()
    sources, _ = collect_sources(client.app.state.database, [{'paper_id': 'notes', 'title': 'Notes paper'}],
        {'intent': 'notes', 'queries': ['audio robustness']}, 'Which notes discuss audio robustness?')
    assert any(s.id == 'note:target' for s in sources)


def test_matched_chunks_precede_neighbors_under_shared_budget(client):
    from app.models import Paper, PaperChunk
    from app.services.librarian import collect_sources
    records = [{'paper_id': f'p{i}', 'title': 'Paper'} for i in range(12)]
    with client.app.state.database.sessions() as session:
        session.add_all([Paper(id=r['paper_id'], title=r['title']) for r in records])
        session.flush()
        for record in records:
            pid = record['paper_id']
            session.add_all([PaperChunk(id=pid + '-before', paper_id=pid, page=16, content='Unrelated filler. ' * 500),
                PaperChunk(id=pid + '-match', paper_id=pid, page=17, content='The zebraquasar evaluation tests noise robustness.')])
        session.commit()
    sources, _ = collect_sources(client.app.state.database, records,
        {'intent': 'research', 'queries': ['zebraquasar'], 'paper_ids': [r['paper_id'] for r in records]}, 'zebraquasar')
    assert {s.paper_id for s in sources if 'zebraquasar' in s.content} == {r['paper_id'] for r in records}


def test_bibliographic_citation_cannot_complete_method_comparison(client, monkeypatch):
    from app.services import librarian
    from app.library_schemas import LibraryQuestion
    from types import SimpleNamespace
    populate_library(client)
    def call(database, provider, system, payload, operation, **kwargs):
        if operation.startswith('library_plan'):
            data = {'queries': ['noise robustness'], 'paper_ids': ['a', 'b'], 'intent': 'comparison'}
        else:
            original = next(s for s in payload['sources'] if s['type'] == 'paper' and s['paper_id'] == 'a')
            metadata = next(s for s in payload['sources'] if s['type'] == 'external_metadata' and s['paper_id'] == 'b')
            data = {'insufficient_evidence': False, 'items': [
                {'kind': 'fact', 'content': 'A评测噪声。', 'citations': [{'source_id': original['source_id'], 'source_text': original['content']}]},
                {'kind': 'metadata', 'content': 'B是2024年。', 'citations': [{'source_id': metadata['source_id'], 'source_text': '"year": 2024'}]}]}
        return SimpleNamespace(data=data, usage={}, cached=False, model='test')
    monkeypatch.setattr(librarian, 'json_call', call)
    result = librarian.answer_library(client.app.state.database, SimpleNamespace(configured=True, mode='remote', name='Test'),
        LibraryQuestion(question='比较这两篇的方法', paper_ids=['a', 'b']))
    assert result.coverage['comparison_complete'] is False


@pytest.mark.parametrize('bad_stage', ['plan', 'answer', 'citations'])
def test_invalid_model_output_is_evicted_before_retry(client, bad_stage):
    from app.services.librarian import answer_library
    from app.library_schemas import LibraryQuestion
    from app.providers.base import ProviderError
    populate_library(client)
    class Provider:
        configured, mode, name, model = True, 'remote', 'Test', 'model'
        last_usage = {'input_tokens': 10, 'output_tokens': 10}
        def __init__(self):
            self.calls, self.failed = 0, False
        def complete_json(self, system, payload, **kwargs):
            self.calls += 1
            if 'sources' not in payload:
                if bad_stage == 'plan' and not self.failed:
                    self.failed = True
                    return {'queries': 'malformed'}
                return {'queries': ['noise robustness'], 'paper_ids': ['a'], 'intent': 'research'}
            if bad_stage in {'answer', 'citations'} and not self.failed:
                self.failed = True
                return {} if bad_stage == 'answer' else {'insufficient_evidence': False, 'items': [
                    {'content': 'Invented conclusion.', 'kind': 'fact', 'citations': [{'source_id': 'missing', 'source_text': 'Imaginary evidence.'}]}]}
            source = next(s for s in payload['sources'] if s['type'] == 'paper')
            return {'insufficient_evidence': False, 'items': [{'kind': 'fact', 'content': '评测检索鲁棒性。',
                'citations': [{'source_id': source['source_id'], 'source_text': source['content']}]}]}
    provider = Provider()
    question = LibraryQuestion(question='鲁棒性评测', paper_ids=['a'])
    with pytest.raises(ProviderError):
        answer_library(client.app.state.database, provider, question)
    result = answer_library(client.app.state.database, provider, question)
    assert result.items and provider.calls == 3
    again = answer_library(client.app.state.database, provider, question)
    assert again.cached and again.usage['model_calls'] == 0 and provider.calls == 3


@pytest.mark.parametrize('invalid_case,accepted_items', [('single_paper', 2), ('overflow', 16)])
def test_partial_invalid_comparison_evicts_only_answer_and_does_not_claim_complete(client, invalid_case, accepted_items):
    from collections import Counter
    from sqlalchemy import select
    from app.library_schemas import LibraryQuestion
    from app.models import ModelCallCache
    from app.services.librarian import answer_library
    populate_library(client)
    class Provider:
        configured, mode, name, model = True, 'remote', 'Test', 'model'
        last_usage = {'input_tokens': 10, 'output_tokens': 10}
        def __init__(self):
            self.calls = Counter()
        def complete_json(self, system, payload, **kwargs):
            if 'sources' not in payload:
                self.calls['plan'] += 1
                return {'queries': ['noise robustness', 'retrieval evaluation'], 'paper_ids': ['a', 'b'], 'intent': 'comparison'}
            self.calls['answer'] += 1
            sources = {s['paper_id']: s for s in payload['sources'] if s['type'] == 'paper'}
            def item(kind, papers):
                return {'kind': kind, 'content': '评测机制具有原文依据。', 'citations': [
                    {'source_id': sources[pid]['source_id'], 'quote_id': sources[pid].get('quote_id')} for pid in papers]}
            if self.calls['answer'] == 1:
                if invalid_case == 'overflow':
                    outside = {'kind': 'fact', 'content': '越界来源不能成为证据。',
                        'citations': [{'source_id': 'outside-scope', 'quote_id': sources['a'].get('quote_id')}]}
                    return {'insufficient_evidence': False,
                        'items': [item('fact', ['a' if i % 2 == 0 else 'b']) for i in range(16)] + [outside]}
                return {'insufficient_evidence': False, 'items': [item('fact', ['a']), item('fact', ['b']),
                    item('comparison', ['a'])]}
            return {'insufficient_evidence': False, 'items': [item('comparison', ['a', 'b'])]}
    provider = Provider()
    question = LibraryQuestion(question='比较这两篇的三个评测指标', paper_ids=['a', 'b'])
    first = answer_library(client.app.state.database, provider, question)
    assert len(first.items) == accepted_items and first.coverage['rejected_items'] == 1
    assert provider.calls == {'plan': 1, 'answer': 1}
    assert first.coverage['comparison_paper_coverage_complete'] is True
    assert first.coverage['comparison_complete'] is False
    assert any('完整比较' in limitation for limitation in first.limitations)
    with client.app.state.database.sessions() as session:
        assert list(session.scalars(select(ModelCallCache.operation))) == ['library_plan_v1']
    retry = answer_library(client.app.state.database, provider, question)
    assert retry.items and retry.coverage['rejected_items'] == 0
    assert retry.coverage['comparison_complete'] is None
    assert provider.calls == {'plan': 1, 'answer': 2}
    assert retry.usage['model_calls'] == 1 and retry.usage['cache_hits'] == 1 and not retry.cached
    again = answer_library(client.app.state.database, provider, question)
    assert again.cached and again.usage['model_calls'] == 0 and provider.calls == {'plan': 1, 'answer': 2}


def test_rare_query_evidence_outranks_repeated_common_terms(client):
    from app.models import Paper, PaperChunk
    from app.services.librarian import collect_sources
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='ranked', title='A Scientific System'))
        session.flush()
        session.add_all([PaperChunk(id=f'common-{i:02}', paper_id='ranked', page=i + 1,
            content='Common retrieval evaluation describes the general pipeline. ' * 4) for i in range(22)])
        session.add(PaperChunk(id='rare-tail', paper_id='ranked', page=40,
            content='Calibration corrects the confidence bias using held-out observations.'))
        session.commit()
    sources, _ = collect_sources(client.app.state.database, [{'paper_id': 'ranked', 'title': 'A Scientific System'}],
        {'intent': 'research', 'paper_ids': ['ranked'], 'queries': ['common retrieval evaluation calibration']},
        'How is confidence calibrated?')
    originals = [s for s in sources if s.kind == 'paper']
    assert originals[0].chunk_id == 'rare-tail'


def test_each_query_facet_survives_a_stronger_competing_query(client):
    from app.models import Paper, PaperChunk
    from app.services.librarian import collect_sources
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='facets', title='A Scientific System'))
        session.flush()
        session.add_all([PaperChunk(id=f'quality-{i:02}', paper_id='facets', page=i + 1,
            content='Accuracy precision coverage evaluation compares the pipeline.') for i in range(22)])
        session.add(PaperChunk(id='latency-tail', paper_id='facets', page=40,
            content='Latency grows linearly with the number of retrieved passages.'))
        session.commit()
    sources, _ = collect_sources(client.app.state.database, [{'paper_id': 'facets', 'title': 'A Scientific System'}],
        {'intent': 'research', 'paper_ids': ['facets'], 'queries': ['accuracy precision coverage evaluation', 'latency']},
        'Compare quality and computational cost.')
    assert any(s.chunk_id == 'latency-tail' for s in sources)
    assert any(s.chunk_id and s.chunk_id.startswith('quality-') for s in sources)


def test_requested_parent_section_retrieves_subsection_topics_without_repeated_query_words(client):
    from app.models import Paper, PaperChunk
    from app.services.librarian import collect_sources
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='sections', title='Omni Retrieval: A Survey'))
        session.flush()
        session.add_all([PaperChunk(id=f'overview-{i:02}', paper_id='sections', page=i + 1, section='1 Introduction',
            content='Omni retrieval survey discusses future research evaluation challenges and efficiency.') for i in range(24)])
        session.add(PaperChunk(id='future-heading', paper_id='sections', page=28, section='12 Future Prospects', content='12\nFuture Prospects'))
        for i, topic in enumerate(['Dynamic maintenance', 'Multimodal integration', 'Scaling', 'Foundation models', 'Compression', 'Benchmarks', 'Applications']):
            session.add(PaperChunk(id=f'future-{i}', paper_id='sections', page=29 + i // 4,
                section=f'12.{i + 1} {topic}', content=f'{topic}\nThe authors identify an unresolved scientific problem. ' + 'A substantial original argument. ' * 5))
        session.add(PaperChunk(id='references', paper_id='sections', page=35, section='13 References', content='Future research appears in a bibliography entry.'))
        session.commit()
    sources, coverage = collect_sources(client.app.state.database,
        [{'paper_id': 'sections', 'title': 'Omni Retrieval: A Survey'}],
        {'intent': 'research', 'paper_ids': ['sections'], 'queries': ['Omni retrieval survey evaluation challenges efficiency future research']},
        'What future directions do the authors identify?')
    assert {f'future-{i}' for i in range(7)} <= {s.chunk_id for s in sources}
    assert coverage['source_characters'] <= 48000 and len(sources) <= 72


def test_evaluation_definition_keeps_column_continuation_and_split_formula(client):
    from app.models import Paper, PaperChunk
    from app.services.librarian import collect_sources
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='equations', title='A Scientific Evaluator'))
        session.flush()
        session.add_all([PaperChunk(id=f'overview-{i:02}', paper_id='equations', page=i + 1, section='1 Introduction',
            content='Evaluation metrics compare faithfulness, context relevance and answer relevance.') for i in range(22)])
        entries = [
            ('definition', 'Answer relevance\nThe evaluator generates reverse questions from the answer as follows:', [300, 100, 520, 180]),
            ('other-column', 'A discussion of unrelated observations in the other column.', [60, 180, 280, 230]),
            ('prompt', 'Generate questions from the supplied answer.', [320, 190, 500, 220]),
            ('stub', 'We obtain embeddings for these questions us-', [300, 230, 520, 242]),
            ('cosine', 'ing an embedding model. Cosine similarity compares each generated question to the original one. The score is computed as:', [300, 246, 520, 300]),
            ('sum', 'n\nΣ', [380, 310, 395, 325]),
            ('lhs', 'Q = 1', [340, 310, 375, 325]),
            ('rhs', 'sim(q, qi)', [400, 312, 515, 330]),
            ('denominator', 'n', [366, 326, 375, 338]),
            ('index', 'i=1', [382, 329, 399, 340]),
        ]
        for i, (name, content, bbox) in enumerate(entries):
            session.add(PaperChunk(id=f'eq-{i:02}-{name}', paper_id='equations', page=40,
                section='3 Evaluation Strategies', content=content, bbox_json=json.dumps(bbox)))
        session.commit()
    sources, _ = collect_sources(client.app.state.database, [{'paper_id': 'equations', 'title': 'A Scientific Evaluator'}],
        {'intent': 'research', 'paper_ids': ['equations'], 'queries': ['evaluation metrics context relevance faithfulness answer relevance']},
        'How are the evaluation metrics calculated?')
    submitted = {s.chunk_id for s in sources}
    assert {f'eq-{i:02}-{name}' for i, (name, _, _) in enumerate(entries) if name != 'other-column'} <= submitted
    assert all(s.content in next(content for name, content, _ in entries if s.chunk_id.endswith(name))
        for s in sources if s.chunk_id and s.chunk_id.startswith('eq-'))


@pytest.mark.parametrize('intent', ['metadata', 'notes'])
def test_metadata_and_notes_intents_skip_pdf_search_and_ai_context(client, monkeypatch, intent):
    from app.services import librarian
    from app.models import PaperAnalysis
    populate_library(client)
    with client.app.state.database.sessions() as session:
        session.add(PaperAnalysis(paper_id='a', mode='remote', one_liner='An unrelated AI summary.',
            card_json=json.dumps({'method': {'content': 'An unrelated method.', 'evidence_ids': []}})))
        session.commit()
    def no_pdf_search(*args, **kwargs):
        pytest.fail('Metadata or note retrieval must not search PDF text.')
    monkeypatch.setattr(librarian, '_fts', no_pdf_search)
    sources, coverage = librarian.collect_sources(client.app.state.database,
        [{'paper_id': 'a', 'title': 'Paper A'}, {'paper_id': 'b', 'title': 'Paper B'}],
        {'intent': intent, 'queries': ['audio', '音频'], 'paper_ids': ['a', 'b']}, '音频笔记' if intent == 'notes' else '作者和年份')
    assert all(s.kind in {'external_metadata', 'user'} for s in sources)
    assert any(s.kind == 'external_metadata' for s in sources)
    if intent == 'notes':
        assert any(s.id == 'note:note-a' for s in sources)
    assert coverage['source_characters'] < 2000


def test_note_question_without_notes_does_not_send_paper_text(client):
    from app.services.librarian import collect_sources
    from app.models import Paper, PaperChunk
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='no-notes', title='A Scientific System'))
        session.flush()
        session.add(PaperChunk(id='large-body', paper_id='no-notes', content='Original scientific evidence. ' * 1500))
        session.commit()
    sources, coverage = collect_sources(client.app.state.database, [{'paper_id': 'no-notes', 'title': 'A Scientific System'}],
        {'intent': 'notes', 'queries': ['my research ideas'], 'paper_ids': ['no-notes']}, 'What are my personal research notes?')
    assert not any(s.kind in {'paper', 'ai'} for s in sources)
    assert coverage['source_characters'] < 1000


def test_specific_metrics_section_survives_broad_parent_and_future_taxonomy(client):
    from app.models import Paper, PaperChunk
    from app.services.librarian import collect_sources
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='taxonomy', title='Omni Retrieval: A Survey'))
        session.flush()
        session.add_all([PaperChunk(id=f'overview-{i:02}', paper_id='taxonomy', page=i + 1, section='1 Introduction',
            content='Omni retrieval survey discusses evaluation metrics future directions and efficiency.') for i in range(20)])
        session.add(PaperChunk(id='broad-evaluation', paper_id='taxonomy', page=24, section='9 Evaluation',
            content='An overview introduces the chapter and its various evaluation settings. ' * 3))
        for i in range(7):
            session.add(PaperChunk(id=f'evaluation-{i}', paper_id='taxonomy', page=25,
                section=f'9.{i + 1} Application {i}', content='An application uses this scientific framework on a particular task. ' * 3))
            session.add(PaperChunk(id=f'prospect-{i}', paper_id='taxonomy', page=30,
                section=f'12.{i + 1} Topic {i}', content='An unresolved scientific problem requires further investigation. ' * 3))
        session.add_all([PaperChunk(id='metric-definition', paper_id='taxonomy', page=28, section='9.8 Benchmarks and Metrics',
            content='The proposed metrics distinguish generation quality from retrieval coverage. ' * 3),
            PaperChunk(id='prospects-heading', paper_id='taxonomy', page=29, section='12 Future Prospects', content='12\nFuture Prospects')])
        session.commit()
    sources, _ = collect_sources(client.app.state.database, [{'paper_id': 'taxonomy', 'title': 'Omni Retrieval: A Survey'}],
        {'intent': 'research', 'paper_ids': ['taxonomy'], 'queries': ['Omni retrieval evaluation metrics efficiency future research']},
        'Explain evaluation metrics and future directions.')
    assert any(s.chunk_id == 'metric-definition' for s in sources)
    assert {f'prospect-{i}' for i in range(7)} <= {s.chunk_id for s in sources}


def test_narrow_formula_anchor_recovers_fragments_above_and_beside_it():
    from app.models import PaperChunk
    from app.services.librarian import _continuation
    entries = [
        ('prose', 'The vector-based metric is computed using this mathematical expression:', [300, 200, 520, 280]),
        ('other-column', 'Unrelated scientific discussion in a different column.', [60, 270, 280, 325]),
        ('sum', 'n\nΣ', [390, 291, 408, 310]),
        ('lhs', 'Q = 1', [340, 298, 380, 315]),
        ('rhs', 'sim(q, qi)', [415, 306, 515, 320]),
        ('denominator', 'n', [366, 314, 375, 326]),
        ('index', 'i=1', [392, 318, 408, 330]),
    ]
    chunks = [PaperChunk(id=name, paper_id='p', page=3, section='3 Evaluation', content=content, bbox_json=json.dumps(bbox))
        for name, content, bbox in entries]
    continuation = _continuation(chunks[3], chunks)
    assert {'sum', 'rhs', 'denominator', 'index'} <= {c.id for c in continuation}
    assert not any(c.id == 'other-column' for c in continuation)


def test_numbered_subheading_keeps_both_following_evidence_categories(client):
    from app.models import Paper, PaperChunk
    from app.services.librarian import collect_sources
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='categories', title='Omni Retrieval Survey'))
        session.flush()
        session.add_all([PaperChunk(id=f'overview-{i:02}', paper_id='categories', page=i + 1, section='1 Introduction',
            content='Omni retrieval evaluation metrics provide a broad overview of the research system.') for i in range(22)])
        session.add_all([PaperChunk(id='heading-000', paper_id='categories', page=30, section='5.2 Evaluation Metrics',
            content='5.2.1\nMetrics. This subsection organizes the measures into two different categories with different scientific purposes.'),
            PaperChunk(id='heading-001', paper_id='categories', page=30, section='5.2 Evaluation Metrics',
                content='The first category measures output quality using agreement with expected entities and semantic similarity.'),
            PaperChunk(id='heading-002', paper_id='categories', page=30, section='5.2 Evaluation Metrics',
                content='The second category measures evidence coverage, balances subgraph size with answer recall, and considers factual support.')])
        session.commit()
    sources, _ = collect_sources(client.app.state.database, [{'paper_id': 'categories', 'title': 'Omni Retrieval Survey'}],
        {'intent': 'research', 'paper_ids': ['categories'], 'queries': ['Omni retrieval evaluation metrics']},
        'Which categories do the authors distinguish?')
    assert {'heading-000', 'heading-001', 'heading-002'} <= {s.chunk_id for s in sources}


@pytest.mark.parametrize('edited_source', ['note', 'card', 'original'])
def test_source_content_edit_refreshes_answer_without_replanning_unchanged_catalog(client, edited_source):
    from collections import Counter
    from app.models import Note, Paper, PaperAnalysis, PaperChunk
    from app.services.librarian import answer_library
    from app.library_schemas import LibraryQuestion
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='cache-edit', title='Audio Robustness'))
        session.flush()
        session.add_all([PaperChunk(id='original', paper_id='cache-edit', page=2,
            content='The original audio robustness evidence measures reliable retrieval.'),
            Note(id='personal', paper_id='cache-edit', content='My audio robustness idea concerns reliable retrieval.'),
            PaperAnalysis(paper_id='cache-edit', mode='remote', one_liner='A stable catalog summary.',
                card_json=json.dumps({'method': {'content': 'Audio robustness uses the previous orientation.', 'evidence_ids': []}}))])
        session.commit()
    class Provider:
        configured, mode, name, model = True, 'remote', 'Fake', 'fake-v1'
        last_usage = {'input_tokens': 10, 'output_tokens': 5}
        def __init__(self):
            self.calls, self.submitted = Counter(), []
        def complete_json(self, system, payload, **kwargs):
            if 'sources' not in payload:
                self.calls['plan'] += 1
                return {'queries': ['audio robustness'], 'paper_ids': ['cache-edit'],
                    'intent': 'notes' if edited_source == 'note' else 'research'}
            self.calls['answer'] += 1
            self.submitted.append(json.loads(json.dumps(payload['sources'])))
            kind = 'user' if edited_source == 'note' else 'paper'
            source = next(s for s in payload['sources'] if s['type'] == kind)
            return {'insufficient_evidence': False, 'items': [{'kind': 'user_note' if kind == 'user' else 'fact',
                'content': source['content'], 'citations': [{'source_id': source['source_id'], 'source_text': source['content']}]}]}
    provider = Provider()
    question = LibraryQuestion(question='Audio robustness evidence', paper_ids=['cache-edit'])
    first = answer_library(client.app.state.database, provider, question)
    repeated = answer_library(client.app.state.database, provider, question)
    assert repeated.cached and provider.calls == {'plan': 1, 'answer': 1}
    with client.app.state.database.sessions() as session:
        if edited_source == 'note':
            session.get(Note, 'personal').content = 'My edited audio robustness idea concerns uncertainty calibration.'
        elif edited_source == 'card':
            session.get(PaperAnalysis, 'cache-edit').card_json = json.dumps({
                'method': {'content': 'Audio robustness now uses the edited orientation.', 'evidence_ids': []}})
        else:
            session.get(PaperChunk, 'original').content = 'The edited audio robustness evidence measures uncertainty calibration.'
        session.commit()
    refreshed = answer_library(client.app.state.database, provider, question)
    assert provider.calls == {'plan': 1, 'answer': 2}
    assert not refreshed.cached and refreshed.usage['model_calls'] == 1
    assert provider.submitted[0] != provider.submitted[1]
    if edited_source != 'card':
        assert refreshed.citations[0].source_text != first.citations[0].source_text
    else:
        assert any(s['type'] == 'ai' and 'edited orientation' in s['content'] for s in provider.submitted[1])
    assert answer_library(client.app.state.database, provider, question).cached
    assert provider.calls == {'plan': 1, 'answer': 2}


@pytest.mark.parametrize('query', ['音频推理鲁棒性研究', 'F1', 'EM'])
def test_cjk_and_short_metric_query_can_reach_paper_outside_fallback_scope(client, query):
    from app.models import Paper, PaperChunk
    from app.services.librarian import collect_sources
    records = [{'paper_id': f'p{i:02}', 'title': 'Generic scientific paper'} for i in range(10)]
    with client.app.state.database.sessions() as session:
        session.add_all([Paper(id=r['paper_id'], title=r['title']) for r in records])
        session.flush()
        session.add(PaperChunk(id='target-metric', paper_id='p09', page=12,
            content=query if len(query) > 2 else query + ' score measures exact-match accuracy.'))
        session.commit()
    sources, _ = collect_sources(client.app.state.database, records,
        {'intent': 'research', 'queries': [query], 'paper_ids': []}, query)
    assert any(s.chunk_id == 'target-metric' for s in sources)
