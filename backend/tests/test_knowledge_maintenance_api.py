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


def test_run_persists_deterministic_issues_and_safe_batch(client):
    seed_duplicate(client)
    created = client.post("/api/knowledge/maintenance/runs", json={"scope_type": "papers", "paper_ids": ["paper-a"]})
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["scope_type"] == "papers"
    assert any(issue["auto_eligible"] for issue in payload["issues"])
    assert payload["safe_count"] >= 1
    run_id = payload["id"]
    applied = client.post(f"/api/knowledge/maintenance/runs/{run_id}/apply-safe")
    assert applied.status_code == 200, applied.text
    assert applied.json()["results"]
    current = client.get(f"/api/knowledge/maintenance/runs/{run_id}")
    assert current.status_code == 200
    assert current.json()["applied_count"] >= 1


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
