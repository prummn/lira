"""Provider boundaries; remote metadata and embeddings are intentionally unconnected."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol
from ..models import PaperChunk


class ProviderError(RuntimeError):
    """Safe user-visible failure; never embeds upstream bodies, URLs, or keys."""
    def __init__(self, message: str, status_code: int = 502, *, code: str = 'provider_error', retryable: bool = False, retry_after: float | None = None, diagnostics: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        self.diagnostics = diagnostics or {}


@dataclass(frozen=True)
class VerifiedCitation:
    chunk: PaperChunk
    source_text: str
    claim: str
    source_type: str


@dataclass
class CardEntry:
    content: str
    citations: list[VerifiedCitation]
    section: str | None = None


@dataclass
class AnalysisResult:
    one_liner: str | None = None
    problem: str | None = None
    method: str | None = None
    findings: str | None = None
    limitations: str | None = None
    concepts: list[str] = field(default_factory=list)
    evidence_chunks: list[PaperChunk] = field(default_factory=list)
    citations: list[VerifiedCitation] = field(default_factory=list)
    card: dict[str, CardEntry | list[CardEntry] | None] = field(default_factory=dict)
    model_version: str | None = None
    prompt_version: str | None = None


@dataclass
class AnswerResult:
    answer: str
    chunks: list[PaperChunk]
    insufficient_evidence: bool
    citations: list[VerifiedCitation] = field(default_factory=list)


class ModelProvider(Protocol):
    name: str
    mode: str
    configured: bool
    translation_available: bool

    def analyze(self, chunks: list[PaperChunk]) -> AnalysisResult: ...
    def ask(self, question: str, chunks: list[PaperChunk]) -> AnswerResult: ...
    def translate(self, chunk: PaperChunk) -> str: ...


class MetadataProvider(Protocol):
    """Interface only: no real provider/network metadata resolution is installed."""

    def resolve(
        self, doi: str | None, arxiv_id: str | None
    ) -> dict[str, object] | None: ...


class EmbeddingProvider(Protocol):
    """Interface only: MVP full-text retrieval does not invoke embeddings."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...
