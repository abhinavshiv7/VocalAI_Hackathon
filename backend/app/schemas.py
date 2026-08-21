from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class InvestigationStatus(StrEnum):
    CREATED = "CREATED"
    DISCOVERING = "DISCOVERING"
    HYPOTHESIS_GENERATED = "HYPOTHESIS_GENERATED"
    INVESTIGATING = "INVESTIGATING"
    CRITIC_REVIEW = "CRITIC_REVIEW"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    VALIDATED = "VALIDATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class HypothesisStatus(StrEnum):
    HYPOTHESIS = "HYPOTHESIS"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    REJECTED = "REJECTED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    VALIDATED = "VALIDATED"


class ToolRequest(BaseModel):
    action: Literal["run_security_tool"] = "run_security_tool"
    tool: Literal["network_discovery", "web_inspection"]
    target_id: str
    scope: Literal["authorized"] = "authorized"
    operation: Literal["read_only"] = "read_only"
    path: str = "/"
    reason: str = Field(min_length=8, max_length=500)

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        if not value.startswith("/") or ".." in value or "://" in value:
            raise ValueError("path must be a local absolute URL path")
        return value


class HypothesisDraft(BaseModel):
    title: str
    description: str
    reason: str
    confidence: float = Field(ge=0, le=1)
    required_evidence: list[str]
    tool_request: ToolRequest


class InvestigatorOutput(BaseModel):
    hypotheses: list[HypothesisDraft] = Field(min_length=1, max_length=5)
    reasoning_summary: str


class CriticOutput(BaseModel):
    decision: Literal[
        "validated", "rejected", "needs_more_evidence", "human_review"
    ]
    confidence: float = Field(ge=0, le=1)
    missing_evidence: list[str] = []
    contradictions: list[str] = []
    reason: str


class InvestigationCreate(BaseModel):
    target_id: str = "lab-web-01"


class FailureInjection(BaseModel):
    kind: Literal["none", "tool", "model", "malformed_output"] = "none"
    subject: str | None = None
    enabled: bool = True


class TargetView(BaseModel):
    id: str
    name: str
    environment: str
    host: str
    port: int
    base_url: str
    authorized: bool
    allowed_tools: list[str]


class HealthView(BaseModel):
    status: str
    database: str
    ai_mode: str
    timestamp: datetime


class EvaluationSummary(BaseModel):
    scenarios: int
    correct_conclusions: int
    false_positives: int
    false_confidence: int
    graceful_failures: int
    success_rate: float
    graceful_failure_rate: float
    results: list[dict[str, Any]]

