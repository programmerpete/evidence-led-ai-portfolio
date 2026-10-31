"""Synthetic-only lab. Deterministic evidence workflow, not a fraud classifier or LLM."""

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, TypedDict

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.graph import END, START, StateGraph
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from storage import open_database


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


class WorkflowState(TypedDict):
    evidence: list[Evidence]
    findings: list[Finding]
    limitations: list[str]


def draft(state: WorkflowState):
    findings = [
        Finding(text=item.description, citations=[item.id])
        for item in state["evidence"]
        if item.state == "available"
    ]
    limitations = [
        f"{item.id}: {item.state}; not used as current supporting evidence."
        for item in state["evidence"]
        if item.state != "available"
    ]
    limitations.append(
        "Shared devices are investigative leads, not proof of identity or fraud. "
        "No fraud probability, regulatory report or automated customer action is produced."
    )
    return {"findings": findings, "limitations": limitations}


builder = StateGraph(WorkflowState)
builder.add_node("draft_cited_facts", draft)
builder.add_edge(START, "draft_cited_facts")
builder.add_edge("draft_cited_facts", END)
workflow = builder.compile()


def create_app(database: str | None = None) -> FastAPI:
    engine = open_database(database or os.getenv("DATABASE_URL", "investigation.db"))

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Evidence-led investigation lab", version="0.2.0", lifespan=lifespan)

    with engine.begin() as db:
        db.execute(
            text("""
            INSERT INTO cases (id, owner) VALUES
              ('CASE-001', 'analyst-a'), ('CASE-002', 'analyst-b') ON CONFLICT DO NOTHING
        """)
        )
        # Fixed times make late-arrival and freshness demonstrations reproducible.
        rows = [
            (
                "E-001",
                "CASE-001",
                "account-a",
                "device-x",
                "Synthetic account A used device X.",
                "2026-10-20T09:00:00+00:00",
                "2026-10-20T09:01:00+00:00",
                0,
            ),
            (
                "E-002",
                "CASE-001",
                "device-x",
                "account-b",
                "Synthetic account B also used device X; this does not establish common ownership.",
                "2026-10-20T09:05:00+00:00",
                "2026-10-22T12:00:00+00:00",
                0,
            ),
            (
                "E-003",
                "CASE-001",
                "account-b",
                "account-c",
                "Synthetic account B transferred AUD 2400 to account C.",
                "2026-10-20T09:10:00+00:00",
                "2026-10-20T09:11:00+00:00",
                0,
            ),
            (
                "E-004",
                "CASE-001",
                "account-a",
                "restricted-profile",
                "Restricted synthetic profile details.",
                "2026-10-20T08:00:00+00:00",
                "2026-10-20T08:01:00+00:00",
                1,
            ),
        ]
        for row in rows:
            fields = dict(
                zip(
                    (
                        "id",
                        "case_id",
                        "source",
                        "target",
                        "description",
                        "event_time",
                        "known_at",
                        "restricted",
                    ),
                    row,
                    strict=True,
                )
            )
            fields["relationship"] = (
                "profile" if row[7] else "transferred_to" if row[0] == "E-003" else "used_device"
            )
            db.execute(
                text("""
                INSERT INTO evidence_versions
                  (id, version, case_id, source, target, description, event_time, known_at,
                   restricted, relationship, source_system, batch_id)
                VALUES (:id, 1, :case_id, :source, :target, :description, :event_time, :known_at,
                        :restricted, :relationship, 'synthetic-fixture', 'seed-001')
                ON CONFLICT DO NOTHING
            """),
                fields,
            )

    bearer = HTTPBearer(auto_error=False)

    def actor(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        # Public demo identities, intentionally not production authentication.
        identities = {"demo-analyst-a": "analyst-a", "demo-analyst-b": "analyst-b"}
        identity = identities.get(credentials.credentials) if credentials else None
        if identity is None:
            raise HTTPException(401, "Use a documented synthetic demo identity")
        return identity

    def authorize(case_id: str, identity: str):
        with engine.connect() as db:
            row = (
                db.execute(text("SELECT owner FROM cases WHERE id = :id"), {"id": case_id})
                .mappings()
                .first()
            )
        # Do not reveal whether another analyst's case exists.
        if row is None or row["owner"] != identity:
            raise HTTPException(404, "Case not found")

    def audit(db, case_id: str, identity: str, action: str, payload: dict):
        return db.execute(
            text("""
            INSERT INTO audit (case_id, actor, action, payload, recorded_at)
            VALUES (:case_id, :actor, :action, :payload, :recorded_at) RETURNING id
        """),
            {
                "case_id": case_id,
                "actor": identity,
                "action": action,
                "payload": json.dumps(payload),
                "recorded_at": datetime.now(UTC).isoformat(),
            },
        ).scalar_one()

    @app.get("/health")
    def health():
        return {"status": "ok", "data": "synthetic-only"}

    @app.post("/cases/{case_id}/investigate", response_model=Investigation)
    def investigate(case_id: str, request: InvestigationRequest, identity: str = Depends(actor)):
        authorize(case_id, identity)
        with engine.connect() as db:
            rows = (
                db.execute(
                    text(
                        "SELECT * FROM evidence_versions WHERE case_id = :id ORDER BY id, version"
                    ),
                    {"id": case_id},
                )
                .mappings()
                .all()
            )
        # Pick the latest version THEN apply event time; an ineligible correction must
        # not resurrect a superseded fact. Parse offsets rather than comparing timestamp strings.
        versions = {}
        for row in rows:
            if datetime.fromisoformat(row["known_at"]) <= request.as_of:
                versions[row["id"]] = row
        eligible = [
            row
            for row in versions.values()
            if datetime.fromisoformat(row["event_time"]) <= request.as_of
        ]
        frontier = {"account-a"}
        visited = set(frontier)
        evidence: dict[str, Evidence] = {}
        for _ in range(request.max_hops):
            next_nodes = set()
            for row in eligible:
                if row["source"] not in frontier and row["target"] not in frontier:
                    continue
                if row["restricted"]:
                    evidence[row["id"]] = Evidence(
                        id=row["id"], state="denied", description="Access to this source is denied."
                    )
                    continue
                event_time = datetime.fromisoformat(row["event_time"])
                stale = request.as_of - event_time > timedelta(days=7)
                evidence[row["id"]] = Evidence(
                    id=row["id"],
                    state="stale" if stale else "available",
                    description=row["description"],
                    event_time=event_time,
                    known_at=datetime.fromisoformat(row["known_at"]),
                    version=row["version"],
                    source_system=row["source_system"],
                    batch_id=row["batch_id"],
                    relationship=row["relationship"],
                )
                if not stale:
                    next_nodes.update({row["source"], row["target"]} - visited)
            visited.update(next_nodes)
            frontier = next_nodes
        if not evidence:
            evidence["SOURCE-GRAPH"] = Evidence(
                id="SOURCE-GRAPH", state="unknown", description="No visible evidence at this time."
            )
        evidence["SOURCE-WATCHLIST"] = Evidence(
            id="SOURCE-WATCHLIST",
            state="unavailable",
            description="Watchlist integration is not configured in this lab.",
        )
        result = workflow.invoke(
            {"evidence": list(evidence.values()), "findings": [], "limitations": []}
        )
        response = Investigation(case_id=case_id, as_of=request.as_of, **result)
        with engine.begin() as db:
            audit(db, case_id, identity, "investigation", response.model_dump(mode="json"))
        return response

    @app.post("/cases/{case_id}/evidence/{evidence_id}/corrections", status_code=201)
    def correct(
        case_id: str, evidence_id: str, request: Correction, identity: str = Depends(actor)
    ):
        authorize(case_id, identity)
        try:
            with engine.begin() as db:
                current = (
                    db.execute(
                        text("""
                    SELECT * FROM evidence_versions WHERE case_id = :case_id AND id = :id
                    ORDER BY version DESC LIMIT 1
                """),
                        {"case_id": case_id, "id": evidence_id},
                    )
                    .mappings()
                    .first()
                )
                if current is None or current["restricted"]:
                    raise HTTPException(404, "Evidence not found")
                if current["version"] != request.expected_version:
                    raise HTTPException(409, "Evidence changed; reload before correcting")
                known_at = max(
                    datetime.now(UTC),
                    datetime.fromisoformat(current["known_at"]) + timedelta(microseconds=1),
                )
                fields = request.model_dump(mode="json", exclude={"expected_version", "reason"})
                fields.update(
                    id=evidence_id,
                    version=current["version"] + 1,
                    case_id=case_id,
                    known_at=known_at.isoformat(),
                    reason=request.reason,
                )
                db.execute(
                    text("""
                    INSERT INTO evidence_versions
                      (id, version, case_id, source, target, relationship, description, event_time,
                       known_at, restricted, source_system, batch_id, correction_reason)
                    VALUES (:id, :version, :case_id, :source, :target, :relationship, :description,
                            :event_time, :known_at, 0, :source_system, :batch_id, :reason)
                """),
                    fields,
                )
                event_id = audit(db, case_id, identity, "evidence_correction", fields)
            return {
                "id": evidence_id,
                "version": fields["version"],
                "known_at": known_at,
                "audit_id": event_id,
            }
        except IntegrityError as error:
            raise HTTPException(409, "Evidence changed; reload before correcting") from error

    @app.post("/cases/{case_id}/reviews", status_code=201)
    def review(case_id: str, request: Review, identity: str = Depends(actor)):
        authorize(case_id, identity)
        with engine.begin() as db:
            event_id = audit(db, case_id, identity, "human_review", request.model_dump())
        return {"audit_id": event_id, "decision": request.decision, "actor": identity}

    @app.get("/cases/{case_id}/audit")
    def get_audit(case_id: str, identity: str = Depends(actor)):
        authorize(case_id, identity)
        with engine.connect() as db:
            rows = (
                db.execute(
                    text("SELECT * FROM audit WHERE case_id = :id ORDER BY id"), {"id": case_id}
                )
                .mappings()
                .all()
            )
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    return app
