import pytest
from fastapi.testclient import TestClient

from investigation import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "test.db"))) as client:
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


def test_review_is_durable_and_attributed(tmp_path):
    path = str(tmp_path / "durable.db")
    headers = {"Authorization": "Bearer demo-analyst-a"}
    with TestClient(create_app(path), headers=headers) as client:
        response = client.post(
            "/cases/CASE-001/reviews",
            json={
                "decision": "request_information",
                "rationale": "Need to verify the shared device lead.",
            },
        )
        assert response.status_code == 201
    with TestClient(create_app(path), headers=headers) as reopened:
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
