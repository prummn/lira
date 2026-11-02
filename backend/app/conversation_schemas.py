"""Local conversation identifiers and archive contracts."""
from typing import Literal
from pydantic import BaseModel, Field

ChatKind = Literal['paper', 'explanation', 'librarian']


class ChatRequest(BaseModel):
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)
    request_id: str | None = Field(default=None, min_length=1, max_length=64)


class ChatResponse(BaseModel):
    conversation_id: str | None = None
    turn_id: str | None = None


class ConversationCreate(BaseModel):
    kind: ChatKind
    paper_id: str | None = Field(default=None, max_length=64)
    context: dict = Field(default_factory=dict)
