# Evidence-led AI engineering portfolio

Two runnable, synthetic-only starting projects for a hands-on banking AI engineering role.
These are learning labs, **not production banking systems**, compliance advice, or evidence
of professional fraud/AML casework. No employer code, customer data, internal documents,
credentials, model API key or paid service is needed.

## 1. Fraud investigation assistant — backend foundation

Python, FastAPI, SQLite, Pydantic and a deterministic LangGraph workflow.

- Typed API inputs and outputs; timezone-aware investigation cutoff.
- Case-scoped demo access on investigation, review and audit routes.
- Bounded graph exploration (1–3 hops) of synthetic account/device/payment relationships.
- Separate event and knowledge timestamps: a late-arriving relationship cannot be used
  before the system knew it, even if its event happened earlier.
- Explicit available, unknown, stale, denied and unavailable evidence states.
- Facts cite evidence IDs; denied contents are redacted; stale edges do not expand the graph.
- Separate human review endpoint records actor, decision, rationale and recording time.
- Investigation outputs and reviews persist in SQLite across process restarts.

### Run

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then:

```sh
uv sync --locked --extra ml
uv run pytest -q
uv run uvicorn investigation:create_app --factory --host 127.0.0.1 --port 8000
```

The server provides OpenAPI and Swagger documentation at `/docs`. Its factory creates
and seeds `investigation.db` on startup. Stop it with Ctrl+C. To reset the demo, stop
the server and remove that disposable database. Tests use isolated temporary databases.

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

### Deliberate boundaries

This is **not yet an LLM agent**. LangGraph currently executes one deterministic drafting
node; it copies permitted source facts rather than generating conclusions. It has no
arbitrary tool execution. There is no probabilistic entity resolution, RAG or risk score.
The graph is a tiny SQL-backed edge list rooted at synthetic account A, not a scalable
graph database. Its relationship meanings are in fixture text, not a typed edge schema yet.
The 7-day freshness cutoff is a demonstrative policy, not a banking retention rule:
older evidence can still matter in real investigations. Historical cutoffs filter evidence,
not historical access entitlements. Corrections/versioned facts are not implemented.

Reviews are attributed records, not a full case lifecycle or approvals system: they are
not tied to a selected investigation version and do not close/block accounts or file reports.
Audit is append-only through this API, **not tamper-proof storage**. Failed/denied requests
are not audited yet. Real deployments also need SSO, purpose-based entitlements, migrations,
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

## Checks and small evaluation set

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

The API evaluation cases check: unavailable/future knowledge; late-arrival bridge
blocking; 1/2/3-hop boundaries; freshness at exactly 7 days and one second later;
redaction; explicit unknown/stale/denied/unavailable states; all-route case access;
timezone/hop validation; absence of automatic reviews; and review persistence.
These are deterministic contract checks, not an LLM quality benchmark.

## What to build next

See [the role preparation plan](PREPARATION.md) for priorities, acceptance criteria and
interview prompts. Finish explainable vertical slices before adding more frameworks.
