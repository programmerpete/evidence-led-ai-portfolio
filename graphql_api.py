"""GraphQL transport for the same operations used by the REST routes."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Annotated

import strawberry
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from graphql import GraphQLError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from strawberry.extensions import MaxAliasesLimiter, MaxTokensLimiter, QueryDepthLimiter
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON
from strawberry.types import Info

from contracts import Correction, InvestigationRequest, Review


@strawberry.type(name="Evidence")
class EvidenceResult:
    id: str
    state: str
    description: str
    event_time: datetime | None
    known_at: datetime | None
    version: int | None
    source_system: str | None
    batch_id: str | None
    relationship: str | None


@strawberry.type(name="Finding")
class FindingResult:
    text: str
    citations: list[str]


@strawberry.type(name="Investigation")
class InvestigationResult:
    case_id: str
    as_of: datetime
    evidence: list[EvidenceResult]
    findings: list[FindingResult]
    limitations: list[str]
    requires_human_review: bool


@strawberry.input
class InvestigationInput:
    as_of: datetime
    max_hops: int = 2


@strawberry.input
class ReviewInput:
    decision: str
    rationale: str


@strawberry.input
class CorrectionInput:
    expected_version: int
    source: str
    target: str
    relationship: str
    description: str
    event_time: datetime
    source_system: str
    batch_id: str
    reason: str


@strawberry.type
class ReviewResult:
    audit_id: int
    decision: str
    actor: str


@strawberry.type
class CorrectionResult:
    id: str
    version: int
    known_at: datetime
    audit_id: int


@strawberry.type
class AuditEvent:
    id: int
    case_id: str
    actor: str
    action: str
    payload: JSON
    recorded_at: datetime


@contextmanager
def graphql_errors():
    try:
        yield
    except HTTPException as error:
        codes = {401: "UNAUTHENTICATED", 404: "NOT_FOUND", 409: "CONFLICT"}
        raise GraphQLError(
            str(error.detail),
            extensions={"code": codes[error.status_code], "status": error.status_code},
        ) from error
    except ValidationError as error:
        # Do not echo input values or internal exception details to the caller.
        raise GraphQLError(
            "Invalid input: "
            + "; ".join(
                f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors()
            ),
            extensions={"code": "BAD_USER_INPUT", "status": 422},
        ) from error


def create_graphql_router(investigate, correct, review, get_audit, actor, bearer):
    # Leave the IDE public; authenticate every data operation using the REST identity policy.
    def context(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        return {"credentials": credentials}

    @strawberry.type
    class Query:
        @strawberry.field
        async def audit(self, info: Info, case_id: str) -> list[AuditEvent]:
            with graphql_errors():
                identity = actor(info.context["credentials"])
                events = await run_in_threadpool(get_audit, case_id, identity)
                return [
                    AuditEvent(
                        **{**event, "recorded_at": datetime.fromisoformat(event["recorded_at"])}
                    )
                    for event in events
                ]

    @strawberry.type
    class Mutation:
        @strawberry.mutation(description="Run an investigation and persist its audit snapshot.")
        async def investigate(
            self, info: Info, case_id: str, input: InvestigationInput
        ) -> InvestigationResult:
            with graphql_errors():
                identity = actor(info.context["credentials"])
                request = InvestigationRequest.model_validate(asdict(input))
                result = await run_in_threadpool(investigate, case_id, request, identity)
                return InvestigationResult(
                    **result.model_dump(exclude={"evidence", "findings"}),
                    evidence=[EvidenceResult(**item.model_dump()) for item in result.evidence],
                    findings=[FindingResult(**item.model_dump()) for item in result.findings],
                )

        @strawberry.mutation
        async def review(self, info: Info, case_id: str, input: ReviewInput) -> ReviewResult:
            with graphql_errors():
                identity = actor(info.context["credentials"])
                request = Review.model_validate(asdict(input))
                result = await run_in_threadpool(review, case_id, request, identity)
                return ReviewResult(**result)

        @strawberry.mutation
        async def correct_evidence(
            self, info: Info, case_id: str, evidence_id: str, input: CorrectionInput
        ) -> CorrectionResult:
            with graphql_errors():
                identity = actor(info.context["credentials"])
                request = Correction.model_validate(asdict(input))
                result = await run_in_threadpool(correct, case_id, evidence_id, request, identity)
                return CorrectionResult(**result)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        extensions=[
            lambda: QueryDepthLimiter(max_depth=6),
            lambda: MaxAliasesLimiter(max_alias_count=5),
            lambda: MaxTokensLimiter(max_token_count=2000),
        ],
    )
    return GraphQLRouter(schema, context_getter=context, allow_queries_via_get=False)
