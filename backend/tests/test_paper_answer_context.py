from types import SimpleNamespace

import pytest

from app.library_schemas import LibraryQuestion
from app.models import Paper, PaperChunk
from app.services import librarian


def test_single_paper_question_reads_low_lexical_relevance_appendix_along_with_entire_text(client, monkeypatch):
    with client.app.state.database.sessions() as session:
        session.add_all([Paper(id='reading', title='Research Agent'), Paper(id='outside', title='Private other paper')])
        session.flush()
        session.add_all([PaperChunk(id=f'block-{i:04}', paper_id='reading', page=i // 20 + 1,
            section='A Evaluation', content=f'Reflection evaluation appendix result {i}. ' * 3)
            for i in range(180)])
        session.add(PaperChunk(id='negative-result', paper_id='reading', page=14,
            section='B.1 WebShop Limitation', content='Shopping failed to improve after four trials. Exploration became trapped.'))
        session.add(PaperChunk(id='secret', paper_id='outside', page=1, content='Never send this unrelated original.'))
        session.commit()
    captured = []
    def call(database, provider, system, payload, **kwargs):
        captured.append(payload)
        if 'sources' not in payload:
            data = {'intent': 'research', 'paper_ids': ['reading'], 'queries': ['appendix reflection evaluation']}
        else:
            originals = [s for s in payload['sources'] if s['type'] == 'paper']
            assert len(originals) == 181
            assert any('Shopping failed' in s['content'] for s in originals)
            assert not any('unrelated original' in s['content'] for s in originals)
            assert payload['coverage']['retrieval_is_partial'] is False
            assert payload['coverage']['reading_mode'] == 'full_paper'
            assert list(payload).index('sources') < list(payload).index('question')
            assert 'B.1 WebShop Limitation' in str(payload['coverage']['paper_context']['sections'])
            source = next(s for s in originals if 'Shopping failed' in s['content'])
            data = {'items': [{'kind': 'inference', 'content': '## 先读局限\n\n建议先读失败实验，再判断反思的有效条件。',
                'citations': [{'source_id': source['source_id'], 'quote_id': source['quote_id']}]}],
                'insufficient_evidence': False, 'limitations': []}
        return SimpleNamespace(data=data, usage={}, cached=False, model='test')
    monkeypatch.setattr(librarian, 'json_call', call)
    result = librarian.answer_library(client.app.state.database,
        SimpleNamespace(configured=True, mode='remote', name='Test'),
        LibraryQuestion(question='这篇论文的附录部分还有什么值得读的地方吗？', paper_ids=['reading']))
    assert result.citations[0].chunk_id == 'negative-result'
    assert result.coverage['paper_context']['provided_chunks'] == 181


def test_background_explanations_need_no_fabricated_paper_citation_but_facts_still_do():
    items, rejected = librarian.validate_answer({'insufficient_evidence': False, 'items': [
        {'kind': 'background', 'content': '作为一般背景，探索决定访问哪些候选策略，反思则可利用已有反馈。', 'citations': []},
        {'kind': 'fact', 'content': '这篇论文报告了某个具体结果。', 'citations': []},
    ]}, [])
    assert len(items) == 1 and items[0].kind == 'background'
    assert rejected == 1


def test_identical_source_references_are_resolved_only_once():
    source = librarian.Source('block', 'paper', 'Paper', 'A real original source paragraph.', 'paper', page=3)
    ref = {'source_id': source.id, 'quote_id': source.quote_id}
    items, rejected = librarian.validate_answer({'insufficient_evidence': False, 'items': [
        {'kind': 'fact', 'content': 'An original fact.', 'citations': [ref, ref]}]}, [source])
    assert rejected == 0 and len(items[0].citations) == 1


@pytest.mark.parametrize('kind', ['ai', 'user', 'external_metadata'])
def test_background_cannot_turn_notes_or_a_summary_into_paper_evidence(kind):
    source = librarian.Source('source', 'paper', 'Paper', 'A supplied but non-original source.', kind)
    items, rejected = librarian.validate_answer({'insufficient_evidence': False, 'items': [
        {'kind': 'background', 'content': 'General explanation.', 'citations': [
            {'source_id': source.id, 'quote_id': source.quote_id}]}]}, [source])
    assert not items and rejected == 1


def test_complete_text_keeps_long_chunk_slices_unchanged_and_bounded(client):
    content = 'This is a long unchanged original paragraph. ' * 350
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='long-block', title='Long block'))
        session.flush()
        session.add(PaperChunk(id='original', paper_id='long-block', page=3, content=content))
        session.commit()
    sources, coverage = librarian.complete_paper_sources(client.app.state.database, {'paper_id': 'long-block', 'title': 'Long block'})
    assert ''.join(s.content for s in sources) == content
    assert all(len(s.content) <= 6000 for s in sources)
    assert len({s.id for s in sources}) == len(sources)
    assert coverage['paper_context']['provided_chunks'] == 1
    assert coverage['paper_context']['provided_characters'] == len(content)
    for source in sources:
        items, rejected = librarian.validate_answer({'insufficient_evidence': False, 'items': [
            {'kind': 'fact', 'content': 'A supported claim.', 'citations': [
                {'source_id': source.id, 'quote_id': source.quote_id}]}]}, sources)
        assert rejected == 0 and items[0].citations[0].chunk_id == 'original'


def test_oversized_document_uses_partial_retrieval_without_claiming_full_reading(client, monkeypatch):
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='large-paper', title='Large document'))
        session.flush()
        session.add(PaperChunk(id='large-original', paper_id='large-paper', page=1, content='Research original text. ' * 100))
        session.commit()
    monkeypatch.setattr(librarian, 'FULL_PAPER_CHARS', 100)
    assert librarian.complete_paper_sources(client.app.state.database, {'paper_id': 'large-paper', 'title': 'Large document'}) is None
    sources, coverage = librarian.collect_sources(client.app.state.database, [{'paper_id': 'large-paper', 'title': 'Large document'}],
        {'intent': 'research', 'paper_ids': ['large-paper'], 'queries': ['Research']}, 'Read this research paper')
    assert sources and coverage['retrieval_is_partial'] is True
    assert coverage.get('reading_mode') != 'full_paper'


def test_complete_text_reads_actual_imported_pdf_columns_instead_of_interleaving_by_height(client, tmp_path):
    import pymupdf as fitz
    from app.services.pdf import parse_pdf
    from app.services.importing import attach_parsed
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        for label, x, y in [('LEFT_FIRST', 40, 50), ('LEFT_SECOND', 40, 170),
                            ('RIGHT_FIRST', 320, 50), ('RIGHT_SECOND', 320, 170)]:
            text = label + '\n' + ('A sustained body paragraph for reading order.\n' * 4)
            assert page.insert_textbox(fitz.Rect(x, y, x + 240, y + 100), text, fontsize=11) > 0
        data = document.tobytes()
    path = tmp_path / 'columns.pdf'
    path.write_bytes(data)
    parsed = parse_pdf(data)
    assert [block.content.splitlines()[0] for block in parsed.blocks] == [
        'LEFT_FIRST', 'RIGHT_FIRST', 'LEFT_SECOND', 'RIGHT_SECOND']
    with client.app.state.database.sessions() as session:
        paper = Paper(id='columns', title='Two column paper', pdf_path=str(path))
        attach_parsed(paper, parsed)
        session.add(paper)
        session.commit()
    sources, _ = librarian.complete_paper_sources(client.app.state.database,
        {'paper_id': 'columns', 'title': 'Two column paper'})
    assert [source.content.splitlines()[0] for source in sources] == [
        'LEFT_FIRST', 'LEFT_SECOND', 'RIGHT_FIRST', 'RIGHT_SECOND']
    assert {s.content for s in sources} == {block.content for block in parsed.blocks}


def test_combined_context_budget_includes_notes_and_falls_back_to_scoped_retrieval(client, monkeypatch):
    import json
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='budget', title='Context budget'))
        session.flush()
        session.add(PaperChunk(id='original', paper_id='budget', page=1, content='Original research. ' * 200))
        session.commit()
    record = {'paper_id': 'budget', 'title': 'Context budget'}
    originals, _ = librarian.complete_paper_sources(client.app.state.database, record)
    monkeypatch.setattr(librarian, 'FULL_PAPER_PAYLOAD_CHARS', len(json.dumps([s.payload() for s in originals], ensure_ascii=False)) + 500)
    assert librarian.complete_paper_sources(client.app.state.database, record) is not None
    excerpt = librarian.Source('excerpt', 'budget', 'Context budget', 'Original research.', 'paper', page=1)
    note = librarian.Source('note', 'budget', 'Context budget', 'My reading note. ' * 100, 'user')
    monkeypatch.setattr(librarian, 'collect_sources', lambda *args: ([excerpt, note], {
        'candidate_paper_ids': ['budget'], 'selected_paper_ids': ['budget'], 'queries': ['research'],
        'retrieval_is_partial': True, 'sources': 2, 'source_characters': len(excerpt.content) + len(note.content)}))
    def call(database, provider, system, payload, **kwargs):
        if 'sources' not in payload:
            data = {'intent': 'research', 'paper_ids': ['budget'], 'queries': ['research']}
        else:
            assert payload['coverage']['retrieval_is_partial'] is True
            assert payload['coverage'].get('reading_mode') != 'full_paper'
            assert len(json.dumps(payload['sources'], ensure_ascii=False)) < librarian.FULL_PAPER_PAYLOAD_CHARS
            source = next(s for s in payload['sources'] if s['type'] == 'paper')
            assert source['content'] == excerpt.content
            assert any(s['type'] == 'user' for s in payload['sources'])
            data = {'insufficient_evidence': False, 'items': [{'kind': 'fact', 'content': 'A supported result.',
                'citations': [{'source_id': source['source_id'], 'quote_id': source['quote_id']}]}]}
        return SimpleNamespace(data=data, usage={}, cached=False, model='test')
    monkeypatch.setattr(librarian, 'json_call', call)
    answer = librarian.answer_library(client.app.state.database,
        SimpleNamespace(configured=True, mode='remote', name='Test'),
        LibraryQuestion(question='Explain this research.', paper_ids=['budget']))
    assert answer.coverage['retrieval_is_partial'] is True
