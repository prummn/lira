from fastapi.testclient import TestClient
import pytest


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
