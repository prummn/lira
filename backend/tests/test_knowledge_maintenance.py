"""Deterministic knowledge-network maintenance and repair gates."""

import json

import httpx
import pytest

from app.models import KnowledgeCandidate, KnowledgeEntity, KnowledgeMaintenanceRun, KnowledgeRelation, Paper, PaperChunk
from app.services.knowledge_maintenance import (
    apply_issue,
    collect_deterministic_findings,
    confidence_gate,
    make_issue,
    scope_fingerprint,
    undo_issue,
)
from app.providers.base import ProviderError
from app.providers.openai_compatible import OpenAICompatibleProvider
from test_knowledge_service import make_db


def _paper(session, paper_id="paper-a"):
    paper = Paper(id=paper_id, title="Paper A")
    paper.chunks.append(PaperChunk(id=paper_id + "-chunk", page=3, section="Method", content="ReAct is evaluated on HotpotQA."))
    session.add(paper)
    session.flush()
    return paper


def _candidate(paper, cid, name="ReAct", normalized="react", status="candidate"):
    return KnowledgeCandidate(
        id=cid,
        paper_id=paper.id,
        entity_type="method",
        name=name,
        normalized_name=normalized,
        role="proposed",
        confidence=0.95,
        status=status,
        evidence_json=json.dumps([{"chunk_id": paper.chunks[0].id, "quote": "ReAct"}]),
    )


def test_deterministic_audit_reports_exact_duplicate_candidates_as_safe(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = _paper(session)
        session.add_all([_candidate(paper, "c-1"), _candidate(paper, "c-2")])
        session.commit()
        findings = collect_deterministic_findings(session, [paper.id])
        duplicate = next(item for item in findings if item["kind"] == "identity")
        assert duplicate["proposed_action"] == {"type": "reconcile_paper", "paper_id": paper.id}
        assert duplicate["auto_eligible"] is True
        assert duplicate["confidence_basis"]["exact_identity"] is True


def test_evidence_repair_is_reversible_and_keeps_quote(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = _paper(session)
        row = _candidate(paper, "c-1")
        row.evidence_json = json.dumps([{"chunk_id": paper.chunks[0].id, "page": 99, "quote": "ReAct"}])
        session.add(row)
        session.flush()
        run = KnowledgeMaintenanceRun(
            id="run-1", scope_type="papers", status="complete", source_fingerprint=scope_fingerprint(session, [paper.id])
        )
        session.add(run)
        session.flush()
        finding = next(item for item in collect_deterministic_findings(session, [paper.id]) if item["kind"] == "evidence")
        issue = make_issue(session, run, finding)
        session.flush()
        assert issue.auto_eligible is True
        apply_issue(session, issue)
        session.commit()
        assert json.loads(row.evidence_json)[0]["page"] == 3
        assert issue.status == "auto_applied"
        undo_issue(session, issue)
        session.commit()
        assert json.loads(row.evidence_json)[0]["page"] == 99
        assert issue.status == "undone"


def test_rejected_endpoint_and_ambiguous_alias_are_never_auto_applied(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = _paper(session)
        first = _candidate(paper, "c-1", name="Memory controller", normalized="memory controller")
        second = _candidate(paper, "c-2", name="Monte Carlo", normalized="monte carlo")
        first.aliases_json = json.dumps(["memory-control"])
        second.aliases_json = json.dumps(["memory-control"])
        first.status = second.status = "confirmed"
        session.add_all([first, second])
        session.add(KnowledgeEntity(id="e-1", entity_type="method", name="Memory controller", normalized_name="memory controller", aliases_json='["memory-control"]'))
        session.add(KnowledgeEntity(id="e-2", entity_type="method", name="Monte Carlo", normalized_name="monte carlo", aliases_json='["memory-control"]'))
        session.flush()
        relation = KnowledgeRelation(
            id="r-1", paper_id=paper.id, relation="builds_on", source_name="Memory controller", source_normalized_name="memory controller",
            target_name="Monte Carlo", target_normalized_name="monte carlo", source_candidate_id=first.id, target_candidate_id=None,
            status="candidate", confidence=.9, evidence_json=json.dumps([{"chunk_id": paper.chunks[0].id, "quote": "ReAct"}]),
        )
        session.add(relation)
        session.commit()
        findings = collect_deterministic_findings(session, [paper.id])
        alias = next(item for item in findings if item["proposed_action"]["type"] == "review_alias_collision")
        assert alias["auto_eligible"] is False
        endpoint = next(item for item in findings if item["proposed_action"]["type"] == "reconcile_paper")
        gate = confidence_gate(session, endpoint)
        assert gate["auto_eligible"] is True
        relation.status = "rejected"
        relation_finding = {
            "kind": "relation", "subject_ids": [relation.id], "confidence": 1,
            "confidence_basis": {"deterministic": True}, "evidence": endpoint["evidence"],
            "proposed_action": {"type": "restore_relation", "relation_id": relation.id},
        }
        assert confidence_gate(session, relation_finding)["auto_eligible"] is False


def test_provider_validates_bounded_maintenance_bundle_and_citations():
    seen = {}

    def respond(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "issues": [{
                    "kind": "relation", "summary": "关系待核对", "reasoning": "原文支持一条明确关系",
                    "subject_ids": ["r-1"], "citations": [{"chunk_id": "chunk-1", "source_text": "A builds on B."}],
                    "action": {"type": "rewrite_relation"}, "confidence": .92,
                    "confidence_factors": {"evidence_count": 1}, "external_queries": [],
                }]
            }, ensure_ascii=False)}}], "model": "maintenance-model",
        })

    provider = OpenAICompatibleProvider(api_key="test-secret", base_url="https://model.example/v1", model="maintenance-model", transport=httpx.MockTransport(respond))
    result = provider.audit_knowledge_bundle({
        "subject_ids": ["r-1"], "chunks": [{"chunk_id": "chunk-1", "content": "A builds on B."}],
        "subjects": [{"id": "r-1", "type": "relation"}],
    })
    assert result["issues"][0]["subject_ids"] == ["r-1"]
    assert result["issues"][0]["citations"][0]["chunk_id"] == "chunk-1"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["max_completion_tokens"] == 2200
    assert "store" not in seen["body"]


def test_provider_rejects_out_of_scope_maintenance_citation():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "issues": [{"kind": "evidence", "summary": "bad", "reasoning": "bad", "subject_ids": ["r-1"],
                             "citations": [{"chunk_id": "unknown", "source_text": "bad"}], "action": {}, "confidence": .1}]
            })}}]
        })

    provider = OpenAICompatibleProvider(api_key="test-secret", base_url="https://model.example/v1", model="maintenance-model", transport=httpx.MockTransport(respond))
    with pytest.raises(ProviderError) as error:
        provider.audit_knowledge_bundle({"subject_ids": ["r-1"], "chunks": [{"chunk_id": "chunk-1", "content": "A builds on B."}]})
    assert error.value.code == "invalid_response"
