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
