from __future__ import annotations

import fitz
import pytest
from fastapi.testclient import TestClient


def pdf_bytes(*pages: str) -> bytes:
    with fitz.open() as document:
        for content in pages:
            page = document.new_page()
            if content:
                page.insert_textbox(fitz.Rect(50, 50, 545, 790), content, fontsize=11)
        return document.tobytes()


@pytest.fixture
def paper(client: TestClient) -> dict:
    content = pdf_bytes(
        "Real Research Paper\nAbstract\nWe investigate quartzflame retrieval for local scientific archives.",
        "3 Method\nWe use quartzflame retrieval to select evidence passages.\n4 Results\nThe system retrieves the correct passage in 71 of 100 cases.\n5 Limitations\nThe evaluation covers only one English corpus.",
    )
    response = client.post(
        "/api/papers/import",
        files={"file": ("archive.pdf", content, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_import_parses_real_pages_and_bounds(client: TestClient, paper: dict) -> None:
    assert paper["page_count"] == 2
    assert paper["is_demo"] is False
    assert paper["pdf_available"] is True
    assert any(c["page"] == 2 and "71 of 100" in c["content"] for c in paper["chunks"])
    for chunk in paper["chunks"]:
        x0, y0, x1, y1 = chunk["bbox"]
        assert 0 <= x0 < x1 <= chunk["page_width"]
        assert 0 <= y0 < y1 <= chunk["page_height"]
    pdf = client.get(f"/api/papers/{paper['id']}/pdf")
    with fitz.open(stream=pdf.content, filetype="pdf") as parsed:
        assert parsed.page_count == 2


def test_same_pdf_is_rejected_even_when_filename_changes(client: TestClient) -> None:
    content = pdf_bytes("Duplicate document")
    first = client.post("/api/papers/import", files={"file": ("one.pdf", content)})
    duplicate = client.post("/api/papers/import", files={"file": ("two.pdf", content)})
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert client.get("/api/papers").json()["total"] == 1


@pytest.mark.parametrize("content", [b"not a PDF", b"%PDF-1.7\ncorrupted"])
def test_invalid_pdf_never_creates_a_record(client: TestClient, content: bytes) -> None:
    response = client.post("/api/papers/import", files={"file": ("bad.pdf", content)})
    assert response.status_code == 422
    assert response.json()["detail"]
    assert client.get("/api/papers").json()["total"] == 0


def test_oversized_pdf_is_rejected(client: TestClient) -> None:
    content = b"%PDF-1.7\n" + b" " * (50 * 1024 * 1024)
    response = client.post("/api/papers/import", files={"file": ("huge.pdf", content)})
    assert response.status_code == 413
    assert client.get("/api/papers").json()["total"] == 0


def test_scanned_pdf_does_not_invent_analysis(client: TestClient) -> None:
    response = client.post(
        "/api/papers/import", files={"file": ("scan.pdf", pdf_bytes(""))}
    )
    assert response.status_code == 201
    paper = response.json()
    assert paper["page_count"] == 1
    assert paper["chunks"] == []
    assert paper["analysis"] is None
    assert paper["analysis_status"] == "no_text"
    analyzed = client.post(f"/api/papers/{paper['id']}/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["analysis"] is None
    answer = client.post(
        f"/api/papers/{paper['id']}/ask", json={"question": "What are the results?"}
    )
    assert answer.json()["insufficient_evidence"] is True
    assert answer.json()["citations"] == []


def test_extract_analysis_never_invents_results(
    client: TestClient, paper: dict
) -> None:
    detail = client.post(f"/api/papers/{paper['id']}/analyze").json()
    assert detail["analysis"]["mode"] == "extractive"
    assert detail["analysis"]["provider"] == "MockProvider"
    chunks = {c["id"]: c for c in detail["chunks"]}
    assert detail["evidence"]
    for citation in detail["evidence"]:
        chunk = chunks[citation["chunk_id"]]
        assert citation["source_text"] in chunk["content"]
        assert citation["claim"] == citation["source_text"]
    assert "71 of 100" in detail["analysis"]["findings"]
    before_ids = [e["id"] for e in detail["evidence"]]
    again = client.post(f"/api/papers/{paper['id']}/analyze").json()
    assert [e["id"] for e in again["evidence"]] == before_ids


def test_question_answer_has_real_citations_or_abstains(
    client: TestClient, paper: dict
) -> None:
    answer = client.post(
        f"/api/papers/{paper['id']}/ask",
        json={"question": "How does quartzflame retrieval select evidence?"},
    )
    assert answer.status_code == 200
    assert answer.json()["insufficient_evidence"] is False
    assert answer.json()["mode"] == "extractive"
    assert answer.json()["citations"]
    assert all(
        c["source_text"] in answer.json()["answer"] for c in answer.json()["citations"]
    )
    missing = client.post(
        f"/api/papers/{paper['id']}/ask",
        json={"question": "What happened on Mars in 1890?"},
    )
    assert missing.json()["insufficient_evidence"] is True
    assert missing.json()["citations"] == []


def test_ask_results_uses_the_actual_results_section(
    client: TestClient, paper: dict
) -> None:
    response = client.post(
        f"/api/papers/{paper['id']}/ask", json={"question": "What are the results?"}
    )
    assert response.json()["insufficient_evidence"] is False
    assert "71 of 100" in response.json()["answer"]


def test_imported_rotation_and_crop_keep_canonical_unrotated_geometry(
    client: TestClient,
) -> None:
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text(
            (140, 170), "A visible rotated and cropped research passage.", fontsize=12
        )
        page.set_cropbox(fitz.Rect(100, 100, 500, 700))
        page.set_rotation(90)
        content = document.tobytes()
        text_block = page.get_text("dict")["blocks"][0]["lines"][0]["bbox"]
        expected = list(text_block)
        canonical_size = (page.cropbox.width, page.cropbox.height)
    response = client.post(
        "/api/papers/import", files={"file": ("rotated.pdf", content)}
    )
    assert response.status_code == 201
    chunk = response.json()["chunks"][0]
    assert [chunk["page_width"], chunk["page_height"]] == list(canonical_size)
    assert chunk["bbox"] == pytest.approx(expected)


def test_notes_persist_and_can_be_deleted(client: TestClient, paper: dict) -> None:
    base = f"/api/papers/{paper['id']}/notes"
    data = {
        "content": "Check external validity",
        "kind": "question",
        "page": 2,
        "source_text": "one English corpus",
        "bbox": [50, 50, 200, 70],
    }
    note = client.post(base, json=data)
    assert note.status_code == 201
    saved = note.json()
    assert saved["created_at"]
    assert saved["kind"] == "question"
    assert saved in client.get(base).json()
    assert saved in client.get(f"/api/papers/{paper['id']}").json()["notes"]
    assert client.delete(f"{base}/{saved['id']}").status_code == 204
    assert client.get(base).json() == []


def test_invalid_note_is_rejected(client: TestClient, paper: dict) -> None:
    path = f"/api/papers/{paper['id']}/notes"
    for body in [
        {"content": "  "},
        {"content": "note", "page": 100},
        {"content": "note", "kind": "bogus"},
        {"content": "note", "bbox": [20, 10, 5, 2]},
    ]:
        response = client.post(path, json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)


def test_collection_membership_is_idempotent(client: TestClient, paper: dict) -> None:
    collection = client.post("/api/collections", json={"name": "Reading queue"}).json()
    path = f"/api/collections/{collection['id']}/papers/{paper['id']}"
    assert client.put(path).status_code == 200
    assert client.put(path).status_code == 200
    assert client.get(f"/api/collections/{collection['id']}").json()["paper_count"] == 1
    filtered = client.get(
        "/api/papers", params={"collection_id": collection["id"]}
    ).json()
    assert [p["id"] for p in filtered["items"]] == [paper["id"]]
    assert client.delete(path).status_code == 204
    assert client.get(f"/api/collections/{collection['id']}").json()["paper_count"] == 0


def test_fulltext_returns_real_chunk_locations(client: TestClient, paper: dict) -> None:
    response = client.get("/api/search", params={"query": "quartzflame"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert all(i["paper_id"] == paper["id"] and i["match_type"] == "fts" for i in items)
    assert all("quartzflame" in i["content"] for i in items)
    assert (
        client.get("/api/search", params={"query": "nonexistenttermxyz"}).json()[
            "items"
        ]
        == []
    )
    assert (
        client.get(
            "/api/search", params={"query": '" OR DROP TABLE papers; --'}
        ).status_code
        == 200
    )


def test_empty_graph_contains_no_invented_edges(
    client: TestClient, paper: dict
) -> None:
    graph = client.get("/api/graph").json()
    assert len(graph["nodes"]) == 1
    assert graph["edges"] == []


def test_pagination_does_not_duplicate_authors(client: TestClient) -> None:
    for index in range(3):
        assert (
            client.post(
                "/api/papers",
                json={
                    "title": f"Query Paper {index}",
                    "author_names": ["Shared Name", "Another Name"],
                },
            ).status_code
            == 201
        )
    page = client.get(
        "/api/papers", params={"query": "Query", "limit": 2, "offset": 0}
    ).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert client.get(
        "/api/papers", params={"query": "Query", "limit": 2, "offset": 2}
    ).json()["items"][0]["id"] not in [p["id"] for p in page["items"]]


def test_unconfigured_provider_reports_honest_capabilities(
    client: TestClient, paper: dict
) -> None:
    settings = client.get("/api/settings").json()
    assert settings["provider"] == "MockProvider"
    assert settings["translation_available"] is False
    result = client.post(
        f"/api/papers/{paper['id']}/translate",
        json={"chunk_id": paper["chunks"][0]["id"]},
    )
    assert result.status_code == 503
    assert "翻译需要配置模型" in result.json()["detail"]
