from copy import deepcopy

import fitz
import pytest


@pytest.fixture
def annotated_paper(client):
    with fitz.open() as pdf:
        for title in ('Annotation reading first page', 'Annotation reading second page'):
            page = pdf.new_page(width=600, height=800)
            page.insert_text((50, 100), title)
        data = pdf.tobytes()
    response = client.post('/api/papers/import', files={'file': ('notes.pdf', data, 'application/pdf')})
    assert response.status_code == 201
    return response.json()


def source_note():
    return {'content': '需要核对实验设置', 'kind': 'note', 'source_text': 'first page second page',
        'page': 1, 'bbox': [50, 80, 300, 120], 'anchors': [
            {'page': 1, 'bbox': [50, 80, 300, 120], 'page_width': 600, 'page_height': 800,
             'rects': [[50, 80, 300, 95], [50, 105, 200, 120]]},
            {'page': 2, 'bbox': [50, 80, 260, 95], 'page_width': 600, 'page_height': 800,
             'rects': [[50, 80, 260, 95]]}]}


def test_note_line_regions_survive_reads_and_edits_without_losing_the_source(client, annotated_paper):
    url = f"/api/papers/{annotated_paper['id']}/notes"
    body = source_note()
    created = client.post(url, json=body)
    assert created.status_code == 201
    note = created.json()
    assert note['anchors'] == body['anchors']
    assert note['updated_at']
    edited = client.patch(url + '/' + note['id'], json={'content': '补充：实验只覆盖一个数据集', 'kind': 'question'})
    assert edited.status_code == 200
    assert edited.json()['id'] == note['id']
    assert edited.json()['anchors'] == body['anchors']
    assert edited.json()['source_text'] == body['source_text']
    assert edited.json()['created_at'] == note['created_at']
    assert edited.json()['updated_at'] >= note['updated_at']
    loaded = client.get(f"/api/papers/{annotated_paper['id']}").json()['notes'][0]
    assert loaded['content'] == '补充：实验只覆盖一个数据集'
    assert loaded['anchors'] == body['anchors']
    assert client.patch(url + '/' + note['id'], json={'content': '   '}).status_code == 422
    assert client.patch(url + '/' + note['id'], json={'source_text': 'replace quote'}).status_code == 422


@pytest.mark.parametrize('invalid', ['page', 'reversed', 'out-of-page', 'out-of-bbox', 'mismatched-page'])
def test_note_annotations_reject_invalid_geometry(client, annotated_paper, invalid):
    body = deepcopy(source_note())
    if invalid == 'page': body['anchors'][1]['page'] = 3
    if invalid == 'reversed': body['anchors'][0]['rects'][0] = [80, 90, 50, 100]
    if invalid == 'out-of-page': body['anchors'][0]['bbox'][2] = 650
    if invalid == 'out-of-bbox': body['anchors'][0]['rects'][0][2] = 500
    if invalid == 'mismatched-page': body['page'] = 2
    assert client.post(f"/api/papers/{annotated_paper['id']}/notes", json=body).status_code == 422


def test_note_edit_is_scoped_to_its_paper_and_legacy_notes_stay_usable(client, annotated_paper):
    url = f"/api/papers/{annotated_paper['id']}/notes"
    created = client.post(url, json={'content': 'legacy quote', 'kind': 'highlight', 'page': 1,
        'source_text': 'Annotation reading first page', 'bbox': [50, 80, 300, 120]}).json()
    assert created['anchors'] == []
    assert client.patch('/api/papers/missing/notes/' + created['id'], json={'content': 'wrong'}).status_code == 404
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 80), 'A separate paper for checking note ownership')
        other = client.post('/api/papers/import', files={'file': ('other.pdf', pdf.tobytes(), 'application/pdf')}).json()
    wrong_url = f"/api/papers/{other['id']}/notes/{created['id']}"
    assert client.patch(wrong_url, json={'content': 'wrong paper'}).status_code == 404
    assert client.delete(wrong_url).status_code == 404
    updated = client.patch(url + '/' + created['id'], json={'content': '自己的思考', 'kind': 'note'})
    assert updated.status_code == 200
    assert updated.json()['bbox'] == created['bbox']
    assert updated.json()['source_text'] == created['source_text']
