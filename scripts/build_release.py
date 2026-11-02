"""Build an allowlisted, credential-free Windows x64 release from this checkout.

Run with backend/.venv/Scripts/python.exe so runtime dependencies match the tested app.
The frontend build must be current. No personal database or environment is read/copied.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.13.15"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"
RUNTIME_REQUIREMENTS = ["fastapi", "uvicorn", "sqlalchemy", "pydantic", "python-multipart", "httpx", "PyMuPDF", "alembic"]


def application_files(root: Path):
    rules = {"backend/app": {".py"}, "backend/migrations": {".py", ".mako"},
        "prompts": {".txt"}, "frontend/src": None, "frontend/public": None, "frontend/dist": None}
    for folder, extensions in rules.items():
        for path in sorted((root / folder).rglob("*")):
            relative = path.relative_to(root)
            if not path.is_file() or any(part.is_symlink() for part in [path, *path.parents] if part != root.parent):
                continue
            if "__pycache__" in relative.parts or path.suffix in {".pyc", ".db", ".sqlite", ".sqlite3", ".log"} or path.name.startswith(".env"):
                continue
            if extensions is None or path.suffix in extensions:
                yield path
    for name in ("backend/__init__.py", "backend/alembic.ini", "backend/requirements.txt",
        "frontend/package.json", "frontend/package-lock.json", "frontend/tsconfig.json",
        "frontend/tsconfig.app.json", "frontend/tsconfig.node.json", "frontend/vite.config.ts", "frontend/index.html"):
        path = root / name
        if path.is_file() and not path.is_symlink():
            yield path


def audit_files(root: Path):
    errors = []
    secret = re.compile(rb"(?:sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,})")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if path.is_symlink() or any(part in {".git", ".local-runtime", "__pycache__"} for part in relative.parts):
            errors.append(f"Forbidden path: {relative}")
        if path.name.startswith(".env") or path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pdf", ".log"} or path.name in {"auth.json", "instance.json"}:
            errors.append(f"Private data path: {relative}")
        if path.suffix.lower() in {".py", ".js", ".ts", ".tsx", ".json", ".txt", ".md", ".ini", ".cmd", ".html", ".css"}:
            if secret.search(path.read_bytes()):
                errors.append(f"Possible credential in: {relative}")
    return errors


def digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url: str, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        print(f"Downloading {url}", flush=True)
        temporary = destination.with_suffix(".download")
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as target:
            shutil.copyfileobj(response, target)
        temporary.replace(destination)


def copy_dependencies(target: Path):
    from packaging.requirements import Requirement
    pending, copied = list(RUNTIME_REQUIREMENTS), {}
    while pending:
        distribution = metadata.distribution(pending.pop())
        name = distribution.metadata["Name"]
        if name.casefold() in copied:
            continue
        copied[name.casefold()] = {"name": name, "version": distribution.version,
            "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License", "See package license files")}
        for requirement in distribution.requires or []:
            parsed = Requirement(requirement)
            if parsed.marker is None or parsed.marker.evaluate({"extra": ""}):
                pending.append(parsed.name)
        for relative in distribution.files or []:
            if ".." in relative.parts or "__pycache__" in relative.parts or relative.suffix == ".pyc":
                continue
            source = Path(distribution.locate_file(relative))
            if source.is_file() and not source.is_symlink():
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    return sorted(copied.values(), key=lambda x: x["name"].casefold())


def copy_codex(target: Path, source: Path | None):
    if source is None:
        npm_root = subprocess.check_output([shutil.which("npm.cmd"), "root", "-g"], text=True).strip()
        base = Path(npm_root) / "@openai"
        candidates = [base / "codex" / "node_modules" / "@openai" / "codex-win32-x64", base / "codex-win32-x64"]
        source = next((p for p in candidates if p.is_dir()), None)
    if source is None:
        raise RuntimeError("Install @openai/codex on this build machine, or specify --codex-package")
    info = json.loads((source / "package.json").read_text(encoding="utf-8"))
    vendor = source / "vendor" / "x86_64-pc-windows-msvc"
    shutil.copytree(vendor, target)
    version = subprocess.check_output([str(target / "bin" / "codex.exe"), "--version"], text=True).strip()
    return {"package_version": info["version"], "executable_version": version}


def frontend_licenses(target: Path):
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    packages = []
    for name, info in lock["packages"].items():
        if not name or info.get("dev"):
            continue
        installed = ROOT / "frontend" / name
        if not installed.is_dir():
            continue
        packages.append({"name": name.removeprefix("node_modules/"), "version": info["version"], "license": info.get("license", "See package source")})
        for path in installed.iterdir():
            if path.is_file() and path.name.lower().startswith(("license", "licence", "notice", "copying")):
                destination = target / name.removeprefix("node_modules/") / path.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
    return packages


def build(args):
    if sys.platform != "win32" or sys.version_info[:2] != (3, 13):
        raise RuntimeError("Build using Windows x64 Python 3.13 (the project's tested environment).")
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise RuntimeError("Run npm --prefix frontend run build first.")
    output = args.output.resolve()
    folder = output / args.name
    if folder.exists():
        raise RuntimeError(f"Refusing to overwrite existing release: {folder}")
    folder.mkdir(parents=True)
    for path in application_files(ROOT):
        destination = folder / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    shutil.copy2(ROOT / "scripts" / "portable" / "lira.py", folder / "lira.py")
    for name in ("启动 LIRA.cmd", "停止 LIRA.cmd", "使用说明.txt"):
        source = ROOT / "scripts" / "portable" / name
        # cmd.exe misparses multibyte text and quoted paths with Unix line endings.
        if source.suffix == ".cmd":
            (folder / name).write_bytes(source.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
        else:
            shutil.copy2(source, folder / name)
    python_zip = ROOT / ".local-runtime" / "release-downloads" / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    download(PYTHON_URL, python_zip)
    if digest(python_zip) != PYTHON_SHA256:
        raise RuntimeError("Python runtime checksum mismatch; refusing to package.")
    python_dir = folder / "runtime" / "python"
    with zipfile.ZipFile(python_zip) as archive:
        archive.extractall(python_dir)
    (python_dir / "python313._pth").write_text("python313.zip\n.\nLib/site-packages\n../..\n../../backend\nimport site\n", encoding="utf-8")
    dependencies = copy_dependencies(python_dir / "Lib" / "site-packages")
    codex = copy_codex(folder / "runtime" / "codex", args.codex_package)
    licenses = folder / "THIRD_PARTY"
    licenses.mkdir()
    download("https://raw.githubusercontent.com/openai/codex/rust-v0.154.0/LICENSE", licenses / "Codex-LICENSE.txt")
    download("https://raw.githubusercontent.com/openai/codex/rust-v0.154.0/NOTICE", licenses / "Codex-NOTICE.txt")
    frontend = frontend_licenses(licenses / "frontend")
    (licenses / "packages.json").write_text(json.dumps({"python": dependencies, "frontend": frontend}, ensure_ascii=False, indent=2), encoding="utf-8")
    (licenses / "README.txt").write_text(
        "LIRA includes third-party open source components.\n"
        "Python: https://www.python.org/ (license: runtime/python/LICENSE.txt).\n"
        "Python package licenses: runtime/python/Lib/site-packages/<package>.dist-info/ (and package source folders).\n"
        "Frontend package licenses: THIRD_PARTY/frontend; versions: packages.json.\n"
        "Codex CLI: https://github.com/openai/codex/tree/rust-v0.154.0 (Apache-2.0, LICENSE and NOTICE included).\n"
        "PyMuPDF and MuPDF: AGPL-3.0, https://github.com/pymupdf/PyMuPDF and https://mupdf.com/; see package COPYING files.\n"
        "LIRA application source is included under backend/, frontend/src/, prompts/, and lira.py.\n"
        "This private preview does not grant a separate proprietary license to third-party components.\n", encoding="utf-8")
    errors = audit_files(folder)
    if errors:
        raise RuntimeError("Release audit rejected files:\n" + "\n".join(errors))
    manifest = {"name": args.name, "built_at": datetime.now(timezone.utc).isoformat(),
        "platform": "windows-x64", "python": {"version": PYTHON_VERSION, "url": PYTHON_URL, "sha256": digest(python_zip)},
        "codex": codex, "dependencies": dependencies, "frontend_packages": len(frontend),
        "private_data_included": False, "files": {p.relative_to(folder).as_posix(): digest(p) for p in sorted(folder.rglob("*")) if p.is_file()}}
    (folder / "release.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Creating ZIP...", flush=True)
    archive_path = output / f"{args.name}.zip"
    if archive_path.exists():
        raise RuntimeError(f"Refusing to overwrite existing archive: {archive_path}")
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output))
    checksum = digest(archive_path)
    archive_path.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive_path.name}\n", encoding="ascii")
    print(json.dumps({"zip": str(archive_path), "bytes": archive_path.stat().st_size, "sha256": checksum, "files": len(manifest["files"])}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--name", default="LIRA-2026.11.02-Windows-x64")
    parser.add_argument("--codex-package", type=Path)
    build(parser.parse_args())
