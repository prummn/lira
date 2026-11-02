"""Small, opt-in external evidence lookup for selection questions.

The reader keeps this path separate from the paper corpus.  Results are
temporary snippets used for one answer only; they are never written into the
paper, evidence, or knowledge tables.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..models import PaperChunk

_ENDPOINT = "https://api.openalex.org/works"
_MAX_QUERY = 320
_MAX_SNIPPET = 5000


@dataclass(frozen=True)
class ExternalSnippet:
    title: str
    text: str
    url: str


def _clean(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _abstract(index: Any) -> str:
    if not isinstance(index, dict):
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                words.append((position, word))
    return " ".join(word for _, word in sorted(words))


def _openalex_results(payload: Any) -> list[ExternalSnippet]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return []
    snippets: list[ExternalSnippet] = []
    for item in payload["results"]:
        if not isinstance(item, dict):
            continue
        title = _clean(item.get("title"), 300)
        abstract = _clean(_abstract(item.get("abstract_inverted_index")), _MAX_SNIPPET)
        location = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
        url = _clean(location.get("landing_page_url"), 1000) or _clean(item.get("id"), 1000)
        if not title or not abstract or not url.startswith("https://"):
            continue
        year = item.get("publication_year")
        venue = item.get("primary_location", {}).get("source", {}).get("display_name") if isinstance(item.get("primary_location"), dict) and isinstance(item.get("primary_location", {}).get("source"), dict) else ""
        label = " · ".join(str(value) for value in (year, _clean(venue, 160)) if value)
        prefix = f"{title} ({label})" if label else title
        snippets.append(ExternalSnippet(title, f"{prefix}\n{abstract}", url))
    return snippets


def search_external(query: str, *, transport: httpx.BaseTransport | None = None, limit: int = 5) -> list[ExternalSnippet]:
    query = _clean(query, _MAX_QUERY)
    if len(query) < 3:
        return []
    try:
        with httpx.Client(
            transport=transport or httpx.HTTPTransport(retries=0, trust_env=False),
            timeout=httpx.Timeout(8.0, connect=3.0),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json", "User-Agent": "ResearchIntelligenceWorkspace/0.3"},
        ) as client:
            response = client.get(_ENDPOINT, params={"search": query, "per-page": max(1, min(limit, 8))})
            if response.status_code != 200:
                return []
            payload = response.json()
    except (httpx.HTTPError, ValueError, OSError, TypeError):
        return []
    snippets = _openalex_results(payload)
    if not snippets and "exact match" not in query.casefold() and re.search(r"\bEM\b", query):
        # Acronyms are often omitted from bibliographic abstracts.  A single
        # refined query makes definitions such as EM → exact match discoverable
        # without turning every selection into a multi-request web search.
        return search_external(f"{query} exact match", transport=transport, limit=limit)
    if snippets:
        return snippets
    return []


def transient_chunks(paper_id: str, snippets: list[ExternalSnippet]) -> list[PaperChunk]:
    """Turn snippets into provider-compatible, non-persistent chunks."""
    chunks: list[PaperChunk] = []
    for snippet in snippets:
        digest = hashlib.sha256(snippet.url.encode("utf-8")).hexdigest()[:24]
        chunk = PaperChunk(
            id=f"external-{digest}",
            paper_id=paper_id,
            page=None,
            section="External source",
            content=snippet.text,
            bbox_json=None,
            page_width=None,
            page_height=None,
        )
        # SQLAlchemy models are regular Python objects; these attributes are
        # deliberately transient and are copied to the response only.
        chunk.source_url = snippet.url  # type: ignore[attr-defined]
        chunk.source_type = "external"  # type: ignore[attr-defined]
        chunks.append(chunk)
    return chunks
