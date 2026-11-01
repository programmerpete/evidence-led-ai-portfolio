# evidence-led-ai-portfolio

AI portfolio in the fraud space

Three runnable, synthetic-only portfolio labs for a hands-on banking AI engineering role.
These are learning labs, **not production banking systems**, compliance advice, or evidence
of professional fraud/AML casework. No employer code, customer data, internal documents,
credentials, model API key or paid service is needed.

## 1. Fraud investigation assistant — backend foundation

Python, FastAPI, PostgreSQL or SQLite, Alembic, Pydantic and a deterministic LangGraph workflow.

- Typed API inputs and outputs; timezone-aware investigation cutoff.
- Case-scoped demo access on investigation, review and audit routes.
- Bounded graph exploration (1–3 hops) of synthetic account/device/payment relationships.
- Separate event and knowledge timestamps: a late-arriving relationship cannot be used
  before the system knew it, even if its event happened earlier.
- Explicit available, unknown, stale, denied and unavailable evidence states.
- Facts cite evidence IDs; denied contents are redacted; stale edges do not expand the graph.
- Separate human review endpoint records actor, decision, rationale and recording time.
- Investigation outputs and reviews persist in SQLite across process restarts.
- Append-only evidence corrections with version, typed relationship, source system and batch lineage.
- Server-assigned knowledge timestamps, optimistic edit conflicts and atomic correction/audit writes.

### Run

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then:

```sh
uv sync --locked --all-extras
uv run pytest -q
uv run uvicorn investigation:create_app --factory --host 127.0.0.1 --port 8000
```

The server provides OpenAPI and Swagger documentation at `/docs`. Its factory creates
and seeds `investigation.db` on startup. Stop it with Ctrl+C. To reset the demo, stop
the server and remove that disposable database. Tests use isolated temporary databases.

For hands-on endpoint exercises, follow [API_TESTING.md](API_TESTING.md): Swagger
authorisation, investigation cutoffs, corrections, reviews, audit and expected error codes.

### REST and GraphQL side by side

The same server also exposes **Strawberry GraphQL at `/graphql`**, including a GraphiQL
browser playground. Both interfaces call the same operations and share Pydantic validation,
case access, evidence-history selection, LangGraph drafting and database transactions.
GraphQL is a second interface, not a second implementation of investigation logic.

| REST operation | GraphQL operation |
| --- | --- |
| `POST /cases/{case_id}/investigate` | Mutation `investigate(caseId, input)` |
| `POST /cases/{case_id}/reviews` | Mutation `review(caseId, input)` |
| `POST /cases/{case_id}/evidence/{evidence_id}/corrections` | Mutation `correctEvidence(caseId, evidenceId, input)` |
| `GET /cases/{case_id}/audit` | Query `audit(caseId)` |

Investigation is a **mutation** because it persists an audit snapshot. GraphQL lets clients
select response fields, but the complete investigation still runs and is audited; selecting
fewer fields does not weaken the evidence policy or reduce the underlying traversal.
Use the same bearer header as REST. GraphQL uses camelCase field names, such as `asOf`,
`maxHops` and `requiresHumanReview`. See [the GraphQL walkthrough](API_TESTING.md#graphql-walkthrough).

Data operations use HTTP POST. The GET playground and schema introspection are public;
every data resolver checks the demo identity. Resolver errors appear in `errors` (usually
with HTTP 200), with `extensions.code` and `extensions.status`; check those rather than
HTTP status alone. The flat schema has no arbitrary nested graph traversal. Requests are
limited to depth 6, 5 aliases and 2,000 tokens; JSON batching is disabled. These are modest
demo guardrails, not complete resource controls: audit pagination, rate/body-size limits,
timeouts and production authentication are still needed. Mutations are individual
transactions, not one atomic transaction for an entire multi-field GraphQL request.
The stock GraphiQL browser assets load from a CDN and need an internet connection.

### PostgreSQL and migrations

SQLite remains the zero-infrastructure default. Set `DATABASE_URL` to a SQLAlchemy
PostgreSQL URL to use a dedicated **synthetic-only** database instead. Both
`postgresql://` and `postgresql+psycopg://` URLs are supported. Do not put credentials
in source control. The server applies Alembic migrations at startup, so its database
role needs schema-creation permissions; production migration roles should be separate.

For local development with Docker installed:

```sh
docker run --name portfolio-postgres -d \
  -e POSTGRES_USER=portfolio -e POSTGRES_PASSWORD=synthetic-local-only \
  -e POSTGRES_DB=portfolio -p 127.0.0.1:5432:5432 postgres:17
# Wait until this reports that the server accepts connections:
docker exec portfolio-postgres pg_isready -U portfolio -d portfolio
DATABASE_URL='postgresql+psycopg://portfolio:synthetic-local-only@127.0.0.1:5432/portfolio' \
  uv run uvicorn investigation:create_app --factory --host 127.0.0.1 --port 8000
```

The example password is a public, disposable local-demo value, not a production secret.
Stop the container with `docker stop portfolio-postgres`; restart with `docker start
portfolio-postgres`. Do not remove a database/container whose contents you need.

Migration `0001` also upgrades the original SQLite schema in place: existing facts
become version 1 with `legacy-import` lineage; existing reviews and audit IDs survive.
It copies the old `evidence` table to `evidence_versions` before removing the old table.
**Stop old application processes and back up the database before upgrading.** SQLite
DDL is not guaranteed to roll back atomically. Downgrade is intentionally unsupported;
recovery means restoring a tested backup, not discarding evidence history. Changing
`DATABASE_URL` does not copy SQLite data to PostgreSQL; each database is independent.

`.agents/setup` installs the PostgreSQL binaries and locked dependencies in a fresh
Debian orb. It does not start a database service. Use a supervised orb service for
long-lived processes; Docker instructions above are for environments with a Docker daemon.

### Five-minute demo

In Swagger's **Authorize** dialog use `demo-analyst-a` (the bearer value, without a
`Bearer ` prefix). The public demo identities intentionally let anyone impersonate
either analyst; they only demonstrate access-policy branches, not secure authentication.

1. Call `POST /cases/CASE-001/investigate` with:

   ```json
   {"as_of": "2026-10-21T12:00:00Z", "max_hops": 3}
   ```

   Only E-001 supports a finding. E-002 is not known yet, so it cannot bridge to E-003.
2. Change the cutoff to `2026-10-22T12:00:00Z`: E-001, E-002 and E-003 can now be cited.
3. Set `max_hops` to 1: only E-001 supports a finding. Restricted E-004 stays denied.
4. Set the cutoff to `2026-10-30T00:00:00Z`: the root's accessible evidence is stale;
   no current facts are drafted. Before `2026-10-20`, graph evidence is unknown.
5. Try CASE-002 with analyst A: 404, just as for a nonexistent case. Missing or invalid
   bearer identity returns 401.
6. Call `POST /cases/CASE-001/reviews` with:

   ```json
   {"decision": "request_information", "rationale": "Verify the shared device lead before escalation."}
   ```

7. Read `GET /cases/CASE-001/audit`; restart the server and read it again to see persistence.

All fixture timestamps are UTC. Sydney-facing date display belongs in the future UI;
API callers may supply any explicit timezone offset.

### Evidence correction demo

Call `POST /cases/CASE-001/evidence/E-001/corrections` with the demo analyst A identity:

```json
{
  "expected_version": 1,
  "source": "account-a",
  "target": "device-x",
  "relationship": "used_device",
  "description": "Corrected synthetic device observation from source reconciliation.",
  "event_time": "2026-10-20T09:00:00Z",
  "source_system": "synthetic-reconciliation",
  "batch_id": "correction-batch-002",
  "reason": "Reconciled the observation with the synthetic source."
}
```

The response supplies version 2, its server-assigned `known_at`, and its audit ID.
Repeat an investigation with the original `2026-10-22T12:00:00Z` cutoff: it still
returns version 1. Investigate at the returned `known_at`: it selects version 2
(stale under the demo's 7-day rule). No caller can backdate the knowledge timestamp.
If a correction moves an event beyond the cutoff, the superseded fact does **not**
reappear. Repeating an edit with `expected_version: 1` returns 409; reload before editing.
Restricted evidence cannot be corrected with these demo identities.

Versions are append-only through the API, not immutable against a database administrator.
`event_time` is a point-in-time assertion, not a full valid-time interval model. Timestamps
remain offset-aware ISO text for parity with the first SQLite schema; this small lab
loads case history and selects versions in Python. Larger deployments need native temporal
types, indexed as-of queries, pagination and resource limits. Lineage identifiers are
caller-supplied synthetic metadata, not independently attested source provenance.

### Deliberate boundaries

This is **not yet an LLM agent**. LangGraph currently executes one deterministic drafting
node; it copies permitted source facts rather than generating conclusions. It has no
arbitrary tool execution. There is no probabilistic entity resolution, RAG or risk score
in this API. The separate Splink lab below does not change case evidence or merge entities.
The graph is a tiny SQL-backed edge list rooted at synthetic account A, not a scalable
graph database. Relationships are typed (`used_device`, `transferred_to`, `profile`),
but entity types and direction-specific traversal policies are not yet enforced.
The 7-day freshness cutoff is a demonstrative policy, not a banking retention rule:
older evidence can still matter in real investigations. Historical cutoffs filter evidence,
not historical access entitlements. Replays assume unchanged access and freshness policy;
they are evidence-history replays, not versioned application/model/policy replays.

Reviews are attributed records, not a full case lifecycle or approvals system: they are
not tied to a selected investigation version and do not close/block accounts or file reports.
Audit is append-only through this API, **not tamper-proof storage**. Failed/denied requests
are not audited yet. Real deployments also need SSO, purpose-based entitlements,
retention controls, monitoring, rate/resource limits, and independent security review.
Do not expose this demo with real data or treat the public demo tokens as secrets.

## 2. Fraud signal evaluation lab

```sh
uv run --extra ml python fraud_signals.py
```

Compares a simple two-feature rule baseline against logistic regression, using an
imbalanced probabilistic synthetic dataset. Fits preprocessing/model only on training
data, freezes both alert thresholds on a separate validation period at a 5% alert budget,
then evaluates untouched held-out and deliberately shifted periods.

Reports positive prevalence, **average precision** (not trapezoidal PR-AUC), precision,
recall, alert rate, confusion counts and feature-mean shifts. This is a starting point
for discussing alert fatigue, false positives, missed cases, drift and challenger testing.
It is not a real temporal backtest: periods are independent simulations. No model is
automatically promoted, and no claim of real fraud performance should be made.

## 3. Entity-resolution lab (Splink + DuckDB)

```sh
uv run --extra entity python entity_resolution.py
```

Trains a Splink linkage model on **240 synthetic records for 120 labelled people**, then
scores a separate **160 records for 80 held-out people**. Training and held-out person
IDs are disjoint. Labels are supplied only for supervised training and final evaluation,
never as inference inputs. Names, DOB, addresses and postcodes support matching; shared
device IDs are deliberately excluded. Fixtures include spelling errors, initials, address
changes, DOB errors and distinct people with similar names in the same household.

Splink estimates `m` probabilities from matching training labels and `u` probabilities
from seeded training-pair sampling. The prior comes from training duplicate prevalence.
The pair budget covers this tiny training set, including a small fraction of real duplicate
pairs; production u-estimation needs a much larger representative population. The simple
generator and correlated attributes mean these probabilities are **not calibrated for real
customers**. No EM training or unlabelled learning is claimed here.

Candidate blocking uses matching DOB or surname plus postcode. The report compares fixed
0.8/0.95/0.99 score thresholds, showing pair precision/recall, blocking recall, false-positive
pair examples (named `false_merge_examples`) and missed duplicates. Recall includes duplicates
that blocking failed to generate, rather than reporting inflated candidate-only recall.
An example generated run at 0.95 scored 69 true-positive pairs, 10 false-positive pairs and
11 missed duplicate pairs. Those mistakes are deliberately visible, not hidden or converted
to confirmed identities. Thresholds are illustrative, not a recommendation or selected on
the held-out labels; increasing a threshold does not guarantee better observed precision.

This is **CLI-only**, with no API endpoint yet. It neither writes to the investigation
database nor performs graph merges, clustering, reviewer overrides or customer actions.
Next, build a reviewable candidate-link workflow that records accepted/rejected matches
separately from evidence and fraud suspicion. Do not automatically treat predicted pair
links as transitive identity clusters.

## Checks and small evaluation set

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Install the optional `entity` extra (or use `uv run --all-extras pytest -q`) to include
the Splink contract tests; otherwise that test module is skipped. The entity tests check
pair metrics including blocked-out duplicates and verify that changing device IDs cannot
change the matching scores.

The API evaluation cases check: unavailable/future knowledge; late-arrival bridge
blocking; 1/2/3-hop boundaries; freshness at exactly 7 days and one second later;
redaction; explicit unknown/stale/denied/unavailable states; all-route case access;
timezone/hop validation; absence of automatic reviews; and review persistence.
These are deterministic contract checks, not an LLM quality benchmark.

To run the same API contracts against PostgreSQL as well, point `TEST_DATABASE_URL`
at a **disposable test database** with permission to create/drop schemas:

```sh
TEST_DATABASE_URL='postgresql+psycopg://portfolio:synthetic-local-only@127.0.0.1:5432/portfolio' \
  uv run pytest -q
```

Each PostgreSQL test uses a unique schema, then drops it. Tests additionally cover
historical replay after correction, the exact knowledge-time boundary, future-event
supersession, competing edits, correction access, and legacy SQLite migration/restart.
GitHub Actions runs these contracts on both SQLite and PostgreSQL 17, plus lint,
formatting and both synthetic experiments. Without `TEST_DATABASE_URL`, local tests
run only SQLite; a passing SQLite run is not evidence of PostgreSQL compatibility.

## What to build next

See [the role preparation plan](PREPARATION.md) for priorities, acceptance criteria and
interview prompts. Finish explainable vertical slices before adding more frameworks.
