from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.mock import MockProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from test_remote_provider import import_fixture


def remote_provider(calls: list[str], *, model: str = "test-model", text: str = "该方法正确检索了 100 个段落中的 71 个。", fail: bool = False):
    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["model"])
        if fail:
            raise httpx.ReadTimeout("test-secret unsafe detail", request=request)
        return httpx.Response(200, json={"model": model + "-actual", "choices": [{"message": {"content": text}}]})

    return OpenAICompatibleProvider(api_key="test-secret", base_url="https://model.example/v1", model=model, transport=httpx.MockTransport(respond))


def test_translation_persists_across_restart_and_reads_without_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite:///{(tmp_path / 'workspace.db').as_posix()}"
    calls: list[str] = []
    monkeypatch.setattr("app.api.papers.get_model_provider", lambda: remote_provider(calls))
    with TestClient(create_app(database_url=url, storage_dir=tmp_path / "files", seed_demo=False)) as client:
        paper = import_fixture(client)
        chunk = paper["chunks"][0]
        path = f"/api/papers/{paper['id']}/translate"
        first = client.post(path, json={"chunk_id": chunk["id"]})
        assert first.status_code == 200
        assert first.json()["cached"] is False
        assert first.json()["model_version"] == "test-model-actual"
        assert first.json()["prompt_version"]
        assert first.json()["source_text"] == chunk["content"]
    with TestClient(create_app(database_url=url, storage_dir=tmp_path / "files", seed_demo=False)) as restarted:
        again = restarted.post(path, json={"chunk_id": chunk["id"]})
        assert again.status_code == 200
        assert again.json()["cached"] is True
        assert again.json()["id"] == first.json()["id"]
        assert calls == ["test-model"]
        detail = restarted.get(f"/api/papers/{paper['id']}").json()
        assert len(detail["translations"]) == 1
        assert detail["translations"][0]["text"] == first.json()["text"]
        assert detail["translations"][0]["provider"] == "OpenAICompatibleProvider"
        monkeypatch.setattr("app.api.papers.get_model_provider", MockProvider)
        offline = restarted.post(path, json={"chunk_id": chunk["id"]})
        assert offline.status_code == 200
        assert offline.json()["text"] == first.json()["text"]
        assert offline.json()["provider"] == "OpenAICompatibleProvider"
        assert offline.json()["cached"] is True
        forced_offline = restarted.post(path, json={"chunk_id": chunk["id"], "force": True})
        assert forced_offline.status_code == 503
        assert calls == ["test-model"]


def test_translation_config_change_and_explicit_force_regenerate(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = import_fixture(client)
    chunk = paper["chunks"][0]
    path = f"/api/papers/{paper['id']}/translate"
    calls: list[str] = []
    monkeypatch.setattr("app.api.papers.get_model_provider", lambda: remote_provider(calls))
    first = client.post(path, json={"chunk_id": chunk["id"]}).json()
    monkeypatch.setattr("app.api.papers.get_model_provider", lambda: remote_provider(calls, model="other-model", text="第二个模型产生的真实返回译文。"))
    second = client.post(path, json={"chunk_id": chunk["id"]})
    assert second.status_code == 200
    assert second.json()["text"] != first["text"]
    assert second.json()["cached"] is False
    assert second.json()["model_version"] == "other-model-actual"
    cached = client.post(path, json={"chunk_id": chunk["id"]})
    assert cached.json()["cached"] is True
    forced = client.post(path, json={"chunk_id": chunk["id"], "force": True})
    assert forced.status_code == 200
    assert forced.json()["cached"] is False
    assert calls == ["test-model", "other-model", "other-model"]
    records = client.get(f"/api/papers/{paper['id']}").json()["translations"]
    assert len(records) == 2
    assert "test-secret" not in json.dumps(records)


def test_failed_forced_translation_preserves_cache_and_unknown_chunk_cannot_read_it(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = import_fixture(client)
    chunk = paper["chunks"][0]
    path = f"/api/papers/{paper['id']}/translate"
    calls: list[str] = []
    monkeypatch.setattr("app.api.papers.get_model_provider", lambda: remote_provider(calls))
    first = client.post(path, json={"chunk_id": chunk["id"]}).json()
    monkeypatch.setattr("app.api.papers.get_model_provider", lambda: remote_provider(calls, fail=True))
    failed = client.post(path, json={"chunk_id": chunk["id"], "force": True})
    assert failed.status_code == 504
    assert "test-secret" not in failed.text
    assert client.get(f"/api/papers/{paper['id']}").json()["translations"][0]["text"] == first["text"]
    wrong = client.post(path, json={"chunk_id": "nonexistent-chunk"})
    assert wrong.status_code == 404
    monkeypatch.setattr("app.api.papers.get_model_provider", MockProvider)
    fresh = import_fixture_with_distinct_content(client)
    missing = client.post(f"/api/papers/{fresh['id']}/translate", json={"chunk_id": fresh["chunks"][0]["id"]})
    assert missing.status_code == 503
    assert client.get(f"/api/papers/{fresh['id']}").json()["translations"] == []


def test_endpoint_prompt_and_original_source_changes_do_not_reuse_stale_translation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.models import PaperChunk

    paper = import_fixture(client)
    chunk = paper["chunks"][0]
    path = f"/api/papers/{paper['id']}/translate"
    calls: list[str] = []
    provider = remote_provider(calls)
    monkeypatch.setattr("app.api.papers.get_model_provider", lambda: provider)
    first = client.post(path, json={"chunk_id": chunk["id"]}).json()
    provider.base_url = "https://another-model.example/v1"
    second = client.post(path, json={"chunk_id": chunk["id"]}).json()
    assert second["cached"] is False
    assert second["id"] != first["id"]
    original_prompt = provider._prompt
    monkeypatch.setattr(provider, "_prompt", lambda name: original_prompt(name) + "\nUpdated translation instructions.")
    third = client.post(path, json={"chunk_id": chunk["id"]}).json()
    assert third["cached"] is False
    assert third["prompt_version"] != second["prompt_version"]
    with client.app.state.database.sessions() as session:
        original = session.get(PaperChunk, chunk["id"])
        original.content = "The corrected original paper passage retrieves 75 of 100 passages."
        session.commit()
    assert client.get(f"/api/papers/{paper['id']}").json()["translations"] == []
    monkeypatch.setattr("app.api.papers.get_model_provider", MockProvider)
    offline = client.post(path, json={"chunk_id": chunk["id"]})
    assert offline.status_code == 503
    assert calls == ["test-model", "test-model", "test-model"]


def import_fixture_with_distinct_content(client: TestClient) -> dict:
    import fitz
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), "A distinct original source passage without a cached translation.")
        data = document.tobytes()
    response = client.post("/api/papers/import", files={"file": ("distinct.pdf", data)})
    assert response.status_code == 201
    return response.json()
