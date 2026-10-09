from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_model_settings_can_be_saved_without_echoing_secret(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    response = client.put(
        "/api/settings/model",
        json={
            "base_url": "https://spacetimeai.cc/v1",
            "model": "gpt-6.1-sol",
            "api_key": "settings-secret",
            "wire_api": "responses",
            "reasoning_effort": "xhigh",
            "timeout": 600,
            "test_connection": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "OpenAICompatibleProvider"
    assert body["translation_available"] is True
    assert body["model"] == "gpt-6.1-sol"
    assert body["api_key_configured"] is True
    assert "settings-secret" not in response.text
    assert os.getenv("PAPER_READER_MODEL_API_KEY") == "settings-secret"
    config_path = client.app.state.model_config_path
    config = config_path.read_text(encoding="utf-8")
    assert 'PAPER_READER_MODEL_BASE_URL="https://spacetimeai.cc/v1"' in config
    assert 'PAPER_READER_MODEL_NAME="gpt-6.1-sol"' in config
    assert 'PAPER_READER_MODEL_API_KEY="settings-secret"' in config


def test_model_settings_reject_invalid_url_without_changing_active_config(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("PAPER_READER_MODEL_API_KEY", "existing-secret")
    monkeypatch.setenv("PAPER_READER_MODEL_BASE_URL", "https://model.example/v1")
    response = client.put(
        "/api/settings/model",
        json={
            "base_url": "not a url",
            "model": "gpt-6.1-sol",
            "api_key": "new-secret",
            "wire_api": "responses",
            "reasoning_effort": "xhigh",
            "timeout": 600,
            "test_connection": False,
        },
    )

    assert response.status_code == 422
    assert os.getenv("PAPER_READER_MODEL_API_KEY") == "existing-secret"
    assert os.getenv("PAPER_READER_MODEL_BASE_URL") == "https://model.example/v1"
    assert client.app.state.model_config_path.exists() is False


def test_model_settings_can_be_removed_without_leaving_secret_in_config(
    client: TestClient,
) -> None:
    saved = client.put(
        "/api/settings/model",
        json={
            "base_url": "https://model.example/v1",
            "model": "fixture-model",
            "api_key": "remove-me",
            "test_connection": False,
        },
    )
    assert saved.status_code == 200

    response = client.delete("/api/settings/model")

    assert response.status_code == 200
    assert response.json()["provider"] == "MockProvider"
    assert response.json()["api_key_configured"] is False
    assert os.getenv("PAPER_READER_MODEL_API_KEY") is None
    assert "remove-me" not in client.app.state.model_config_path.read_text(encoding="utf-8")
