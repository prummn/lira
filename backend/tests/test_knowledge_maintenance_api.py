"""API persistence and safe repair behavior for knowledge maintenance."""

import json

from app.models import KnowledgeCandidate, Paper, PaperChunk


def seed_duplicate(client):
    with client.app.state.database.sessions() as session:
        paper = Paper(id="paper-a", title="Paper A")
        paper.chunks.append(PaperChunk(id="chunk-a", paper_id=paper.id, page=2, section="Method", content="ReAct is evaluated."))
        session.add(paper)
        session.flush()
        for cid in ("candidate-a", "candidate-b"):
            session.add(KnowledgeCandidate(
                id=cid, paper_id=paper.id, entity_type="method", name="ReAct", normalized_name="react",
                role="proposed", confidence=.9, status="candidate",
                evidence_json=json.dumps([{"chunk_id": "chunk-a", "page": 2, "quote": "ReAct"}]),
            ))
        session.commit()


def test_run_persists_one_paper_checkpoint_without_promising_unperformed_repairs(client):
    seed_duplicate(client)
    created = client.post("/api/knowledge/maintenance/runs", json={"scope_type": "papers", "paper_ids": ["paper-a"]})
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["scope_type"] == "papers"
    assert len(payload['issues']) == 1
    assert payload['issues'][0]['proposed_action']['type'] == 'curate_paper'
    assert payload['safe_count'] == 0
    run_id = payload["id"]
    applied = client.post(f"/api/knowledge/maintenance/runs/{run_id}/apply-safe")
    assert applied.status_code == 200, applied.text
    assert applied.json()["results"] == []
    current = client.get(f"/api/knowledge/maintenance/runs/{run_id}")
    assert current.status_code == 200
    assert current.json()["applied_count"] == 0


def test_run_deduplicates_same_fingerprint_unless_forced(client):
    seed_duplicate(client)
    first = client.post("/api/knowledge/maintenance/runs", json={"scope_type": "library"})
    second = client.post("/api/knowledge/maintenance/runs", json={"scope_type": "library"})
    assert first.json()["id"] == second.json()["id"]
    forced = client.post("/api/knowledge/maintenance/runs", json={"scope_type": "library", "force": True})
    assert forced.json()["id"] != first.json()["id"]


def test_run_can_be_cancelled_and_retried_without_losing_local_issues(client):
    seed_duplicate(client)
    created = client.post("/api/knowledge/maintenance/runs", json={"scope_type": "papers", "paper_ids": ["paper-a"]})
    run_id = created.json()["id"]
    cancelled = client.post(f"/api/knowledge/maintenance/runs/{run_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    retried = client.post(f"/api/knowledge/maintenance/runs/{run_id}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "queued"
    detail = client.get(f"/api/knowledge/maintenance/runs/{run_id}").json()
    assert detail["issues"]


def test_run_list_can_be_scoped_to_collection(client):
    from app.models import Collection, CollectionPaper, Paper
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='paper-a', title='Paper A'))
        session.add(Collection(id='collection-a', name='A'))
        session.add(Collection(id='collection-b', name='B'))
        session.add_all([CollectionPaper(collection_id='collection-a', paper_id='paper-a'), CollectionPaper(collection_id='collection-b', paper_id='paper-a')])
        session.commit()
    first = client.post('/api/knowledge/maintenance/runs', json={'scope_type':'collection','scope_id':'collection-a'})
    second = client.post('/api/knowledge/maintenance/runs', json={'scope_type':'collection','scope_id':'collection-b'})
    assert first.status_code == 200 and second.status_code == 200
    scoped = client.get('/api/knowledge/maintenance/runs?scope_type=collection&scope_id=collection-a')
    assert scoped.status_code == 200
    assert [item['scope_id'] for item in scoped.json()['items']] == ['collection-a']
