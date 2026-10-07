from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.models import Paper
from app.services.pdf import parse_pdf
from test_workflow import pdf_bytes


def imported_paper(client: TestClient) -> dict:
    response = client.post('/api/papers/import', files={'file': ('local.pdf', pdf_bytes('Local Paper\nAbstract\nWe report actual source evidence in a scientific paper.\n3 Method\nWe use a locally verifiable method.'))})
    assert response.status_code == 201, response.text
    return response.json()


def test_metadata_patch_records_manual_provenance_and_ordered_authors(client: TestClient) -> None:
    paper = imported_paper(client)
    corrected = client.patch(f"/api/papers/{paper['id']}", json={'title': 'Corrected Research Title', 'authors': ['Second Surname', 'First Surname'], 'year': 2017, 'venue': 'Recorded Conference', 'doi': '10.1234/real-id', 'arxiv_id': '1706.03762'})
    assert corrected.status_code == 200, corrected.text
    result = corrected.json()
    assert result['title'] == 'Corrected Research Title'
    assert result['authors'] == ['Second Surname', 'First Surname']
    assert result['year'] == 2017
    assert result['metadata_sources'] == {field: 'manual' for field in ('title', 'authors', 'year', 'venue', 'doi', 'arxiv_id')}
    detail = client.get(f"/api/papers/{paper['id']}").json()
    assert detail['analysis']['card']['title'] == 'Corrected Research Title'
    assert detail['chunks'] == paper['chunks']
    assert detail['evidence'] == paper['evidence']
    with client.app.state.database.sessions() as session:
        stored = session.get(Paper, paper['id'])
        assert json.loads(stored.analysis.card_json)['title'] == 'Corrected Research Title'


def test_refresh_preserves_manual_fields_and_research_data(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = imported_paper(client)
    path = f"/api/papers/{paper['id']}"
    client.patch(path, json={'title': 'My exact manual title', 'authors': ['My corrected author'], 'year': None, 'is_favorite': True, 'reading_status': 'reading', 'tags': ['personal']})
    note = client.post(path + '/notes', json={'content': 'A research thought', 'page': 1}).json()
    collection = client.post('/api/collections', json={'name': 'Research collection'}).json()
    client.put(f"/api/collections/{collection['id']}/papers/{paper['id']}")
    before = client.get(path).json()
    refreshed = client.post(path + '/refresh-metadata')
    assert refreshed.status_code == 200, refreshed.text
    after = refreshed.json()
    assert after['id'] == paper['id']
    assert after['title'] == 'My exact manual title'
    assert after['authors'] == ['My corrected author']
    assert after['year'] is None
    assert after['metadata_sources']['year'] == 'manual'
    assert after['reading_status'] == 'reading'
    assert after['is_favorite'] is True
    assert after['collection_ids'] == [collection['id']]
    assert after['tags'] == ['personal']
    assert after['notes'] == [note]
    assert after['chunks'] == before['chunks']
    assert after['evidence'] == before['evidence']


def test_local_identifier_import_enriches_from_authority_and_outage_keeps_pdf(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.metadata import MetadataResult

    content = pdf_bytes('Locally Extracted Title\nAbstract\nAn original evidence passage.')
    parsed = replace(parse_pdf(content), arxiv_id='1706.03762', year=2023, metadata_sources={'title': 'pdf_layout', 'year': 'pdf_text', 'arxiv_id': 'pdf_text'})
    monkeypatch.setattr('app.services.importing.parse_pdf', lambda _: parsed)
    def enrich(**kwargs):
        assert kwargs['arxiv_id'] == '1706.03762'
        return MetadataResult({'title': 'Authority Title', 'authors': ['Author Two', 'Author One'], 'year': 2017, 'arxiv_id': '1706.03762'}, {field: 'arxiv' for field in ('title', 'authors', 'year', 'arxiv_id')}, [])
    monkeypatch.setattr('app.services.importing.enrich_metadata', enrich)
    response = client.post('/api/papers/import', files={'file': ('known.pdf', content)})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['title'] == 'Authority Title'
    assert result['authors'] == ['Author Two', 'Author One']
    assert result['year'] == 2017
    assert result['metadata_sources']['year'] == 'arxiv'
    assert result['analysis']['provider'] == 'MockProvider'
    assert result['source_url'] is None
    assert client.get(f"/api/papers/{result['id']}/pdf").content == content
    monkeypatch.setattr('app.services.importing.enrich_metadata', lambda **kwargs: MetadataResult({}, {}, ['arXiv 元数据服务暂不可用，已保留 PDF 中的识别结果']))
    content2 = pdf_bytes('A different source PDF')
    response2 = client.post('/api/papers/import', files={'file': ('outage.pdf', content2)})
    assert response2.status_code == 201
    assert response2.json()['title'] == 'Locally Extracted Title'
    assert response2.json()['metadata_warnings']
    assert response2.json()['pdf_available'] is True


def test_url_import_uses_validated_download_and_rejects_duplicate(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.downloads import DownloadedPDF
    from app.services.metadata import MetadataResult

    content = pdf_bytes('A URL Imported Paper\nAbstract\nAn actual source paragraph from a public link.')
    link = 'https://arxiv.org/abs/1706.03762'
    monkeypatch.setattr('app.api.papers.download_pdf', lambda url: DownloadedPDF(content, '1706.03762.pdf', link, 'https://arxiv.org/pdf/1706.03762', '1706.03762'))
    monkeypatch.setattr('app.services.importing.enrich_metadata', lambda **kwargs: MetadataResult({'title': 'Recorded Public Paper', 'year': 2017}, {'title': 'arxiv', 'year': 'arxiv'}, []))
    imported = client.post('/api/papers/import-url', json={'url': link})
    assert imported.status_code == 201, imported.text
    paper = imported.json()
    assert paper['source_url'] == link
    assert paper['arxiv_id'] == '1706.03762'
    assert paper['title'] == 'Recorded Public Paper'
    assert paper['analysis']['provider'] == 'MockProvider'
    assert client.get(f"/api/papers/{paper['id']}/pdf").content == content
    assert client.post('/api/papers/import-url', json={'url': link}).status_code == 409


def test_refresh_only_updates_sections_of_matching_original_chunks(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = imported_paper(client)
    path = f"/api/papers/{paper['id']}"
    with client.app.state.database.sessions() as session:
        stored = session.get(Paper, paper['id'])
        stored.title = 'Wrong first line'
        original = parse_pdf(__import__('pathlib').Path(stored.pdf_path).read_bytes())
        session.commit()
    changed_blocks = [replace(block, section='3 Corrected Method') for block in original.blocks]
    changed_blocks.append(replace(original.blocks[0], content='Unmatched invented replacement'))
    parsed = replace(original, title='Correctly detected title', blocks=changed_blocks)
    monkeypatch.setattr('app.services.importing.parse_pdf', lambda _: parsed)
    response = client.post(path + '/refresh-metadata')
    assert response.status_code == 200, response.text
    after = response.json()
    assert after['title'] == 'Correctly detected title'
    assert [c['id'] for c in after['chunks']] == [c['id'] for c in paper['chunks']]
    assert [c['content'] for c in after['chunks']] == [c['content'] for c in paper['chunks']]
    assert [c['bbox'] for c in after['chunks']] == [c['bbox'] for c in paper['chunks']]
    assert all(c['section'] == '3 Corrected Method' for c in after['chunks'])
    assert [e['id'] for e in after['evidence']] == [e['id'] for e in paper['evidence']]


@pytest.mark.parametrize('payload', [{'title': '   '}, {'title': None}, {'year': 1200}, {'authors': ['   ']}, {'doi': 'not-a-doi'}, {'arxiv_id': 'not-an-id'}])
def test_invalid_manual_metadata_is_rejected(client: TestClient, payload: dict) -> None:
    paper = imported_paper(client)
    response = client.patch(f"/api/papers/{paper['id']}", json=payload)
    assert response.status_code == 422


def test_doi_conflict_is_useful_and_does_not_change_existing_metadata(client: TestClient) -> None:
    first = client.post('/api/papers', json={'title': 'Original', 'doi': '10.1234/unique'}).json()
    second = client.post('/api/papers', json={'title': 'Second'}).json()
    conflict = client.patch(f"/api/papers/{second['id']}", json={'title': 'Do not save', 'doi': first['doi']})
    assert conflict.status_code == 409
    assert isinstance(conflict.json()['detail'], str)
    assert client.get(f"/api/papers/{second['id']}").json()['title'] == 'Second'


def test_distinct_pdf_with_registered_doi_is_rejected_as_duplicate(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.metadata import MetadataResult

    client.post('/api/papers', json={'title': 'Registered prior version', 'doi': '10.1234/same-work'})
    content = pdf_bytes('A distinct PDF version of an already registered DOI')
    parsed = replace(parse_pdf(content), doi='10.1234/same-work', metadata_sources={'doi': 'pdf_text'})
    monkeypatch.setattr('app.services.importing.parse_pdf', lambda _: parsed)
    monkeypatch.setattr('app.services.importing.enrich_metadata', lambda **kwargs: MetadataResult())
    response = client.post('/api/papers/import', files={'file': ('version.pdf', content)})
    assert response.status_code == 409
    assert client.get('/api/papers').json()['total'] == 1


def split_parser_fixture(client: TestClient, monkeypatch: pytest.MonkeyPatch, *, ambiguous: bool = False) -> tuple[dict, str]:
    import pymupdf as fitz
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((70, 80), 'Paper With Split Headings', fontsize=18, fontname='hebo')
        page.insert_text((70, 160), 'Abstract', fontsize=12, fontname='hebo')
        page.insert_text((70, 185), 'We describe verifiable observations.', fontsize=10)
        for number, heading, body, y in [('3', 'Model Architecture', 'Our method selects real source passages.', 260), ('4', 'Results', 'Our measured result is 71 of 100.', 360)]:
            page.insert_text((70, y), number, fontsize=12, fontname='hebo')
            page.insert_text((90, y), heading, fontsize=12, fontname='hebo')
            page.insert_text((70, y + 25), body, fontsize=10)
        content = document.tobytes()
    current = parse_pdf(content)
    fragments = [block for block in current.blocks if block.section and ('Architecture' in block.section or (ambiguous and 'Results' in block.section))]
    assert len(fragments) >= 2, 'Use genuinely changed heading/body boundaries'
    bounds = (min(b.bbox[0] for b in fragments), min(b.bbox[1] for b in fragments), max(b.bbox[2] for b in fragments), max(b.bbox[3] for b in fragments))
    merged = replace(fragments[0], section=None, content='\n'.join(b.content for b in fragments), bbox=bounds)
    legacy = replace(current, blocks=[b for b in current.blocks if b not in fragments] + [merged])
    monkeypatch.setattr('app.services.importing.parse_pdf', lambda _: legacy)
    response = client.post('/api/papers/import', files={'file': ('legacy.pdf', content)})
    assert response.status_code == 201, response.text
    paper = response.json()
    old_chunk = next(chunk for chunk in paper['chunks'] if chunk['content'] == merged.content)
    monkeypatch.setattr('app.services.importing.parse_pdf', lambda _: current)
    return paper, old_chunk['id']


def test_refresh_recovers_section_from_identical_text_with_new_split_boundaries(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    paper, chunk_id = split_parser_fixture(client, monkeypatch)
    response = client.post(f"/api/papers/{paper['id']}/refresh-metadata")
    assert response.status_code == 200, response.text
    after = response.json()
    previous = next(c for c in paper['chunks'] if c['id'] == chunk_id)
    recovered = next(c for c in after['chunks'] if c['id'] == chunk_id)
    assert recovered['section'] == '3 Model Architecture'
    assert recovered['content'] == previous['content']
    assert recovered['bbox'] == previous['bbox']
    assert [c['id'] for c in after['chunks']] == [c['id'] for c in paper['chunks']]
    assert [e['id'] for e in after['evidence']] == [e['id'] for e in paper['evidence']]
    assert all(e['section'] == recovered['section'] for e in after['evidence'] if e['chunk_id'] == chunk_id)


def test_refresh_keeps_ambiguous_multi_section_chunk_and_warns(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    paper, chunk_id = split_parser_fixture(client, monkeypatch, ambiguous=True)
    response = client.post(f"/api/papers/{paper['id']}/refresh-metadata")
    assert response.status_code == 200, response.text
    after = response.json()
    recovered = next(c for c in after['chunks'] if c['id'] == chunk_id)
    assert recovered['section'] is None
    assert after['metadata_warnings']
