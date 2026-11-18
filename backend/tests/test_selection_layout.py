import json
from pathlib import Path

import pytest
import pymupdf as fitz
from app.models import Paper, PaperChunk
from app.providers.validation import canonical_quote


@pytest.fixture
def memory_selection():
    data = json.loads((Path(__file__).parent / 'fixtures/agentic_memory_selection.json').read_text(encoding='utf-8'))
    return data['source'], data['selection']


def test_rendered_greek_name_and_citation_spacing_resolve_to_original_span(memory_selection):
    from app.services.selection_source import resolve_pdf_selection
    source, selection = memory_selection
    chunk = PaperChunk(id='memory-source', paper_id='memory', page=26, content=source)
    paper = Paper(id='memory', title='Memory survey', chunks=[chunk])
    result = resolve_pdf_selection(paper, selection, page=26)
    assert result is not None
    assert result.anchor.id == chunk.id
    assert result.text in source
    assert 'Mem-α' in result.text
    assert canonical_quote(source, result.text) == result.text
    assert source == chunk.content


@pytest.mark.parametrize('replacement', ['Mem-β', 'Mem-315', 'Memory-R2', 'Mirax'])
def test_selection_recovery_preserves_greek_letters_names_and_numbers(memory_selection, replacement):
    from app.services.selection_source import resolve_pdf_selection
    source, selection = memory_selection
    selected = selection.replace('Mem- α', replacement) if replacement.startswith('Mem-') else selection.replace(
        'Memory-R1' if replacement.startswith('Memory') else 'Mirix', replacement)
    paper = Paper(id='memory', title='Memory', chunks=[PaperChunk(id='memory-source', paper_id='memory', page=26, content=source)])
    assert resolve_pdf_selection(paper, selected, page=26) is None


@pytest.mark.parametrize('hint', ['header', 'removed-old-chunk', None])
def test_explain_resolves_actual_selection_despite_guessed_or_stale_chunk(client, memory_selection, monkeypatch, hint):
    from app.providers.base import AnswerResult, VerifiedCitation
    source, selection = memory_selection
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='memory', title='Memory', chunks=[
            PaperChunk(id='header', paper_id='memory', page=26, content='Agentic Reasoning for Large Language Models'),
            PaperChunk(id='memory-source', paper_id='memory', page=26, content=source),
        ]))
        session.commit()
    calls = []
    class Provider:
        name, mode, configured = 'MemoryFixture', 'remote', True
        def ask(self, question, chunks):
            calls.append((question, chunks))
            original = next(c for c in chunks if c.id == 'memory-source')
            return AnswerResult('可以把它理解成会整理自己的研究笔记。', [], False,
                [VerifiedCitation(original, original.content, '动态整理记忆', 'llm_summary')])
    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: Provider())
    payload = {'page':26, 'selected_text':selection, 'question':'给我通俗的讲讲这个方向'}
    if hint: payload['chunk_id'] = hint
    context = {**{k:v for k,v in payload.items() if k != 'question'}, 'visual':False}
    chat = client.post('/api/conversations', json={'kind':'explanation', 'paper_id':'memory', 'context':context}).json()
    response = client.post('/api/papers/memory/explain', json={**payload, 'conversation_id':chat['id']})
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert calls[0][1][0].id == 'memory-source'
    assert 'Mem-α' in calls[0][0]
    assert response.json()['citations'][0]['source_text'] in source
    assert client.get('/api/conversations/'+chat['id']).json()['turns'][0]['status'] == 'completed'


def test_selection_recovery_does_not_rebind_another_papers_chunk(client, memory_selection):
    source, selection = memory_selection
    with client.app.state.database.sessions() as session:
        session.add_all([
            Paper(id='memory', title='Memory', chunks=[PaperChunk(id='memory-source', paper_id='memory', page=26, content=source)]),
            Paper(id='other', title='Other', chunks=[PaperChunk(id='other-source', paper_id='other', page=26, content=source)]),
        ])
        session.commit()
    response = client.post('/api/papers/memory/explain', json={
        'page':26, 'chunk_id':'other-source', 'selected_text':selection, 'question':'解释这一段'})
    assert response.status_code == 404


@pytest.mark.parametrize('next_page', [26, 27])
def test_rendered_memory_selection_survives_block_and_page_boundaries(memory_selection, next_page):
    from app.services.selection_source import resolve_pdf_selection
    source, selection = memory_selection
    start = source.index('Similarly,')
    paper = Paper(id='memory', title='Memory', chunks=[
        PaperChunk(id='memory-a', paper_id='memory', page=26, content=source[:start]),
        PaperChunk(id='header', paper_id='memory', page=next_page, content='Agentic Reasoning for Large Language Models'),
        PaperChunk(id='memory-b', paper_id='memory', page=next_page, content=source[start:]),
    ])
    result = resolve_pdf_selection(paper, selection, page=26)
    assert result is not None
    assert [chunk.id for chunk in result.chunks] == ['memory-a', 'memory-b']


@pytest.fixture
def metrics():
    data = json.loads((Path(__file__).parent / 'fixtures/deepswe_pass4_selection.json').read_text(encoding='utf-8'))
    chunks = [PaperChunk(id=item['id'], paper_id='metrics-paper', page=item['page'], content=item['content'],
                        bbox_json=json.dumps(item['bbox']), page_width=612, page_height=792) for item in data['chunks']]
    return Paper(id='metrics-paper', title='Metrics', chunks=chunks), data['selection']


def test_formula_selection_resolves_only_with_font_verified_glyph_mapping(metrics, monkeypatch):
    from app.services.selection_source import resolve_pdf_selection
    paper, selection = metrics
    monkeypatch.setattr('app.services.selection_source.pdf_comparison_views',
                        lambda paper, pages: {'metrics-1': 'N\n∑'})
    result = resolve_pdf_selection(paper, selection, page=12)
    assert result is not None
    assert result.layout_recovered
    assert result.anchor.id == 'metrics-0'
    assert {chunk.id for chunk in result.chunks} == {chunk.id for chunk in paper.chunks}
    assert result.text == selection
    # Citations retain their stronger literal-source contract.
    assert canonical_quote('N\nX', 'N ∑') is None
    assert paper.chunks[1].content == 'N\nX'


@pytest.mark.parametrize('change', [
    lambda text: text.replace('N = 113', 'N = 114'),
    lambda text: text.replace('≥ 1', '≥ 2'),
    lambda text: text.replace('≥ 1', '≤ 1'),
    lambda text: text.replace('mildly understate', 'always overstate'),
    lambda text: text + ' This method is optimal for all tasks.',
])
def test_layout_matching_does_not_accept_changed_numbers_operators_or_prose(metrics, monkeypatch, change):
    from app.services.selection_source import resolve_pdf_selection
    paper, selection = metrics
    monkeypatch.setattr('app.services.selection_source.pdf_comparison_views',
                        lambda paper, pages: {'metrics-1': 'N\n∑'})
    assert resolve_pdf_selection(paper, change(selection), page=12) is None


def test_regular_x_and_remote_page_cannot_be_used_to_repair_math_selection(metrics, monkeypatch):
    from app.services.selection_source import resolve_pdf_selection
    paper, selection = metrics
    monkeypatch.setattr('app.services.selection_source.pdf_comparison_views', lambda paper, pages: {})
    assert resolve_pdf_selection(paper, selection, page=12) is None
    monkeypatch.setattr('app.services.selection_source.pdf_comparison_views',
                        lambda paper, pages: {'metrics-1': 'N\n∑'})
    assert resolve_pdf_selection(paper, selection, page=3) is None


def test_layout_recovery_cannot_insert_words_from_other_prose_blocks(metrics, monkeypatch):
    from app.services.selection_source import resolve_pdf_selection
    paper, selection = metrics
    paper.chunks.append(PaperChunk(id='unrelated',paper_id=paper.id,page=12,
                                  content='This method can always overstate reliability on unrelated tasks.'))
    monkeypatch.setattr('app.services.selection_source.pdf_comparison_views',
                        lambda paper, pages: {'metrics-1': 'N\n∑'})
    assert resolve_pdf_selection(paper,selection.replace('mildly understate','always overstate'),page=12) is None


def test_math_selection_can_start_and_end_inside_a_prose_block(metrics, monkeypatch):
    from app.services.selection_source import resolve_pdf_selection
    paper, selection = metrics
    monkeypatch.setattr('app.services.selection_source.pdf_comparison_views',
                        lambda paper, pages: {'metrics-1': 'N\n∑'})
    partial = selection[selection.index('fraction of'):selection.index('The only approximation')]
    assert resolve_pdf_selection(paper,partial,page=12) is not None


@pytest.mark.parametrize('remote', [False, True])
def test_explain_recovers_math_context_and_keeps_conversation_identity(client, metrics, monkeypatch, remote):
    from app.providers.base import AnswerResult, VerifiedCitation
    paper, selection = metrics
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72,90), 'Metrics source fixture')
    imported = client.post('/api/papers/import', files={'file':('metrics.pdf',pdf.tobytes())}).json()
    pdf.close()
    with client.app.state.database.sessions() as session:
        for chunk in paper.chunks:
            session.add(PaperChunk(id=chunk.id, paper_id=imported['id'], page=1, content=chunk.content,
                                  bbox_json=chunk.bbox_json, page_width=612, page_height=792))
        session.commit()
    monkeypatch.setattr('app.services.selection_source.pdf_comparison_views',
                        lambda paper, pages: {'metrics-1': 'N\n∑'})
    calls = []
    class Provider:
        name,mode,configured = 'MathVisionFixture','remote',True
        def ask_with_image(self, question, chunks, image):
            calls.append((question,chunks,image))
            original = next(chunk for chunk in chunks if chunk.id=='metrics-0')
            return AnswerResult('每道题尝试四次，只要有一次成功就算这道题成功。',[],False,
                                [VerifiedCitation(original,original.content,'四次尝试中至少一次成功','llm_summary')])
        def ask(self,*args):
            raise AssertionError('A damaged math formula should use its local PDF image')
    if remote:
        monkeypatch.setattr('app.api.papers.get_model_provider',lambda:Provider())
    context = {'page':1,'chunk_id':'metrics-0','selected_text':selection,'visual':False}
    conversation = client.post('/api/conversations', json={'kind':'explanation','paper_id':imported['id'],'context':context}).json()
    for question in ['通俗解释 pass@4','它和 pass@1 有什么区别？']:
        response = client.post('/api/papers/'+imported['id']+'/explain',json={
            'conversation_id':conversation['id'],'page':1,'chunk_id':'metrics-0','selected_text':selection,'question':question})
        assert response.status_code==200,response.text
        assert response.json()['conversation_id']==conversation['id']
        assert response.json()['visual_used'] is remote
        assert response.json()['citations']
    saved = client.get('/api/conversations/'+conversation['id']).json()
    assert saved['context']['visual'] is False
    assert saved['context']['selected_text']==selection
    assert [turn['status'] for turn in saved['turns']]==['completed','completed']
    if remote:
        assert len(calls)==2
        assert '∑' in calls[0][0]
        assert {chunk.id for chunk in calls[0][1]} >= {chunk.id for chunk in paper.chunks}
        assert calls[0][2].startswith('data:image/png;base64,')
    else:
        for citation in response.json()['citations']:
            source = next(chunk for chunk in paper.chunks if chunk.id==citation['chunk_id'])
            assert citation['source_text'] in source.content


def test_glyph_recovery_reads_the_pdf_encoding_and_matches_the_exact_block(tmp_path):
    from app.services.selection_source import pdf_comparison_views
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72,100),'NX')
    font_xref = page.get_fonts()[0][0]
    document.xref_set_key(font_xref,'BaseFont','/ABCDEF+LMMathExtension10-Regular')
    document.xref_set_key(font_xref,'Encoding','<</Differences [88 /summationdisplay]>>')
    path = tmp_path/'glyph.pdf'
    document.save(path)
    document.close()
    with fitz.open(path) as document:
        block = next(b for b in document[0].get_text('dict')['blocks'] if b['type']==0)
        raw = '\n'.join(''.join(s['text'] for s in line['spans']) for line in block['lines'])
    chunk = PaperChunk(id='glyph',paper_id='p',page=1,content=raw,bbox_json=json.dumps(block['bbox']))
    wrong_location = PaperChunk(id='elsewhere',paper_id='p',page=1,content=raw,bbox_json='[10,10,30,30]')
    paper = Paper(id='p',title='Glyph',pdf_path=str(path),chunks=[chunk,wrong_location])
    repaired = pdf_comparison_views(paper,{1})
    assert repaired['glyph'].endswith('∑')
    assert 'elsewhere' not in repaired


def test_plain_x_in_normal_font_is_not_a_summation(tmp_path):
    from app.services.selection_source import pdf_comparison_views
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72,100),'NX')
    block = page.get_text('dict')['blocks'][0]
    path = tmp_path/'letter.pdf'
    document.save(path)
    document.close()
    paper = Paper(id='p',title='Letters',pdf_path=str(path),chunks=[PaperChunk(
        id='letter',paper_id='p',page=1,content='NX',bbox_json=json.dumps(block['bbox']))])
    assert pdf_comparison_views(paper,{1})=={}
