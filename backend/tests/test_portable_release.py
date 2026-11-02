"""The student release must start empty and keep private files out of HTTP/ZIP."""
from __future__ import annotations

import importlib.util
import mimetypes
from pathlib import Path
import pytest

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, relative: str):
    path = ROOT / relative
    assert path.is_file(), f"Missing release component: {relative}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_starts_empty_and_only_serves_frontend(tmp_path, monkeypatch):
    portable = load_script("portable_release", "scripts/portable/lira.py")
    install = tmp_path / "安装 文件"
    web = install / "frontend" / "dist"
    web.mkdir(parents=True)
    (web / "index.html").write_text("<h1>LIRA release</h1>", encoding="utf-8")
    (web / "worker.js").write_text("// pdf worker", encoding="utf-8")
    (web / "pdf.worker.mjs").write_text("// module worker", encoding="utf-8")
    (install / "private.txt").write_text("private", encoding="utf-8")
    data = tmp_path / "研究 数据"
    monkeypatch.setenv("PAPER_READER_MODEL_API_KEY", "should-not-be-inherited")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-shell-credential")
    # Windows registry overrides can mislabel .js/.mjs and produce a blank UI.
    mimetypes.init()
    monkeypatch.setitem(mimetypes.types_map, ".js", "text/plain")
    monkeypatch.setitem(mimetypes.types_map, ".mjs", "text/plain")
    # configure_environment is process-local, so restore every affected key.
    for key in list(portable.os.environ):
        if key.startswith("PAPER_READER_") or key in {"OPENAI_API_KEY", "PATH"}:
            monkeypatch.setenv(key, portable.os.environ[key])
    for key in ("PAPER_READER_DATABASE_URL", "PAPER_READER_STORAGE_DIR", "PAPER_READER_MODEL_CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)
    application = portable.create_application(install, data, "test-instance", "test-token")
    with TestClient(application) as client:
        assert client.get("/").text == "<h1>LIRA release</h1>"
        assert client.get("/worker.js").status_code == 200
        for route in ("/worker.js", "/pdf.worker.mjs"):
            assert client.get(route).headers["content-type"].split(";")[0] in {"application/javascript", "text/javascript"}
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/papers").json()["total"] == 0
        profiles = application.state.model_profiles.public()
        assert profiles["profiles"] == []
        for route in ("/private.txt", "/data/paper_reader.db", "/backend/app/main.py", "/.env", "/api/missing"):
            assert client.get(route).status_code == 404
        identity = client.get("/__lira/instance").json()
        assert identity["instance"] == "test-instance"
        assert "test-token" not in client.get("/__lira/instance").text
        assert client.post("/__lira/stop").status_code == 403
        assert client.post("/__lira/stop", headers={"X-Lira-Token": "wrong"}).status_code == 403
        assert client.post("/__lira/stop", headers={"X-Lira-Token": "test-token"}).status_code == 202
        assert application.state.exit_requested.is_set()
    assert (data / "paper_reader.db").is_file()
    assert not (install / "backend" / "paper_reader.db").exists()


def test_packaging_allowlist_excludes_local_data_and_symlinks(tmp_path):
    release = load_script("release_builder", "scripts/build_release.py")
    for name in ("backend/app/main.py", "backend/app/__pycache__/secret.pyc", "backend/app/leak.db", "backend/paper_reader.db", "backend/storage/paper.pdf", "backend/migrations/env.py", "prompts/paper_ask.txt", "frontend/src/App.tsx", "frontend/package-lock.json", ".env", ".env.models.json", "debug-resume-model.env.models.json", "frontend/dist/index.html", ".local-runtime/cache.json"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")
    paths = {p.relative_to(tmp_path).as_posix() for p in release.application_files(tmp_path)}
    assert paths == {"backend/app/main.py", "backend/migrations/env.py", "prompts/paper_ask.txt", "frontend/src/App.tsx", "frontend/package-lock.json", "frontend/dist/index.html"}


def test_release_audit_rejects_secret_even_in_allowed_source(tmp_path):
    release = load_script("release_builder_audit", "scripts/build_release.py")
    (tmp_path / "app.py").write_text("key='sk-" + "x" * 48 + "'", encoding="utf-8")
    errors = release.audit_files(tmp_path)
    assert errors and "app.py" in str(errors)
    assert "x" * 48 not in str(errors)


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows portable process lock")
def test_busy_service_cannot_start_second_worker_when_health_is_unavailable(tmp_path):
    portable = load_script("portable_process_lock", "scripts/portable/lira.py")
    assert hasattr(portable, "service_lock"), "A server lifetime lock must protect the shared library"
    with portable.service_lock(tmp_path):
        with pytest.raises(RuntimeError, match="正在运行"):
            portable.start(tmp_path, 5173, no_browser=True)
