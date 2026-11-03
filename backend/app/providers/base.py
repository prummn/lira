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

    def public_payload(self) -> dict:
        codes = {
            'provider_error', 'authentication', 'invalid_request', 'invalid_response',
            'invalid_image', 'rate_limit', 'upstream_error', 'upstream_timeout',
            'output_budget', 'output_incomplete', 'stream_interrupted', 'local_capacity',
            'transport_timeout', 'transport_protocol', 'transport_connection',
            'transport_dns', 'transport_refused', 'transport_reset', 'transport_tls',
            'transport_unreachable', 'tls_certificate', 'tls_configuration', 'transport_error',
            'codex_unavailable', 'codex_account_error', 'codex_catalog_error',
            'background_preempted', 'subscription_required', 'science_support',
        }
        upstream = {'rate_limit', 'rate_limit_error', 'rate_limit_exceeded', 'server_error',
                    'api_error', 'overloaded_error', 'invalid_api_key', 'authentication_error',
                    'permission_denied', 'invalid_request_error', 'missing', 'unknown'}
        enums = {
            'transport_type': {'ConnectError', 'ReadError', 'WriteError', 'CloseError',
                              'ConnectTimeout', 'ReadTimeout', 'WriteTimeout', 'PoolTimeout',
                              'RemoteProtocolError', 'unknown'},
            'upstream_code': upstream, 'upstream_type': upstream,
            'event_type': {'error', 'response.failed', 'response.incomplete'},
            'validation': {'answer_citations'},
        }
        diagnostics = {}
        for key, value in self.diagnostics.items():
            if key in enums and type(value) is str and value in enums[key]:
                diagnostics[key] = value
            elif key == 'http_status' and type(value) is int and 100 <= value <= 599:
                diagnostics[key] = value
            elif key == 'tls_verify_code' and type(value) is int and 0 <= value <= 1000:
                diagnostics[key] = value
            elif key == 'request_sent' and type(value) is bool:
                diagnostics[key] = value
        return {'detail': str(self),
                'code': self.code if type(self.code) is str and self.code in codes else 'provider_error',
                'retryable': self.retryable is True, 'diagnostics': diagnostics}


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
class KnowledgeCandidateEntry:
    entity_type: str
    name: str
    normalized_name: str
    aliases: list[str]
    description: str | None
    role: str
    confidence: float
    citations: list[VerifiedCitation]


@dataclass
class KnowledgeRelationEntry:
    relation: str
    source_name: str
    source_normalized_name: str
    target_name: str
    target_normalized_name: str
    description: str | None
    confidence: float
    citations: list[VerifiedCitation]


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
    knowledge_candidates: list[KnowledgeCandidateEntry] = field(default_factory=list)
    knowledge_relations: list[KnowledgeRelationEntry] = field(default_factory=list)
    model_version: str | None = None
    prompt_version: str | None = None


@dataclass
class AnswerResult:
    answer: str
    chunks: list[PaperChunk]
    insufficient_evidence: bool
    citations: list[VerifiedCitation] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    inferences: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    needs_more_context: bool = False


class ModelProvider(Protocol):
    name: str
    mode: str
    configured: bool
    translation_available: bool

    def analyze(self, chunks: list[PaperChunk]) -> AnalysisResult: ...
    def ask(self, question: str, chunks: list[PaperChunk]) -> AnswerResult: ...
    def ask_with_image(self, question: str, chunks: list[PaperChunk], image_data_url: str) -> AnswerResult: ...
    def translate(self, chunk: PaperChunk) -> str: ...

    def audit_knowledge_bundle(self, bundle: dict) -> dict: ...


class MetadataProvider(Protocol):
    """Interface only: no real provider/network metadata resolution is installed."""

    def resolve(
        self, doi: str | None, arxiv_id: str | None
    ) -> dict[str, object] | None: ...


class EmbeddingProvider(Protocol):
    """Interface only: MVP full-text retrieval does not invoke embeddings."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...
