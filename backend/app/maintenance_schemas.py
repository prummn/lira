"""API contracts for persistent knowledge-network maintenance runs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MaintenanceRunStatus = Literal["queued", "running", "complete", "partial", "failed", "cancelled"]
MaintenanceIssueStatus = Literal[
    "proposed", "auto_applied", "needs_review", "accepted", "rejected", "stale", "undone"
]
MaintenanceKind = Literal["identity", "relation", "evidence", "coverage", "importance", "structure"]
MaintenanceSeverity = Literal["critical", "warning", "info"]


class MaintenanceRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: Literal["library", "collection", "papers"] = "library"
    scope_id: str | None = Field(default=None, min_length=1, max_length=64)
    paper_ids: list[str] = Field(default_factory=list, max_length=200)
    allow_external: bool = False
    force: bool = False

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope_type == "collection" and not self.scope_id:
            raise ValueError("专题范围需要提供专题 ID")
        if self.scope_type == "papers" and not self.paper_ids:
            raise ValueError("论文范围至少需要一篇论文")
        if self.scope_type != "papers" and self.paper_ids:
            raise ValueError("只有论文范围可以提供 paper_ids")
        return self


class MaintenanceRunRead(BaseModel):
    id: str
    scope_type: str
    scope_id: str | None = None
    status: MaintenanceRunStatus
    allow_external: bool
    model_name: str | None = None
    prompt_version: str | None = None
    source_fingerprint: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    safe_count: int = 0
    review_count: int = 0
    conflict_count: int = 0
    applied_count: int = 0
    usage: dict = Field(default_factory=dict)


class MaintenanceIssueRead(BaseModel):
    id: str
    run_id: str
    kind: MaintenanceKind
    severity: MaintenanceSeverity
    status: MaintenanceIssueStatus
    confidence: float = Field(ge=0, le=1)
    confidence_basis: dict = Field(default_factory=dict)
    auto_eligible: bool
    subject_ids: list[str] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    external_leads: list[dict] = Field(default_factory=list)
    summary: str
    reasoning: str
    proposed_action: dict = Field(default_factory=dict)
    source_fingerprint: str
    applied_change_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MaintenanceRunDetail(MaintenanceRunRead):
    issues: list[MaintenanceIssueRead] = Field(default_factory=list)


class MaintenanceActionResult(BaseModel):
    issue: MaintenanceIssueRead
    run: MaintenanceRunRead

