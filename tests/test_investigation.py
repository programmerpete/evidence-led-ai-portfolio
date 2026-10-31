import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

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
