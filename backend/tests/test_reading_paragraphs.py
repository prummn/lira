"""Reading paragraphs preserve source identity while leaving evidence chunks intact."""
import json

import pytest
from fastapi.testclient import TestClient

from test_remote_provider import import_fixture
from test_translation_cache import remote_provider


def test_reading_paragraphs_exclude_headings_and_keep_pdf_anchors(client: TestClient):
    paper = import_fixture(client)
    response = client.get(f"/api/papers/{paper['id']}/reading-paragraphs")
    assert response.status_code == 200
    paragraphs = response.json()['paragraphs']
    assert paragraphs
    assert all(item['text'].strip().lower() not in {'abstract', 'method', 'limitations'} for item in paragraphs)
    assert all(item['anchors'][0]['bbox'] for item in paragraphs)
    assert {chunk['id'] for chunk in paper['chunks']} == {
        chunk['id'] for chunk in client.get(f"/api/papers/{paper['id']}").json()['chunks']
    }


def test_paragraph_translation_uses_the_exact_derived_source_and_offline_cache(client: TestClient, monkeypatch):
    paper = import_fixture(client)
    reading = client.get(f"/api/papers/{paper['id']}/reading-paragraphs")
    assert reading.status_code == 200
    paragraph = reading.json()['paragraphs'][0]
    calls = []
    provider = remote_provider(calls, text=r'注意力为 $QK^T$。')
    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: provider)
    path = f"/api/papers/{paper['id']}/translate"
    first = client.post(path, json={'paragraph_id': paragraph['id']})
    assert first.status_code == 200
    assert first.json()['paragraph_id'] == paragraph['id']
    assert first.json()['source_text'] == paragraph['source_text']
    assert first.json()['cached'] is False
    again = client.post(path, json={'paragraph_id': paragraph['id']})
    assert again.status_code == 200 and again.json()['cached'] is True
    from app.providers.mock import MockProvider
    monkeypatch.setattr('app.api.papers.get_model_provider', MockProvider)
    offline = client.get(f"/api/papers/{paper['id']}/reading-paragraphs").json()
    assert offline['translations'][paragraph['id']]['text'] == r'注意力为 $QK^T$。'
    assert len(calls) == 1
    assert client.post(path, json={'paragraph_id': 'invented'}).status_code == 404


def test_paragraphs_join_cross_page_sentence_but_keep_new_paragraphs_separate():
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs
    def chunk(index, page, text, y):
        return PaperChunk(id=str(index), paper_id='p', page=page, content=text,
                          section='Attention', bbox_json=json.dumps([50, y, 500, y + 35]),
                          page_width=600, page_height=800)
    chunks = [chunk(0, 1, 'An attention function maps a query to an output. The output is computed as a weighted sum', 700),
              chunk(1, 2, 'of values, where the weight is computed by a compatibility function.', 60),
              chunk(2, 2, 'We call this scaled dot-product attention.', 130)]
    paragraphs = build_reading_paragraphs(chunks)
    assert len(paragraphs) == 2
    assert paragraphs[0]['text'].endswith('compatibility function.')
    assert [a['page'] for a in paragraphs[0]['anchors']] == [1, 2]
    assert paragraphs[1]['text'].startswith('We call this')


def test_indentation_splits_a_pdf_block_into_natural_paragraphs(tmp_path):
    import pymupdf as fitz
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs
    pdf = tmp_path / 'indented.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=800)
        for x, y, text in [(60, 100, 'This is the first sentence.'), (50, 113, 'This continues the first paragraph.'),
                           (60, 126, 'A new paragraph starts with indentation.'), (50, 139, 'Its second line remains together.')]:
            page.insert_text((x, y), text, fontsize=10)
        doc.save(pdf)
    source = 'This is the first sentence.\nThis continues the first paragraph.\nA new paragraph starts with indentation.\nIts second line remains together.'
    chunk = PaperChunk(id='source', paper_id='p', page=1, section='Method', content=source,
                      bbox_json=json.dumps([50, 80, 500, 150]), page_width=600, page_height=800)
    paragraphs = build_reading_paragraphs([chunk], pdf)
    assert len(paragraphs) == 2
    assert paragraphs[0]['text'] == 'This is the first sentence. This continues the first paragraph.'
    assert paragraphs[1]['text'].startswith('A new paragraph')
    assert paragraphs[0]['anchors'][0]['bbox'][1] < paragraphs[1]['anchors'][0]['bbox'][1]
    assert paragraphs[0]['refs'][0]['end'] < paragraphs[1]['refs'][0]['start']


def test_cross_page_sentence_can_continue_after_a_figure_caption():
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs
    def chunk(index, page, text, bounds):
        return PaperChunk(id=str(index), paper_id='p', page=page, section='Attention', content=text,
                          bbox_json=json.dumps(bounds), page_width=600, page_height=800)
    chunks = [chunk(0, 1, 'The output is computed as a weighted sum', [50,700,500,735]),
              chunk(1, 2, 'Figure 2: Several attention layers running in parallel.', [50,280,500,300]),
              chunk(2, 2, 'of the values, using a compatibility function of the query and key.', [50,330,500,365])]
    paragraphs = build_reading_paragraphs(chunks)
    assert len(paragraphs) == 2
    assert paragraphs[0]['text'].endswith('query and key.')
    assert paragraphs[1]['kind'] == 'caption'


def test_abstract_with_pass_at_metric_is_kept_as_one_reading_paragraph():
    """Metrics such as pass@1 are prose, not email/layout noise."""
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs

    chunk = PaperChunk(
        id='abstract-pass-at-one', paper_id='p', page=1, section='Abstract',
        content=(
            'We introduce Reflexion, a framework for language agents. '
            'It reaches 91% pass@1 accuracy on HumanEval and improves coding results.'
        ),
        bbox_json=json.dumps([50, 100, 550, 140]), page_width=600, page_height=800,
    )

    paragraphs = build_reading_paragraphs([chunk])

    assert len(paragraphs) == 1
    assert paragraphs[0]['section'] == 'Abstract'
    assert 'pass@1' in paragraphs[0]['text']


def test_inline_formula_fragments_stay_in_the_self_reflection_paragraph():
    """Overlapping PDF text blocks at a wrapped formula do not split prose."""
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs

    def chunk(index, text, bounds):
        return PaperChunk(
            id=str(index), paper_id='p', page=4,
            section='3 Reflexion: reinforcement via verbal reflection',
            content=text, bbox_json=json.dumps(bounds),
            page_width=612, page_height=792,
        )

    chunks = [
        chunk('base', 'Self-reflection\nThe model stores an experience and should have taken action a��', [108, 554, 505, 641]),
        chunk('inline-1', 'i, which would have resulted in a��', [358, 629, 493, 643]),
        chunk('inline-2', 'i+1\nand a��', [108, 635, 504, 653]),
        chunk('inline-3', 'i+2, and store this experience in its memory', [108, 643, 504, 665]),
        chunk('tail', 'i. This iterative process improves the agent.', [108, 655, 504, 687]),
    ]

    paragraphs = build_reading_paragraphs(chunks)

    prose = [item for item in paragraphs if item['kind'] == 'prose']
    assert len(prose) == 1
    assert 'i, which would have resulted' in prose[0]['text']
    assert prose[0]['text'].endswith('agent.')


def test_radical_and_midline_capital_continuation_stay_in_the_same_real_paragraph(monkeypatch):
    """DeepSWE 5.5: a raised radical is emitted before its containing paragraph."""
    from pathlib import Path
    from app.models import PaperChunk
    from app.services.pdf_metadata import LayoutLine
    from app.services.reading_paragraphs import build_reading_paragraphs

    fixture = json.loads((Path(__file__).parent / 'fixtures/deepswe_uncertainty_layout.json').read_text(encoding='utf-8'))
    lines = [LayoutLine(key=tuple(row['key']), text=row['text'], bbox=tuple(row['bbox']),
                        size=row['size'], bold=row['bold'], horizontal=row['horizontal'], spans=[])
             for row in fixture['lines']]
    ranks = {row['key'][1]: row['rank'] for row in fixture['lines']}
    monkeypatch.setattr('app.services.reading_paragraphs._read_layout', lambda path: ({12: lines}, {12: ranks}))
    chunks = [PaperChunk(id=row['id'], paper_id='p', page=row['page'], section=row['section'],
                         content=row['content'], bbox_json=json.dumps(row['bbox']), page_width=612, page_height=792)
              for row in fixture['chunks']]
    snapshots = [chunk.content for chunk in chunks]
    paragraphs = build_reading_paragraphs(chunks)

    assert len(paragraphs) == 2
    first, following = paragraphs
    assert first['text'].startswith('Running every task')
    assert 'std(s1, . . . , sR)/ √ R. This convention follows' in first['text']
    assert first['text'].endswith('not statistically separated.')
    assert following['text'].startswith('This interval captures only one source of noise:')
    assert [ref['chunk_id'] for ref in first['refs']] == ['uncertainty-2', 'uncertainty-1', 'uncertainty-3']
    assert [chunk.content for chunk in chunks] == snapshots
    sources = {chunk.id: chunk.content for chunk in chunks}
    assert first['source_text'] == '\n'.join(sources[ref['chunk_id']][ref['start']:ref['end']] for ref in first['refs'])


def test_sentence_can_continue_after_an_inline_figure_caption():
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs
    def chunk(index, text, bounds):
        return PaperChunk(id=str(index), paper_id='p', page=1, section='Results', content=text,
                          bbox_json=json.dumps(bounds), page_width=600, page_height=800)
    chunks = [
        chunk(0, 'The model predicts a calibrated score', [50, 100, 500, 125]),
        chunk(1, 'Figure 3: Calibration curves for all datasets.', [50, 150, 500, 175]),
        chunk(2, 'using a held-out validation set.', [50, 190, 500, 215]),
    ]
    paragraphs = build_reading_paragraphs(chunks)
    prose = [item for item in paragraphs if item['kind'] == 'prose']
    assert len(prose) == 1
    assert prose[0]['text'].endswith('held-out validation set.')
    assert any(item['kind'] == 'caption' for item in paragraphs)


def test_cross_page_sentence_survives_running_header_table_and_footnote_artifacts():
    """ReAct 3.2 resumes below a figure/table on the next page.

    The PDF text extractor emits the running header, table rows, captions and
    footnotes as independent blocks between the two prose fragments.  Those
    blocks must not become the previous paragraph or prevent the page-boundary
    continuation from being recognized.
    """
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs

    def chunk(index, page, text, bounds):
        return PaperChunk(id=str(index), paper_id='p', page=page, section='ReAct Prompting', content=text,
                          bbox_json=json.dumps(bounds), page_width=612, page_height=792)

    chunks = [
        chunk(0, 4, 'ReAct Prompting\nFor HotpotQA and Fever, we randomly select cases and guide', [108, 632, 506, 711]),
        chunk(1, 5, 'Published as a conference paper at ICLR 2023', [108, 28, 293, 38]),
        chunk(2, 5, 'Prompt Methoda\nHotpotQA\nFever', [113, 85, 269, 103]),
        chunk(3, 5, 'Standard\n28.7\n57.1\nReAct\n27.4\n60.9', [113, 107, 267, 175]),
        chunk(4, 5, 'Table 1: PaLM-540B prompting results on HotpotQA and Fever.', [108, 204, 274, 225]),
        chunk(5, 5, 'aHotpotQA EM is 27.1, 28.9, 33.8 for Standard, CoT.', [108, 233, 275, 250]),
        chunk(6, 5, 'b(Zhu et al., 2021; Lewis et al., 2020)', [121, 250, 211, 260]),
        chunk(7, 5, 'search reformulation (maybe I can search x instead), and synthesize the final answer.', [108, 275, 504, 296]),
    ]

    paragraphs = build_reading_paragraphs(chunks)
    prose = [item for item in paragraphs if item['kind'] == 'prose']
    assert len(prose) == 1
    assert prose[0]['text'].startswith('ReAct Prompting For HotpotQA')
    assert prose[0]['text'].endswith('synthesize the final answer.')
    assert [anchor['page'] for anchor in prose[0]['anchors']] == [4, 5]
    assert all(artifact.content not in prose[0]['source_text'] for artifact in chunks[1:-1])


def test_short_formula_fragments_remain_with_the_paragraph_that_introduces_them():
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs
    def chunk(index, text, bounds):
        return PaperChunk(id=str(index), paper_id='p', page=1, section='Attention', content=text,
                          bbox_json=json.dumps(bounds), page_width=600, page_height=800)
    chunks = [chunk(0, 'We compute the matrix of outputs as:', [50,100,500,125]),
              chunk(1, 'Attention(Q, K, V) = softmax(QKT', [120,145,350,163]),
              chunk(2, ')V\n(1)', [355,153,500,165]),
              chunk(3, '√dk', [310,155,340,175]),
              chunk(4, 'The next paragraph explains computational complexity.', [50,195,500,230])]
    paragraphs = build_reading_paragraphs(chunks)
    assert len(paragraphs) == 2
    assert all(fragment.content in paragraphs[0]['source_text'] for fragment in chunks[:4])
    assert {ref['chunk_id'] for ref in paragraphs[0]['refs']} == {'0','1','2','3'}
    assert paragraphs[1]['text'].startswith('The next paragraph')


def test_overlapping_pdf_math_blocks_keep_their_original_reading_position(tmp_path):
    import pymupdf as fitz
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs
    pdf = tmp_path / 'overlapping.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=800)
        page.insert_text((50,100), 'The parameter matrices have dimensions',fontsize=10)
        page.insert_text((310,100), 'R = 64',fontsize=10)
        page.insert_text((50,115), 'and the output projection is shared.',fontsize=10)
        page.insert_text((50,190), 'This later paragraph describes a different topic.',fontsize=10)
        doc.save(pdf)
    def chunk(index, text, bounds):
        return PaperChunk(id=str(index), paper_id='p', page=1, section='Method', content=text,
                          bbox_json=json.dumps(bounds), page_width=600, page_height=800)
    # Wide source bounds overlap another block but the exact block text still matches.
    chunks = [chunk(0,'The parameter matrices have dimensions',[50,89,225,103]),
              chunk(1,'R = 64\nand the output projection is shared.',[50,89,345,118]),
              chunk(2,'This later paragraph describes a different topic.',[50,179,265,194])]
    paragraphs=build_reading_paragraphs(chunks,pdf)
    source='\n'.join(paragraph['source_text'] for paragraph in paragraphs)
    assert source.index('R = 64') < source.index('This later paragraph')
    assert all(chunk.content in source for chunk in chunks)


def test_inline_math_fragments_follow_the_visual_left_to_right_order(tmp_path):
    import pymupdf as fitz
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs
    pdf = tmp_path / 'inline-math.pdf'
    with fitz.open() as doc:
        page=doc.new_page(width=600,height=800)
        for x,y,text in [(50,100,'Where the projection parameter matrices are WQ'),
                          (330,100,'=64, WV'),(280,100,'=64, WK'),(385,100,'=32'),
                          (50,115,'and WO is the final output projection.')]:
            page.insert_text((x,y),text,fontsize=10)
        doc.save(pdf)
    def chunk(index,text,bounds):
        return PaperChunk(id=str(index),paper_id='p',page=1,section='Method',content=text,
                          bbox_json=json.dumps(bounds),page_width=600,page_height=800)
    chunks=[chunk(0,'Where the projection parameter matrices are WQ',[50,89,275,103]),
            chunk(1,'=64, WV',[330,89,370,103]),
            chunk(2,'=64, WK',[280,89,320,103]),
            chunk(3,'=32\nand WO is the final output projection.',[50,89,420,118])]
    paragraphs=build_reading_paragraphs(chunks,pdf)
    assert len(paragraphs)==1
    assert paragraphs[0]['source_text'].index('WK') < paragraphs[0]['source_text'].index('WV')
    assert all(chunk.content in paragraphs[0]['source_text'] for chunk in chunks)


def test_math_in_another_column_is_not_attached_to_unrelated_prose():
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs
    chunks=[PaperChunk(id='left',paper_id='p',page=2,section='Method',
                      content='This is an unrelated sentence in the left column.',
                      bbox_json=json.dumps([50,100,270,114]),page_width=600,page_height=800),
            PaperChunk(id='right',paper_id='p',page=2,section='Method',content='R = 64',
                      bbox_json=json.dumps([330,100,550,114]),page_width=600,page_height=800)]
    assert len(build_reading_paragraphs(chunks))==2


def test_adjacent_diagram_labels_do_not_use_the_inline_math_join(tmp_path):
    from app.services.reading_paragraphs import build_reading_paragraphs
    chunks, pdf = _layout_fixture(tmp_path, [
        (1, [(50,100,'Input records remain available to the retrieval module')]),
        (1, [(272,100,'Output'), (50,111,'The labels refer to separate nodes in this diagram.')]),
    ])
    assert len(build_reading_paragraphs(chunks, pdf)) == 2


def _layout_fixture(tmp_path, groups):
    """Exact source blocks with realistic indentation and two-column geometry."""
    import pymupdf as fitz
    from app.models import PaperChunk
    pdf = tmp_path / 'column-flow.pdf'
    chunks = []
    with fitz.open() as doc:
        for number in range(max(group[0] for group in groups)):
            doc.new_page(width=612, height=792)
        for index, (number, rows) in enumerate(groups):
            page = doc[number - 1]
            for x, y, text in rows:
                page.insert_text((x, y), text, fontsize=9)
            # Text line bounds use the actual font metrics, never guessed offsets.
            boxes = [page.search_for(text)[-1] for _, _, text in rows]
            chunks.append(PaperChunk(id=f'layout-{index}', paper_id='p', page=number,
                section='1 Introduction', content='\n'.join(text for _, _, text in rows),
                bbox_json=json.dumps([min(b.x0 for b in boxes),min(b.y0 for b in boxes),max(b.x1 for b in boxes),max(b.y1 for b in boxes)]),
                page_width=612, page_height=792))
        doc.save(pdf)
    return chunks, pdf


def test_paragraph_continues_from_left_column_bottom_to_right_column_top(tmp_path):
    from app.services.reading_paragraphs import build_reading_paragraphs
    chunks, pdf = _layout_fixture(tmp_path, [
        (1, [(64,680,'In this paper, we introduce agents that draw on'),
             (54,691,'generative models to simulate believable behavior and')]),
        (1, [(318,100,'demonstrate that they produce believable human behavior.'),
             (318,111,'Their memories inform the actions they take every day.')]),
        (1, [(328,140,'A different paragraph begins with an indented first line.'),
             (318,151,'It must stay separate from the preceding paragraph.')]),
    ])
    paragraphs = build_reading_paragraphs(chunks, pdf)
    assert len(paragraphs) == 2
    assert 'behavior and demonstrate' in paragraphs[0]['text']
    assert [ref['chunk_id'] for ref in paragraphs[0]['refs']] == ['layout-0','layout-1']
    assert paragraphs[1]['text'].startswith('A different paragraph')


def test_sentence_final_footnote_does_not_split_an_unindented_continuation(tmp_path):
    from app.services.reading_paragraphs import build_reading_paragraphs
    chunks, pdf = _layout_fixture(tmp_path, [
        (1, [(328,410,'This architecture suggests applications in many domains.'),
             (318,421,'We focus on a society inspired by games such as The Sims.2')]),
        (1, [(318,432,'By connecting our architecture to a language model,'),
             (318,443,'we manifest a society of twenty-five agents in a game.')]),
        (1, [(328,465,'We conducted two evaluations of the resulting agents.'),
             (318,476,'This really is the start of a different paragraph.')]),
    ])
    paragraphs = build_reading_paragraphs(chunks, pdf)
    assert len(paragraphs) == 3
    assert paragraphs[0]['text'].endswith('The Sims.2')
    assert paragraphs[1]['text'].startswith('By connecting')
    assert paragraphs[2]['text'].startswith('We conducted')


def test_paragraph_continues_from_right_column_to_next_page_left_column(tmp_path):
    from app.services.reading_paragraphs import build_reading_paragraphs
    chunks, pdf = _layout_fixture(tmp_path, [
        (1, [(328,650,'The agents spread the word about the party and then'),
             (318,661,'coordinate their plans so that they can all')]),
        (2, [(54,100,'show up, with one agent even asking another on a date.'),
             (54,111,'All this emerges from a single seed suggestion.')]),
    ])
    paragraphs = build_reading_paragraphs(chunks, pdf)
    assert len(paragraphs) == 1
    assert [a['page'] for a in paragraphs[0]['anchors']] == [1,2]


def test_inline_caption_does_not_break_a_capitalized_sentence_fragment(tmp_path):
    from app.services.reading_paragraphs import build_reading_paragraphs
    chunks, pdf = _layout_fixture(tmp_path, [
        (1, [(64,100,'The evaluated agents perform well on'),
             (54,111,'a range of tasks, including')]),
        (1, [(54,220,'Figure 2: Performance on all evaluated tasks.')]),
        (1, [(54,270,'HotpotQA and other benchmarks of factual reasoning.'),
             (54,281,'The model can use observations to improve its answer.')]),
    ])
    paragraphs = build_reading_paragraphs(chunks, pdf)
    prose = [p for p in paragraphs if p['kind'] == 'prose']
    assert len(prose) == 1
    assert 'including HotpotQA' in prose[0]['text']
    assert 'Figure 2' not in prose[0]['text']


def test_unfinished_text_in_adjacent_columns_on_the_same_row_does_not_merge():
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs
    chunks = [PaperChunk(id='col-left',paper_id='p',page=1,section='Intro',
        content='A left-column fragment with an unfinished thought',bbox_json=json.dumps([54,100,290,140]),page_width=612,page_height=792),
        PaperChunk(id='col-right',paper_id='p',page=1,section='Intro',
        content='another independent fragment in the right column.',bbox_json=json.dumps([318,100,560,140]),page_width=612,page_height=792)]
    assert len(build_reading_paragraphs(chunks)) == 2


def test_column_rollover_keeps_following_unindented_sentences_in_the_same_paragraph(tmp_path):
    from app.services.reading_paragraphs import build_reading_paragraphs
    chunks,pdf = _layout_fixture(tmp_path,[
        (1,[(64,680,'In this paper, we introduce an architecture'),(54,691,'that remembers experiences and')]),
        (1,[(318,100,'demonstrates believable behavior in an open world.'),(318,111,'The agents can stop to talk to one another.1')]),
        (1,[(318,122,'A society full of agents has emergent social dynamics.'),(318,133,'Information diffuses and coordination arises.')]),
        (1,[(328,155,'To enable these agents, we describe their architecture.'),(318,166,'This is a genuinely different paragraph.')]),
    ])
    paragraphs=build_reading_paragraphs(chunks,pdf)
    assert len(paragraphs)==3
    assert paragraphs[0]['text'].endswith('one another.1')
    assert paragraphs[1]['text'].startswith('A society')
    assert len(paragraphs[0]['refs'])==2
    assert paragraphs[2]['text'].startswith('To enable')


def test_abstract_continues_in_an_unlabelled_adjacent_column(tmp_path):
    from app.services.reading_paragraphs import build_reading_paragraphs
    chunks,pdf = _layout_fixture(tmp_path,[
        (1,[(54,564,'Believable agents can empower interactive applications.'),(54,575,'Artists paint, while')]),
        (1,[(318,550,'authors write and remember their daily experiences.'),(318,561,'The agents make plans for the following day.')]),
    ])
    chunks[0].section='Abstract';chunks[1].section=None
    paragraphs=build_reading_paragraphs(chunks,pdf)
    assert len(paragraphs)==1
    assert paragraphs[0]['section']=='Abstract'
    assert 'while authors write' in paragraphs[0]['text']


@pytest.mark.parametrize('start',['mRNA expression','pH measurements','3D reconstruction'])
def test_scientific_prefixes_are_not_mistaken_for_footnote_markers(start):
    from app.models import PaperChunk
    from app.services.reading_paragraphs import build_reading_paragraphs
    text=start+' was evaluated across several different experimental conditions.'
    chunk=PaperChunk(id='scientific',paper_id='p',page=2,section='Results',content=text,
        bbox_json=json.dumps([54,100,290,130]),page_width=612,page_height=792)
    assert build_reading_paragraphs([chunk])[0]['text']==text
