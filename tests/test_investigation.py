import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from investigation import create_app


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("TEST_DATABASE_URL") else []))
def database(request, tmp_path):
    if request.param == "sqlite":
        yield str(tmp_path / "test.db")
        return
    # TEST_DATABASE_URL must point to a disposable test database, never real data.
    schema = f"test_{uuid4().hex}"
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    url = make_url(os.environ["TEST_DATABASE_URL"]).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with engine.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.fixture
def client(database):
    with TestClient(create_app(database)) as client:
        client.headers["Authorization"] = "Bearer demo-analyst-a"
        yield client


@pytest.mark.parametrize(
    "as_of,hops,expected",
    [
        ("2026-10-19T00:00:00Z", 3, set()),
        ("2026-10-21T12:00:00Z", 3, {"E-001"}),
        ("2026-10-22T12:00:00Z", 1, {"E-001"}),
        ("2026-10-22T12:00:00Z", 2, {"E-001", "E-002"}),
        ("2026-10-22T12:00:00Z", 3, {"E-001", "E-002", "E-003"}),
        ("2026-10-27T09:00:00Z", 1, {"E-001"}),
        ("2026-10-27T09:00:01Z", 3, set()),
    ],
)
def test_cited_facts_respect_knowledge_time_hop_limit_and_freshness(client, as_of, hops, expected):
    response = client.post("/cases/CASE-001/investigate", json={"as_of": as_of, "max_hops": hops})
    assert response.status_code == 200
    body = response.json()
    assert {
        citation for finding in body["findings"] for citation in finding["citations"]
    } == expected
    assert body["requires_human_review"] is True
    assert all(item["state"] == "available" for item in body["evidence"] if item["id"] in expected)
    assert "Restricted synthetic profile details" not in response.text
    assert "restricted-profile" not in response.text


def test_explicit_states_and_no_automatic_decision(client):
    body = client.post("/cases/CASE-001/investigate", json={"as_of": "2026-10-30T00:00:00Z"}).json()
    assert {item["state"] for item in body["evidence"]} == {"stale", "denied", "unavailable"}
    assert body["findings"] == []
    assert [event["action"] for event in client.get("/cases/CASE-001/audit").json()] == [
        "investigation"
    ]
    early = client.post(
        "/cases/CASE-001/investigate", json={"as_of": "2026-10-01T00:00:00Z"}
    ).json()
    assert {item["state"] for item in early["evidence"]} == {"unknown", "unavailable"}


@pytest.mark.parametrize(
    "endpoint,method,payload",
    [
        ("investigate", "post", {"as_of": "2026-10-22T12:00:00Z"}),
        ("reviews", "post", {"decision": "close", "rationale": "Reviewed synthetic evidence."}),
        ("audit", "get", None),
    ],
)
def test_case_access_on_every_route(client, endpoint, method, payload):
    kwargs = {"json": payload} if payload else {}
    response = getattr(client, method)(f"/cases/CASE-002/{endpoint}", **kwargs)
    assert response.status_code == 404
    client.headers.pop("Authorization")
    assert getattr(client, method)(f"/cases/CASE-001/{endpoint}", **kwargs).status_code == 401


def test_review_is_durable_and_attributed(database):
    headers = {"Authorization": "Bearer demo-analyst-a"}
    with TestClient(create_app(database), headers=headers) as client:
        response = client.post(
            "/cases/CASE-001/reviews",
            json={
                "decision": "request_information",
                "rationale": "Need to verify the shared device lead.",
            },
        )
        assert response.status_code == 201
    with TestClient(create_app(database), headers=headers) as reopened:
        events = reopened.get("/cases/CASE-001/audit").json()
        assert len(events) == 1
        assert events[0]["actor"] == "analyst-a"
        assert events[0]["action"] == "human_review"
        assert events[0]["payload"]["decision"] == "request_information"


@pytest.mark.parametrize(
    "payload",
    [
        {"as_of": "2026-10-22T12:00:00"},
        {"as_of": "2026-10-22T12:00:00Z", "max_hops": 4},
        {"as_of": "2026-10-22T12:00:00Z", "max_hops": 0},
    ],
)
def test_tool_input_boundaries(client, payload):
    assert client.post("/cases/CASE-001/investigate", json=payload).status_code == 422


CORRECTION = {
    "expected_version": 1,
    "source": "account-a",
    "target": "device-x",
    "relationship": "used_device",
    "description": "Corrected synthetic device observation from source reconciliation.",
    "event_time": "2026-10-20T09:00:00Z",
    "source_system": "synthetic-reconciliation",
    "batch_id": "correction-batch-002",
    "reason": "Reconciled the observation with the synthetic source.",
}
CORRECTION_URL = "/cases/CASE-001/evidence/E-001/corrections"


def test_correction_replays_original_and_switches_at_knowledge_boundary(client):
    historical = {"as_of": "2026-10-22T12:00:00Z", "max_hops": 3}
    original = client.post("/cases/CASE-001/investigate", json=historical).json()
    response = client.post(CORRECTION_URL, json=CORRECTION)
    assert response.status_code == 201
    assert response.json()["version"] == 2
    known_at = datetime.fromisoformat(response.json()["known_at"])
    assert client.post("/cases/CASE-001/investigate", json=historical).json() == original
    for cutoff, version, description in [
        (known_at - timedelta(microseconds=1), 1, "Synthetic account A used device X."),
        (known_at, 2, CORRECTION["description"]),
    ]:
        result = client.post(
            "/cases/CASE-001/investigate", json={"as_of": cutoff.isoformat()}
        ).json()
        item = next(item for item in result["evidence"] if item["id"] == "E-001")
        assert item["version"] == version
        assert item["description"] == description
    events = client.get("/cases/CASE-001/audit").json()
    corrections = [event for event in events if event["action"] == "evidence_correction"]
    assert len(corrections) == 1
    assert corrections[0]["actor"] == "analyst-a"
    assert corrections[0]["payload"]["reason"] == CORRECTION["reason"]
    assert corrections[0]["payload"]["batch_id"] == CORRECTION["batch_id"]


def test_future_event_correction_does_not_resurrect_old_fact(client):
    response = client.post(
        CORRECTION_URL, json={**CORRECTION, "event_time": "2099-01-01T00:00:00Z"}
    )
    assert response.status_code == 201
    result = client.post("/cases/CASE-001/investigate", json={"as_of": response.json()["known_at"]})
    assert result.status_code == 200
    assert not any(item["id"] == "E-001" for item in result.json()["evidence"])


def test_concurrent_corrections_cannot_overwrite_each_other(client):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(CORRECTION_URL, json=CORRECTION), range(2)))
    assert sorted(response.status_code for response in results) == [201, 409]
    events = client.get("/cases/CASE-001/audit").json()
    assert len(events) == 1
    assert events[0]["action"] == "evidence_correction"
    assert events[0]["payload"]["version"] == 2


def test_correction_access_and_server_assigned_knowledge_time(client):
    for path in [
        "/cases/CASE-002/evidence/E-001/corrections",
        "/cases/CASE-001/evidence/E-004/corrections",
        "/cases/CASE-001/evidence/missing/corrections",
    ]:
        assert client.post(path, json=CORRECTION).status_code == 404
    assert (
        client.post(
            CORRECTION_URL, json={**CORRECTION, "known_at": "2020-01-01T00:00:00Z"}
        ).status_code
        == 422
    )
    assert (
        client.post(CORRECTION_URL, json={**CORRECTION, "relationship": "same_person"}).status_code
        == 422
    )
    assert client.get("/cases/CASE-001/audit").json() == []
    client.headers.pop("Authorization")
    assert client.post(CORRECTION_URL, json=CORRECTION).status_code == 401


def test_original_sqlite_database_upgrades_without_losing_facts_or_reviews(tmp_path):
    path = str(tmp_path / "legacy.db")
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE cases (id TEXT PRIMARY KEY, owner TEXT NOT NULL);
            CREATE TABLE evidence (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, source TEXT NOT NULL,
                target TEXT NOT NULL, description TEXT NOT NULL, event_time TEXT NOT NULL,
                known_at TEXT NOT NULL, restricted INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE audit (
                id INTEGER PRIMARY KEY, case_id TEXT NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL
            );
            INSERT INTO cases VALUES ('CASE-001', 'analyst-a');
            INSERT INTO evidence VALUES ('E-001', 'CASE-001', 'account-a', 'device-x',
                'Existing custom synthetic fact.', '2026-10-20T09:00:00+00:00',
                '2026-10-20T09:01:00+00:00', 0);
            INSERT INTO audit VALUES (1, 'CASE-001', 'analyst-a', 'human_review',
                '{"decision":"close","rationale":"Existing synthetic review."}',
                '2026-10-21T00:00:00+00:00');
        """)
    headers = {"Authorization": "Bearer demo-analyst-a"}
    for _ in range(2):
        with TestClient(create_app(path), headers=headers) as migrated:
            review = migrated.get("/cases/CASE-001/audit").json()[0]
            assert review["payload"]["rationale"] == "Existing synthetic review."
            body = migrated.post(
                "/cases/CASE-001/investigate", json={"as_of": "2026-10-21T12:00:00Z"}
            ).json()
            item = next(item for item in body["evidence"] if item["id"] == "E-001")
            assert item["description"] == "Existing custom synthetic fact."
            assert item["version"] == 1
            assert item["batch_id"] == "legacy-import"


GQL_INVESTIGATE = """
mutation Investigate($case: String!, $input: InvestigationInput!) {
  investigate(caseId: $case, input: $input) {
    caseId requiresHumanReview
    findings { text citations }
    evidence { id state description version knownAt sourceSystem batchId relationship eventTime }
  }
}
"""
GQL_CORRECT = """
mutation Correct($case: String!, $evidence: String!, $input: CorrectionInput!) {
  correctEvidence(caseId: $case, evidenceId: $evidence, input: $input) {
    id version knownAt auditId
  }
}
"""
GQL_CORRECTION = {
    "expectedVersion": 1,
    "source": "account-a",
    "target": "device-x",
    "relationship": "used_device",
    "description": "Corrected synthetic observation using GraphQL.",
    "eventTime": "2026-10-20T09:00:00Z",
    "sourceSystem": "synthetic-graphql",
    "batchId": "graphql-demo-002",
    "reason": "Reconciled against the synthetic source.",
}


@pytest.mark.parametrize(
    "cutoff,hops,expected",
    [
        ("2026-10-21T12:00:00Z", 3, {"E-001"}),
        ("2026-10-22T12:00:00Z", 3, {"E-001", "E-002", "E-003"}),
        ("2026-10-22T12:00:00Z", 1, {"E-001"}),
        ("2026-10-30T00:00:00Z", 3, set()),
    ],
)
def test_graphql_investigation_matches_rest_and_audits_full_snapshot(
    client, cutoff, hops, expected
):
    body = client.post(
        "/graphql",
        json={
            "query": GQL_INVESTIGATE,
            "variables": {"case": "CASE-001", "input": {"asOf": cutoff, "maxHops": hops}},
        },
    ).json()
    assert "errors" not in body
    result = body["data"]["investigate"]
    assert result["requiresHumanReview"] is True
    assert {ref for fact in result["findings"] for ref in fact["citations"]} == expected
    assert "Restricted synthetic profile details" not in str(result)
    denied = next(item for item in result["evidence"] if item["id"] == "E-004")
    assert denied["state"] == "denied"
    assert denied["knownAt"] is None
    rest = client.post(
        "/cases/CASE-001/investigate", json={"as_of": cutoff, "max_hops": hops}
    ).json()
    assert result["findings"] == rest["findings"]
    assert [(e["id"], e["state"]) for e in result["evidence"]] == [
        (e["id"], e["state"]) for e in rest["evidence"]
    ]
    audit = client.post(
        "/graphql", json={"query": '{ audit(caseId: "CASE-001") { action payload actor } }'}
    ).json()["data"]["audit"]
    assert len(audit) == 2
    assert all(event["action"] == "investigation" for event in audit)
    assert audit[0]["actor"] == "analyst-a"
    assert audit[0]["payload"] == rest  # Full snapshot even though selection omitted limitations.
    assert "limitations" not in result


@pytest.mark.parametrize(
    "operation",
    [
        'query { audit(caseId: "CASE") { id } }',
        'mutation { investigate(caseId: "CASE", input: {asOf: "2026-10-22T12:00:00Z"}) {caseId} }',
        'mutation { review(caseId: "CASE", input: {decision: "close", rationale: "Synthetic review."}) {actor} }',
        """mutation { correctEvidence(caseId: "CASE", evidenceId: "E-001", input: {
          expectedVersion: 1, source: "account-a", target: "device-x", relationship: "used_device",
          description: "Synthetic correction.", eventTime: "2026-10-20T09:00:00Z",
          sourceSystem: "synthetic", batchId: "test-002", reason: "Synthetic reconciliation."
        }) {version} }""",
    ],
)
def test_graphql_access_on_every_operation(client, operation):
    missing = client.post("/graphql", json={"query": operation.replace("CASE", "CASE-002")}).json()
    assert missing["data"] is None
    assert missing["errors"][0]["extensions"] == {"code": "NOT_FOUND", "status": 404}
    assert client.get("/cases/CASE-001/audit").json() == []
    client.headers.pop("Authorization")
    unauthenticated = client.post(
        "/graphql", json={"query": operation.replace("CASE", "CASE-001")}
    ).json()
    assert unauthenticated["data"] is None
    assert unauthenticated["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"


def test_graphql_correction_replay_conflict_and_review_share_rest_history(client):
    payload = {
        "query": GQL_CORRECT,
        "variables": {"case": "CASE-001", "evidence": "E-001", "input": GQL_CORRECTION},
    }
    response = client.post("/graphql", json=payload).json()
    assert "errors" not in response
    corrected = response["data"]["correctEvidence"]
    assert corrected["version"] == 2
    assert client.post(CORRECTION_URL, json=CORRECTION).status_code == 409
    conflict = client.post("/graphql", json=payload).json()
    assert conflict["errors"][0]["extensions"]["code"] == "CONFLICT"
    for cutoff, version in [("2026-10-22T12:00:00Z", 1), (corrected["knownAt"], 2)]:
        result = client.post(
            "/cases/CASE-001/investigate", json={"as_of": cutoff, "max_hops": 3}
        ).json()
        item = next(item for item in result["evidence"] if item["id"] == "E-001")
        assert item["version"] == version
    review = client.post(
        "/graphql",
        json={
            "query": """mutation { review(caseId: "CASE-001", input: {
          decision: "request_information", rationale: "Verify synthetic shared device lead."
        }) { actor decision auditId } }"""
        },
    ).json()
    assert "errors" not in review
    assert review["data"]["review"]["actor"] == "analyst-a"
    audit = client.get("/cases/CASE-001/audit").json()
    assert [event["action"] for event in audit] == [
        "evidence_correction",
        "investigation",
        "investigation",
        "human_review",
    ]
    assert audit[0]["payload"]["source_system"] == "synthetic-graphql"
    assert audit[-1]["id"] == review["data"]["review"]["auditId"]
    for evidence_id in ["E-004", "missing"]:
        denied = client.post(
            "/graphql",
            json={**payload, "variables": {**payload["variables"], "evidence": evidence_id}},
        ).json()
        assert denied["errors"][0]["extensions"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "input",
    [
        {"asOf": "2026-10-22T12:00:00"},
        {"asOf": "2026-10-22T12:00:00Z", "maxHops": 4},
        {"asOf": "2026-10-22T12:00:00Z", "maxHops": 0},
    ],
)
def test_graphql_preserves_request_boundaries(client, input):
    body = client.post(
        "/graphql",
        json={"query": GQL_INVESTIGATE, "variables": {"case": "CASE-001", "input": input}},
    ).json()
    assert body["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"
    assert client.get("/cases/CASE-001/audit").json() == []


def test_graphql_rejects_invalid_writes_and_excess_aliases_without_side_effects(client):
    invalid = client.post(
        "/graphql",
        json={
            "query": """mutation { review(caseId: "CASE-001", input: {
          decision: "freeze_account", rationale: "Invalid synthetic decision."
        }) { auditId } }"""
        },
    ).json()
    assert invalid["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"
    payload = {
        "query": GQL_CORRECT,
        "variables": {
            "case": "CASE-001",
            "evidence": "E-001",
            "input": {**GQL_CORRECTION, "knownAt": "2020-01-01T00:00:00Z"},
        },
    }
    assert client.post("/graphql", json=payload).json()["errors"]
    repeated = (
        "mutation {"
        + " ".join(
            f'a{i}: review(caseId: "CASE-001", input: {{decision: "close", rationale: "Synthetic review."}}) {{auditId}}'
            for i in range(6)
        )
        + "}"
    )
    assert client.post("/graphql", json={"query": repeated}).json()["errors"]
    assert client.get("/cases/CASE-001/audit").json() == []


RUN_FIELDS = """id caseId status createdAt reviewedAt reviewer reviewDecision reviewRationale
  investigation { asOf findings { text citations } evidence { id version state description }
                  limitations requiresHumanReview }"""
START_RUN = (
    """mutation Start($case: String!, $input: InvestigationInput!) {
  startRun(caseId: $case, input: $input) { """
    + RUN_FIELDS
    + " } }"
)
REVIEW_RUN = (
    """mutation Review($case: String!, $id: String!, $input: ReviewInput!) {
  reviewRun(caseId: $case, runId: $id, input: $input) { """
    + RUN_FIELDS
    + " } }"
)
GET_RUN = (
    """query Run($case: String!, $id: String!) {
  run(caseId: $case, runId: $id) { """
    + RUN_FIELDS
    + " } }"
)


def test_run_survives_restart_freezes_evidence_and_reviews_exactly_once(database):
    headers = {"Authorization": "Bearer demo-analyst-a"}
    with TestClient(create_app(database), headers=headers) as client:
        started = client.post(
            "/graphql",
            json={
                "query": START_RUN,
                "variables": {
                    "case": "CASE-001",
                    "input": {"asOf": "2026-10-22T12:00:00Z", "maxHops": 3},
                },
            },
        ).json()
        assert "errors" not in started, started
        run = started["data"]["startRun"]
        assert run["status"] == "awaiting_review"
        assert run["reviewer"] is None
        assert {ref for f in run["investigation"]["findings"] for ref in f["citations"]} == {
            "E-001",
            "E-002",
            "E-003",
        }
        assert client.post(CORRECTION_URL, json=CORRECTION).status_code == 201
        assert [e["action"] for e in client.get("/cases/CASE-001/audit").json()] == [
            "run_started",
            "evidence_correction",
        ]
    with TestClient(create_app(database), headers=headers) as reopened:
        variables = {"case": "CASE-001", "id": run["id"]}
        loaded = reopened.post("/graphql", json={"query": GET_RUN, "variables": variables}).json()
        assert loaded["data"]["run"] == run
        review_variables = {
            **variables,
            "input": {
                "decision": "request_information",
                "rationale": "Verify this frozen synthetic lead.",
            },
        }
        reviewed = reopened.post(
            "/graphql", json={"query": REVIEW_RUN, "variables": review_variables}
        ).json()
        assert "errors" not in reviewed, reviewed
        result = reviewed["data"]["reviewRun"]
        assert result["status"] == "reviewed"
        assert result["reviewer"] == "analyst-a"
        assert result["reviewedAt"] is not None
        assert result["investigation"] == run["investigation"]
        retry = reopened.post(
            "/graphql", json={"query": REVIEW_RUN, "variables": review_variables}
        ).json()
        assert retry == reviewed
        events = reopened.get("/cases/CASE-001/audit").json()
        assert [e["action"] for e in events] == [
            "run_started",
            "evidence_correction",
            "human_review",
            "run_reviewed",
        ]
        assert events[-2]["payload"]["run_id"] == run["id"]
        assert events[-2]["payload"]["decision"] == "request_information"


@pytest.mark.parametrize("failure_point", ["before_resume", "after_resume"])
def test_saved_run_review_can_recover_after_interruption(client, monkeypatch, failure_point):
    from contextlib import contextmanager

    from investigation_runs import InvestigationRuns

    run = client.post(
        "/graphql",
        json={
            "query": START_RUN,
            "variables": {"case": "CASE-001", "input": {"asOf": "2026-10-22T12:00:00Z"}},
        },
    ).json()["data"]["startRun"]
    variables = {
        "case": "CASE-001",
        "id": run["id"],
        "input": {"decision": "close", "rationale": "Reviewed the frozen synthetic snapshot."},
    }
    original = InvestigationRuns.workflow

    @contextmanager
    def broken(self):
        if failure_point == "before_resume":
            raise RuntimeError("Injected checkpoint connection outage")
        with original(self) as graph:
            yield graph
        raise RuntimeError("Injected interruption after graph completed")

    with monkeypatch.context() as patch:
        patch.setattr(InvestigationRuns, "workflow", broken)
        failed = client.post("/graphql", json={"query": REVIEW_RUN, "variables": variables}).json()
        assert failed["errors"]
    pending = client.post(
        "/graphql", json={"query": GET_RUN, "variables": {"case": "CASE-001", "id": run["id"]}}
    ).json()["data"]["run"]
    assert pending["status"] == "review_pending"
    assert pending["reviewDecision"] == "close"
    recovered = client.post("/graphql", json={"query": REVIEW_RUN, "variables": variables}).json()
    assert recovered["data"]["reviewRun"]["status"] == "reviewed", recovered
    events = client.get("/cases/CASE-001/audit").json()
    assert [e["action"] for e in events] == ["run_started", "human_review", "run_reviewed"]


def test_competing_run_reviews_cannot_replace_first_decision(client):
    run = client.post(
        "/graphql",
        json={
            "query": START_RUN,
            "variables": {"case": "CASE-001", "input": {"asOf": "2026-10-22T12:00:00Z"}},
        },
    ).json()["data"]["startRun"]

    def submit(decision):
        return client.post(
            "/graphql",
            json={
                "query": REVIEW_RUN,
                "variables": {
                    "case": "CASE-001",
                    "id": run["id"],
                    "input": {
                        "decision": decision,
                        "rationale": "Reviewed the synthetic evidence snapshot.",
                    },
                },
            },
        ).json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ["close", "escalate"]))
    assert sum("errors" not in result for result in results) == 1, results
    rejected = next(result for result in results if "errors" in result)
    assert rejected["errors"][0]["extensions"]["code"] == "CONFLICT"
    events = client.get("/cases/CASE-001/audit").json()
    assert [e["action"] for e in events] == ["run_started", "human_review", "run_reviewed"]


@pytest.mark.parametrize(
    "operation",
    [
        '{ runs(caseId: "CASE-002") { id } }',
        '{ run(caseId: "CASE-002", runId: "missing") { id } }',
        'mutation { startRun(caseId: "CASE-002", input: {asOf: "2026-10-22T12:00:00Z"}) { id } }',
        """mutation { reviewRun(caseId: "CASE-002", runId: "missing", input: {
         decision: "close", rationale: "Synthetic review denied."}) { id } }""",
    ],
)
def test_run_operations_enforce_case_access(client, operation):
    result = client.post("/graphql", json={"query": operation}).json()
    assert result["errors"][0]["extensions"]["code"] == "NOT_FOUND"
    client.headers.pop("Authorization")
    result = client.post("/graphql", json={"query": operation}).json()
    assert result["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"


@pytest.fixture
def advice_provider(monkeypatch):
    monkeypatch.setenv("DECISION_PROVIDER", "openai")
    monkeypatch.setenv("DECISION_MODEL", "synthetic-test-model")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    requests = []
    output = {
        "decision": "request_information",
        "rationale": "Verify the shared device lead.",
        "citations": ["E-001", "E-002"],
        "gaps": ["Watchlist unavailable."],
    }
    reply = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]}

    def respond(request):
        requests.append(request)
        if reply.get("timeout"):
            raise httpx.ReadTimeout("Synthetic provider timeout", request=request)
        return httpx.Response(reply.get("status", 200), json=reply)

    original = httpx.Client
    monkeypatch.setattr(
        "decision_support.httpx.Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)),
    )
    return requests, output, reply


ADVICE_FIELDS = """status provider model promptVersion message
 advice {decision rationale citations gaps}"""
ADVICE_START = (
    """mutation($case: String!, $input: InvestigationInput!) {
 startRun(caseId:$case,input:$input){id status reviewer investigation {
 requiresHumanReview modelAssessment {"""
    + ADVICE_FIELDS
    + "}}}}"
)


@pytest.mark.parametrize("provider", ["openai", "openrouter"])
def test_model_advice_is_scoped_persisted_and_never_a_human_decision(
    client, database, advice_provider, monkeypatch, provider
):
    requests, expected, _ = advice_provider
    monkeypatch.setenv("DECISION_PROVIDER", provider)
    args = {"case": "CASE-001", "input": {"asOf": "2026-10-22T12:00:00Z", "maxHops": 3}}
    default = client.post("/graphql", json={"query": ADVICE_START, "variables": args}).json()
    assert default["data"]["startRun"]["investigation"]["modelAssessment"] is None
    assert requests == []
    args["input"]["requestAdvice"] = True
    result = client.post("/graphql", json={"query": ADVICE_START, "variables": args}).json()
    run = result["data"]["startRun"]
    assessment = run["investigation"]["modelAssessment"]
    assert assessment["advice"] == expected
    assert assessment["status"] == "completed"
    assert assessment["provider"] == provider
    assert assessment["model"] == "synthetic-test-model"
    assert run["status"] == "awaiting_review"
    assert run["reviewer"] is None
    assert run["investigation"]["requiresHumanReview"] is True
    assert len(requests) == 1
    sent = json.loads(requests[0].content)
    assert requests[0].url.host == ("api.openai.com" if provider == "openai" else "openrouter.ai")
    evidence = json.loads(sent["messages"][1]["content"])
    assert {item["id"] for item in evidence["available_evidence"]} == {"E-001", "E-002", "E-003"}
    assert "restricted-profile" not in str(sent)
    assert "Restricted synthetic profile details" not in str(sent)
    assert all(item["state"] == "available" for item in evidence["available_evidence"])
    with TestClient(
        create_app(database), headers={"Authorization": "Bearer demo-analyst-a"}
    ) as restarted:
        loaded = restarted.post(
            "/graphql",
            json={
                "query": 'query($id:String!){run(caseId:"CASE-001",runId:$id){investigation{modelAssessment{'
                + ADVICE_FIELDS
                + "}}}}",
                "variables": {"id": run["id"]},
            },
        ).json()
        assert loaded["data"]["run"]["investigation"]["modelAssessment"] == assessment
        # The analyst may disagree. Resuming does not regenerate model advice.
        reviewed = restarted.post(
            "/graphql",
            json={
                "query": REVIEW_RUN,
                "variables": {
                    "case": "CASE-001",
                    "id": run["id"],
                    "input": {
                        "decision": "escalate",
                        "rationale": "Escalating for independent synthetic review.",
                    },
                },
            },
        ).json()
        assert reviewed["data"]["reviewRun"]["reviewDecision"] == "escalate"
    assert len(requests) == 1
    events = client.get("/cases/CASE-001/audit").json()
    assert events[1]["payload"]["investigation"]["model_assessment"]["advice"] == expected


@pytest.mark.parametrize(
    "failure",
    [
        "citation",
        "denied_citation",
        "empty_citations",
        "decision",
        "refusal",
        "truncated",
        "timeout",
        "http_error",
        "malformed",
    ],
)
def test_invalid_model_advice_abstains_without_blocking_review(client, advice_provider, failure):
    requests, output, reply = advice_provider
    message = reply["choices"][0]["message"]
    if failure in {"citation", "denied_citation", "empty_citations", "decision"}:
        if failure == "decision":
            output["decision"] = "block_account"
        else:
            output["citations"] = {
                "citation": ["invented"],
                "denied_citation": ["E-004"],
                "empty_citations": [],
            }[failure]
        message["content"] = json.dumps(output)
    elif failure == "refusal":
        message["refusal"] = "Synthetic refusal"
    elif failure == "truncated":
        reply["choices"][0]["finish_reason"] = "length"
    elif failure == "timeout":
        reply["timeout"] = True
    elif failure == "http_error":
        reply["status"] = 429
    else:
        message["content"] = "not json"
    result = client.post(
        "/graphql",
        json={
            "query": ADVICE_START,
            "variables": {
                "case": "CASE-001",
                "input": {"asOf": "2026-10-22T12:00:00Z", "requestAdvice": True},
            },
        },
    ).json()
    run = result["data"]["startRun"]
    assert run["status"] == "awaiting_review"
    assessment = run["investigation"]["modelAssessment"]
    assert assessment["status"] == "unavailable"
    assert assessment["advice"] is None
    assert len(requests) == 1
    assert "synthetic-test-key" not in str(result)
    reviewed = client.post(
        "/graphql",
        json={
            "query": REVIEW_RUN,
            "variables": {
                "case": "CASE-001",
                "id": run["id"],
                "input": {
                    "decision": "request_information",
                    "rationale": "Gather the missing synthetic evidence.",
                },
            },
        },
    ).json()
    assert reviewed["data"]["reviewRun"]["status"] == "reviewed"


def test_advice_does_not_send_without_evidence_configuration_or_authorization(
    client, advice_provider, monkeypatch
):
    requests, _, _ = advice_provider
    for cutoff in ["2026-10-19T00:00:00Z", "2026-10-30T00:00:00Z"]:
        result = client.post(
            "/cases/CASE-001/investigate", json={"as_of": cutoff, "request_advice": True}
        ).json()
        assert result["model_assessment"]["status"] == "unavailable"
        assert result["model_assessment"]["advice"] is None
    monkeypatch.delenv("OPENAI_API_KEY")
    result = client.post(
        "/cases/CASE-001/investigate",
        json={"as_of": "2026-10-22T12:00:00Z", "request_advice": True},
    ).json()
    assert "not configured" in result["model_assessment"]["message"]
    for case_id in ["CASE-002", "missing"]:
        result = client.post(
            "/graphql",
            json={
                "query": ADVICE_START,
                "variables": {
                    "case": case_id,
                    "input": {"asOf": "2026-10-22T12:00:00Z", "requestAdvice": True},
                },
            },
        ).json()
        assert result["errors"][0]["extensions"]["code"] == "NOT_FOUND"
    assert requests == []
