import fitz
from fastapi.testclient import TestClient


def test_collection_fulltext_scope_is_applied_before_limit(client: TestClient) -> None:
    with fitz.open() as document:
        for _ in range(51):
            page = document.new_page()
            page.insert_text((50,50),'nebulaquery.')
        outside_bytes = document.tobytes()
    outside = client.post('/api/papers/import',files={'file':('outside.pdf',outside_bytes)})
    assert outside.status_code == 201
    with fitz.open() as document:
        page = document.new_page()
        paragraph = 'This inside collection paragraph includes nebulaquery. ' + 'Evidence context and original scientific source text are retained. '*10
        assert page.insert_textbox(fitz.Rect(50,50,540,760),paragraph,fontsize=10) >= 0
        inside_bytes = document.tobytes()
    inside = client.post('/api/papers/import',files={'file':('inside.pdf',inside_bytes)})
    assert inside.status_code == 201
    paper = inside.json()
    collection = client.post('/api/collections',json={'name':'Selected collection'}).json()
    client.put(f"/api/collections/{collection['id']}/papers/{paper['id']}")
    global_items = client.get('/api/search',params={'query':'nebulaquery','limit':50}).json()['items']
    assert len(global_items) == 50
    assert all(item['paper_id'] != paper['id'] for item in global_items)
    scoped = client.get('/api/search',params={'query':'nebulaquery','collection_id':collection['id'],'limit':50}).json()['items']
    assert len(scoped) == 1
    assert scoped[0]['paper_id'] == paper['id']
    assert scoped[0]['chunk_id'] == paper['chunks'][0]['id']


def test_fulltext_filters_reading_state_and_favorites(client: TestClient) -> None:
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50,50),'A scintillatingquokka evidence paragraph supports the local workflow.')
        data = document.tobytes()
    paper = client.post('/api/papers/import',files={'file':('filter.pdf',data)}).json()
    assert client.get('/api/search',params={'query':'scintillatingquokka','is_favorite':'true'}).json()['items'] == []
    client.patch(f"/api/papers/{paper['id']}",json={'is_favorite':True,'reading_status':'reading'})
    assert client.get('/api/search',params={'query':'scintillatingquokka','is_favorite':'true','reading_status':'reading'}).json()['items']
    assert client.get('/api/search',params={'query':'scintillatingquokka','reading_status':'read'}).json()['items'] == []
