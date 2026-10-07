from pathlib import Path
import fitz
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import create_app


def test_paper_notes_collection_and_fulltext_survive_restart(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'workspace.db').as_posix()}"
    storage = tmp_path / "storage"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), "Persistent luminoushedgehog evidence paragraph.")
        content = document.tobytes()
    with TestClient(create_app(url, storage, seed_demo=False)) as first:
        paper = first.post(
            "/api/papers/import", files={"file": ("persistent.pdf", content)}
        ).json()
        first.patch(
            f"/api/papers/{paper['id']}",
            json={"is_favorite": True, "reading_status": "reading"},
        )
        first.post(
            f"/api/papers/{paper['id']}/notes",
            json={"content": "Preserve my idea", "kind": "idea"},
        )
        collection = first.post(
            "/api/collections", json={"name": "Persistent collection"}
        ).json()
        first.put(f"/api/collections/{collection['id']}/papers/{paper['id']}")
    app = create_app(url, storage, seed_demo=False)
    with TestClient(app) as restarted:
        detail = restarted.get(f"/api/papers/{paper['id']}").json()
        assert detail["notes"][0]["content"] == "Preserve my idea"
        assert detail["is_favorite"] is True
        assert detail["reading_status"] == "reading"
        assert detail["collection_ids"] == [collection["id"]]
        assert restarted.get(f"/api/papers/{paper['id']}/pdf").content == content
        assert restarted.get(
            "/api/search", params={"query": "luminoushedgehog"}
        ).json()["items"]
        with app.state.database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE paper_chunks SET content='Changed text ambervulture' WHERE paper_id=:paper"
                ),
                {"paper": paper["id"]},
            )
        assert (
            restarted.get("/api/search", params={"query": "luminoushedgehog"}).json()[
                "items"
            ]
            == []
        )
        assert restarted.get("/api/search", params={"query": "ambervulture"}).json()[
            "items"
        ]
