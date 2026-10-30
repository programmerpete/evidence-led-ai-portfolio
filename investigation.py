"""Synthetic-only lab. Deterministic evidence workflow, not a fraud classifier or LLM."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, TypedDict

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.graph import END, START, StateGraph
from pydantic import AwareDatetime, BaseModel, Field


class InvestigationRequest(BaseModel):
    as_of: AwareDatetime
    max_hops: int = Field(default=2, ge=1, le=3)


class Evidence(BaseModel):
    id: str
    state: Literal["available", "unknown", "stale", "denied", "unavailable"]
    description: str
    event_time: AwareDatetime | None = None
    known_at: AwareDatetime | None = None


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


def create_app(database: str = "investigation.db") -> FastAPI:
    app = FastAPI(title="Evidence-led investigation lab", version="0.1.0")

    @contextmanager
    def connect():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, owner TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, source TEXT NOT NULL,
                target TEXT NOT NULL, description TEXT NOT NULL,
                event_time TEXT NOT NULL, known_at TEXT NOT NULL,
                restricted INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, case_id TEXT NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO cases VALUES ('CASE-001', 'analyst-a');
            INSERT OR IGNORE INTO cases VALUES ('CASE-002', 'analyst-b');
        """)
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
        db.executemany("INSERT OR IGNORE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

    bearer = HTTPBearer(auto_error=False)

    def actor(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        # Public demo identities, intentionally not production authentication.
        identities = {"demo-analyst-a": "analyst-a", "demo-analyst-b": "analyst-b"}
        identity = identities.get(credentials.credentials) if credentials else None
        if identity is None:
            raise HTTPException(401, "Use a documented synthetic demo identity")
        return identity

    def authorize(case_id: str, identity: str):
        with connect() as db:
            row = db.execute("SELECT owner FROM cases WHERE id = ?", (case_id,)).fetchone()
        # Do not reveal whether another analyst's case exists.
        if row is None or row["owner"] != identity:
            raise HTTPException(404, "Case not found")

    def audit(case_id: str, identity: str, action: str, payload: dict):
        with connect() as db:
            cursor = db.execute(
                "INSERT INTO audit (case_id, actor, action, payload, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    case_id,
                    identity,
                    action,
                    json.dumps(payload),
                    datetime.now(UTC).isoformat(),
                ),
            )
            return cursor.lastrowid

    @app.get("/health")
    def health():
        return {"status": "ok", "data": "synthetic-only"}

    @app.post("/cases/{case_id}/investigate", response_model=Investigation)
    def investigate(case_id: str, request: InvestigationRequest, identity: str = Depends(actor)):
        authorize(case_id, identity)
        with connect() as db:
            rows = db.execute(
                "SELECT * FROM evidence WHERE case_id = ? ORDER BY id", (case_id,)
            ).fetchall()
        # Filter knowledge AND event time before traversal. Future/denied links cannot bridge nodes.
        eligible = [
            row
            for row in rows
            if datetime.fromisoformat(row["known_at"]) <= request.as_of
            and datetime.fromisoformat(row["event_time"]) <= request.as_of
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
        audit(case_id, identity, "investigation", response.model_dump(mode="json"))
        return response

    @app.post("/cases/{case_id}/reviews", status_code=201)
    def review(case_id: str, request: Review, identity: str = Depends(actor)):
        authorize(case_id, identity)
        event_id = audit(case_id, identity, "human_review", request.model_dump())
        return {"audit_id": event_id, "decision": request.decision, "actor": identity}

    @app.get("/cases/{case_id}/audit")
    def get_audit(case_id: str, identity: str = Depends(actor)):
        authorize(case_id, identity)
        with connect() as db:
            rows = db.execute(
                "SELECT * FROM audit WHERE case_id = ? ORDER BY id", (case_id,)
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    return app
