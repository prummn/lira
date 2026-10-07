from fastapi.testclient import TestClient


def test_health_reports_ready(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


def test_empty_library_is_isolated(client: TestClient) -> None:
    assert client.get("/api/papers").json()["total"] == 0


def test_demo_papers_have_real_locatable_evidence(demo_client: TestClient) -> None:
    papers = demo_client.get("/api/papers").json()["items"]
    assert len(papers) == 10
    for summary in papers:
        assert summary["is_demo"] is True
        assert summary["pdf_available"] is True
        detail = demo_client.get(f"/api/papers/{summary['id']}").json()
        assert detail["chunks"]
        assert detail["analysis"]["provider"] == "MockProvider"
        source = '\n'.join(c['content'] for c in detail['chunks']).casefold()
        assert all(concept.casefold() in source for concept in detail['analysis']['concepts'])
        for evidence in detail["evidence"]:
            chunk = next(c for c in detail["chunks"] if c["id"] == evidence["chunk_id"])
            assert evidence["source_text"] in chunk["content"]
            assert evidence["page"] == chunk["page"]
            assert evidence["bbox"] == chunk["bbox"]
        pdf = demo_client.get(f"/api/papers/{summary['id']}/pdf")
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF-")


def test_demo_concept_index_has_real_source_terms(demo_client: TestClient) -> None:
    detail = demo_client.get('/api/papers/paper-001').json()
    assert detail['analysis']['concepts']
    assert 'verifier' in [term.casefold() for term in detail['analysis']['concepts']]
