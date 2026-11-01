"""Validation contracts shared by REST and GraphQL."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class InvestigationRequest(BaseModel):
    as_of: AwareDatetime
    max_hops: int = Field(default=2, ge=1, le=3)


class Evidence(BaseModel):
    id: str
    state: Literal["available", "unknown", "stale", "denied", "unavailable"]
    description: str
    event_time: AwareDatetime | None = None
    known_at: AwareDatetime | None = None
    version: int | None = None
    source_system: str | None = None
    batch_id: str | None = None
    relationship: Literal["used_device", "transferred_to", "profile"] | None = None


class Finding(BaseModel):
    text: str
    citations: list[str]


class Investigation(BaseModel):
    case_id: str
    as_of: AwareDatetime
    evidence: list[Evidence]
    findings: list[Finding]
    limitations: list[str]
    requires_human_review: Literal[True] = True


class Review(BaseModel):
    decision: Literal["escalate", "close", "request_information"]
    rationale: str = Field(min_length=10, max_length=2000, pattern=r"\S")


class Correction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    relationship: Literal["used_device", "transferred_to", "profile"]
    description: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    event_time: AwareDatetime
    source_system: str = Field(min_length=1, max_length=100)
    batch_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=10, max_length=2000, pattern=r"\S")
