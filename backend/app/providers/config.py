"""Local model configuration persistence for the in-app settings form."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

MODEL_ENV_KEYS = (
    "PAPER_READER_MODEL_BASE_URL",
    "PAPER_READER_MODEL_NAME",
    "PAPER_READER_MODEL_API_KEY",
    "PAPER_READER_MODEL_WIRE_API",
    "PAPER_READER_MODEL_REASONING_EFFORT",
    "PAPER_READER_MODEL_TIMEOUT",
)


def _env_line(name: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{name}="{escaped}"'


def persist_model_config(path: Path, values: dict[str, str]) -> None:
    """Update only model keys in the local env file, preserving other settings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    replacements = {key: values[key] for key in MODEL_ENV_KEYS if key in values}
    seen: set[str] = set()
    output: list[str] = []
    for line in existing:
        stripped = line.lstrip()
        matched = next((key for key in replacements if stripped.startswith(key + "=")), None)
        if matched is None:
            output.append(line)
            continue
        output.append(_env_line(matched, replacements[matched]))
        seen.add(matched)
    if output and output[-1].strip():
        output.append("")
    output.extend(_env_line(key, value) for key, value in replacements.items() if key not in seen)
    content = "\n".join(output).rstrip() + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix="paper-reader-model-", suffix=".env", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clear_model_config(path: Path) -> None:
    persist_model_config(path, {key: "" for key in MODEL_ENV_KEYS})
