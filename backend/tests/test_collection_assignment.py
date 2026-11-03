from fastapi.testclient import TestClient
import pytest

from app.models import (
    Author,
    CollectionPaper,
    KnowledgeEntity,
    Paper,
    PaperAuthor,
    ResearchFinding,
    ResearchFindingRevision,
    ResearchRevision,
    ResearchScope,
    ResearchTask,
)


def make_paper(client: TestClient, title: str) -> dict:
    response = client.post('/api/papers', json={'title': title})
    assert response.status_code == 201
    return response.json()


def test_assign_existing_papers_retains_other_topics_and_is_idempotent(client: TestClient):
    first = make_paper(client, 'Generative Agents')
    second = make_paper(client, 'Reflexion')
    other = client.post('/api/collections', json={'name': 'Agents'}).json()
    target = client.post('/api/collections', json={'name': 'Memory初探'}).json()
    client.put(f"/api/collections/{other['id']}/papers/{first['id']}")
    url = f"/api/collections/{target['id']}/papers"

    for _ in range(2):
        result = client.post(url, json={'paper_ids': [first['id'], second['id'], first['id']]})
        assert result.status_code == 200, result.text
        assert result.json()['paper_count'] == 2
    assert set(client.get(f"/api/papers/{first['id']}").json()['collection_ids']) == {other['id'], target['id']}
    assert client.get(f"/api/papers/{second['id']}").json()['collection_ids'] == [target['id']]
    assert client.get(f"/api/collections/{other['id']}").json()['paper_count'] == 1
    assert client.get('/api/papers', params={'collection_id': target['id']}).json()['total'] == 2
    # Membership changes do not alter metadata or delete the underlying paper.
    assert client.get(f"/api/papers/{first['id']}").json()['title'] == first['title']


def test_delete_collection_keeps_papers_and_other_collections(client: TestClient):
    first = make_paper(client, 'Shared paper')
    second = make_paper(client, 'Other paper')
    target = client.post('/api/collections', json={'name': 'To delete'}).json()
    other = client.post('/api/collections', json={'name': 'Keep'}).json()
    client.put(f"/api/collections/{target['id']}/papers/{first['id']}")
    pdf = client.app.state.storage_dir / f"{first['id']}.pdf"
    pdf.write_bytes(b'%PDF-collection-delete-fixture')
    with client.app.state.database.sessions() as db:
        db.get(Paper, first['id']).pdf_path = str(pdf)
        db.add(Author(id='shared-author', name='Shared author'))
        db.add(KnowledgeEntity(id='shared-entity', entity_type='method',
                               name='Shared method', normalized_name='shared method'))
        db.flush()
        db.add(PaperAuthor(paper_id=first['id'], author_id='shared-author'))
        db.commit()
    client.put(f"/api/collections/{other['id']}/papers/{first['id']}")
    client.put(f"/api/collections/{other['id']}/papers/{second['id']}")

    response = client.delete(f"/api/collections/{target['id']}")

    assert response.status_code == 204
    assert response.content == b''
    assert client.get(f"/api/papers/{first['id']}").status_code == 200
    assert client.get(f"/api/papers/{second['id']}").status_code == 200
    assert client.get(f"/api/collections/{other['id']}").json()['paper_count'] == 2
    assert client.get(f"/api/collections/{target['id']}").status_code == 404
    assert client.get(f"/api/papers/{first['id']}").json()['collection_ids'] == [other['id']]
    assert pdf.read_bytes() == b'%PDF-collection-delete-fixture'
    with client.app.state.database.sessions() as db:
        assert db.get(Paper, first['id']).pdf_path == str(pdf)
        assert db.get(Author, 'shared-author') is not None
        assert db.get(PaperAuthor, (first['id'], 'shared-author')) is not None
        assert db.get(KnowledgeEntity, 'shared-entity') is not None
        assert db.get(CollectionPaper, (target['id'], first['id'])) is None
        assert db.get(CollectionPaper, (other['id'], first['id'])) is not None
    assert client.delete(f"/api/collections/{target['id']}").status_code == 404


def test_delete_collection_cascades_scope_and_research_records(client: TestClient):
    target = client.post('/api/collections', json={'name': 'Research to delete'}).json()
    other = client.post('/api/collections', json={'name': 'Research keep'}).json()
    database = client.app.state.database
    with database.sessions() as db:
        db.add_all([
            ResearchScope(collection_id=target['id'], enabled=True, focus='focus'),
            ResearchScope(collection_id=other['id'], enabled=True, focus='other'),
            ResearchTask(id='task-delete', collection_id=target['id'], fingerprint='fp-delete',
                         material_json='{}'),
            ResearchTask(id='task-keep', collection_id=other['id'], fingerprint='fp-keep',
                         material_json='{}'),
        ])
        db.flush()
        db.add_all([
            ResearchRevision(id='revision-delete', collection_id=target['id'], task_id='task-delete',
                             number=1, title='title', dek='dek', markdown='markdown', changes='changes',
                             sources_json='[]', coverage_json='[]', model='test'),
            ResearchFinding(id='finding-delete', collection_id=target['id'], identity='finding', kind='gap',
                            title='finding', body='body', next_step='next', sources_json='[]', model='test'),
        ])
        db.flush()
        db.add(ResearchFindingRevision(id='finding-revision-delete', finding_id='finding-delete',
                                     task_id='task-delete', content_hash='hash', content_json='{}'))
        db.commit()

    assert client.delete(f"/api/collections/{target['id']}").status_code == 204
    with database.sessions() as db:
        assert db.get(ResearchScope, target['id']) is None
        assert db.get(ResearchTask, 'task-delete') is None
        assert db.get(ResearchRevision, 'revision-delete') is None
        assert db.get(ResearchFinding, 'finding-delete') is None
        assert db.get(ResearchFindingRevision, 'finding-revision-delete') is None
        assert db.get(ResearchScope, other['id']) is not None
        assert db.get(ResearchTask, 'task-keep') is not None


def test_delete_missing_collection_returns_404(client: TestClient):
    response = client.delete('/api/collections/missing-collection')

    assert response.status_code == 404


def test_missing_paper_does_not_partially_assign_a_batch(client: TestClient):
    paper = make_paper(client, 'Existing paper')
    target = client.post('/api/collections', json={'name': 'Memory'}).json()
    result = client.post(f"/api/collections/{target['id']}/papers", json={'paper_ids': [paper['id'], 'missing-paper']})
    assert result.status_code == 404
    assert client.get(f"/api/collections/{target['id']}").json()['paper_count'] == 0
    assert client.get(f"/api/papers/{paper['id']}").json()['collection_ids'] == []


def test_missing_destination_is_reported(client: TestClient):
    paper = make_paper(client, 'Existing paper')
    result = client.post('/api/collections/missing-collection/papers', json={'paper_ids': [paper['id']]})
    assert result.status_code == 404
    assert client.get(f"/api/papers/{paper['id']}").json()['collection_ids'] == []


@pytest.mark.parametrize('paper_ids', [[], ['missing'] * 501])
def test_collection_assignment_has_a_bounded_nonempty_batch(client: TestClient, paper_ids):
    target = client.post('/api/collections', json={'name': 'Memory'}).json()
    result = client.post(f"/api/collections/{target['id']}/papers", json={'paper_ids': paper_ids})
    assert result.status_code == 422
    assert client.get(f"/api/collections/{target['id']}").json()['paper_count'] == 0
