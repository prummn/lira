"""Typed scope and provenance for the read-only library assistant."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .schemas import GeometryModel


class ConversationTurn(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=8000)


class LibraryQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    collection_id: str | None = Field(default=None, max_length=64)
    paper_ids: list[str] | None = Field(default=None, min_length=1, max_length=50)
    history: list[ConversationTurn] = Field(default_factory=list, max_length=12)

    @field_validator('question')
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('问题不能为空')
        return value.strip()


class LibraryCitation(GeometryModel):
    id: str
    paper_id: str
    title: str
    source_id: str
    source_text: str
    source_type: Literal['paper', 'external_metadata', 'user', 'ai']
    page: int | None = None
    section: str | None = None
    chunk_id: str | None = None
    page_width: float | None = None
    page_height: float | None = None


class LibraryAnswerItem(BaseModel):
    content: str
    kind: Literal['fact', 'comparison', 'inference', 'user_note', 'metadata']
    citations: list[LibraryCitation]


class LibraryAnswer(BaseModel):
    answer: str
    items: list[LibraryAnswerItem]
    citations: list[LibraryCitation]
    provider: str
    mode: str
    model: str | None = None
    insufficient_evidence: bool
    limitations: list[str]
    retrieved_paper_ids: list[str]
    queries: list[str]
    coverage: dict
    usage: dict
    cached: bool
