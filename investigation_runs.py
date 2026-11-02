"""Durable synthetic review workflow; no external actions or background worker."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TypedDict
from uuid import uuid4

from fastapi import HTTPException
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import text

from contracts import Investigation, InvestigationRun
from decision_support import assess


class RunState(TypedDict):
    investigation: dict
    review: dict
    request_advice: bool


class InvestigationRuns:
    def __init__(self, engine, collect_evidence, authorize, audit, draft):
        self.engine = engine
        self.collect_evidence = collect_evidence
        self.authorize = authorize
        self.audit = audit

        def draft_snapshot(state):
            snapshot = Investigation.model_validate(state["investigation"])
            result = draft({"evidence": snapshot.evidence, "findings": [], "limitations": []})
            snapshot.findings = result["findings"]
            snapshot.limitations = result["limitations"]
            return {"investigation": snapshot.model_dump(mode="json")}

        def model_advice(state):
            snapshot = Investigation.model_validate(state["investigation"])
            if state.get("request_advice"):
                snapshot.model_assessment = assess(snapshot)
            return {"investigation": snapshot.model_dump(mode="json")}

        def human_review(state):
            # On resume this node runs again. Keep all side effects outside it.
            decision = interrupt({"message": "Review the frozen investigation snapshot."})
            return {"review": decision}

        self.builder = StateGraph(RunState)
        self.builder.add_node("draft_cited_facts", draft_snapshot)
        self.builder.add_node("model_advice", model_advice)
        self.builder.add_node("human_review", human_review)
        self.builder.add_edge(START, "draft_cited_facts")
        self.builder.add_edge("draft_cited_facts", "model_advice")
        self.builder.add_edge("model_advice", "human_review")
        self.builder.add_edge("human_review", END)

    @contextmanager
    def workflow(self):
        if self.engine.dialect.name == "postgresql":
            url = self.engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
            with PostgresSaver.from_conn_string(url) as saver:
                saver.setup()
                yield self.builder.compile(checkpointer=saver)
        else:
            with SqliteSaver.from_conn_string(self.engine.url.database) as saver:
                yield self.builder.compile(checkpointer=saver)

    def get(self, case_id, run_id, identity):
        self.authorize(case_id, identity)
        with self.engine.connect() as db:
            row = (
                db.execute(
                    text("SELECT * FROM investigation_runs WHERE case_id = :case AND id = :id"),
                    {"case": case_id, "id": run_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise HTTPException(404, "Run not found")
        fields = dict(row)
        fields["investigation"] = json.loads(fields.pop("snapshot"))
        return InvestigationRun.model_validate(fields)

    def list(self, case_id, identity):
        self.authorize(case_id, identity)
        with self.engine.connect() as db:
            ids = (
                db.execute(
                    text("""SELECT id FROM investigation_runs WHERE case_id = :case
                        ORDER BY created_at DESC, id DESC LIMIT 20"""),
                    {"case": case_id},
                )
                .scalars()
                .all()
            )
        return [self.get(case_id, run_id, identity) for run_id in ids]

    def start(self, case_id, request, identity):
        evidence = self.collect_evidence(case_id, request, identity)
        initial = Investigation(
            case_id=case_id, as_of=request.as_of, evidence=evidence, findings=[], limitations=[]
        )
        run_id = str(uuid4())
        with self.workflow() as graph:
            result = graph.invoke(
                {
                    "investigation": initial.model_dump(mode="json"),
                    "request_advice": request.request_advice,
                },
                {"configurable": {"thread_id": run_id}},
            )
        with self.engine.begin() as db:
            db.execute(
                text("""INSERT INTO investigation_runs
                (id, case_id, status, snapshot, created_at)
                VALUES (:id, :case, 'awaiting_review', :snapshot, :created)"""),
                {
                    "id": run_id,
                    "case": case_id,
                    "snapshot": json.dumps(result["investigation"]),
                    "created": datetime.now(UTC).isoformat(),
                },
            )
            self.audit(
                db,
                case_id,
                identity,
                "run_started",
                {"run_id": run_id, "investigation": result["investigation"]},
            )
        return self.get(case_id, run_id, identity)

    def review(self, case_id, run_id, request, identity):
        self.get(case_id, run_id, identity)  # Authorize before looking up or changing state.
        values = {
            "id": run_id,
            "case": case_id,
            "actor": identity,
            "decision": request.decision,
            "rationale": request.rationale,
        }
        with self.engine.begin() as db:
            claimed = db.execute(
                text("""UPDATE investigation_runs
                SET status = 'review_pending', reviewer = :actor,
                    review_decision = :decision, review_rationale = :rationale
                WHERE id = :id AND case_id = :case AND status = 'awaiting_review'"""),
                values,
            )
            if claimed.rowcount:
                self.audit(
                    db,
                    case_id,
                    identity,
                    "human_review",
                    {"run_id": run_id, **request.model_dump()},
                )
            else:
                row = (
                    db.execute(
                        text("SELECT * FROM investigation_runs WHERE id = :id"), {"id": run_id}
                    )
                    .mappings()
                    .one()
                )
                if (row["reviewer"], row["review_decision"], row["review_rationale"]) != (
                    identity,
                    request.decision,
                    request.rationale,
                ):
                    raise HTTPException(409, "This run already has a different review")

        # Decision + audit commit BEFORE resume. If the process stops, retrying the same
        # decision resumes from the durable checkpoint; it cannot introduce a new review.
        config = {"configurable": {"thread_id": run_id}}
        decision = {"actor": identity, **request.model_dump()}
        with self.workflow() as graph:
            checkpoint = graph.get_state(config)
            if checkpoint.next:
                graph.invoke(Command(resume=decision), config)
                checkpoint = graph.get_state(config)
            if checkpoint.next or checkpoint.values.get("review") != decision:
                raise HTTPException(409, "Run checkpoint needs recovery; review remains saved")
        with self.engine.begin() as db:
            updated = db.execute(
                text("""UPDATE investigation_runs
                SET status = 'reviewed', reviewed_at = :time
                WHERE id = :id AND status = 'review_pending'"""),
                {"id": run_id, "time": datetime.now(UTC).isoformat()},
            )
            if updated.rowcount:
                self.audit(db, case_id, identity, "run_reviewed", {"run_id": run_id})
        return self.get(case_id, run_id, identity)
