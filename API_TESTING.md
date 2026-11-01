# Try the investigation API

Use the **API documentation portal shared in the Amp thread** for the running orb demo.
For your own local checkout, start the server using README.md and open its `/docs` page.
All examples below are synthetic and safe to experiment with. The demo bearer identities
are public teaching values, not secure logins. Do not upload real bank or customer data.

## Swagger UI walkthrough

1. Click **Authorize** near the top, enter `demo-analyst-a` (without `Bearer `), click
   **Authorize**, then **Close**. This identity owns `CASE-001`.
2. Expand an endpoint, click **Try it out**, fill path fields/request JSON, and click
   **Execute**. Read the **Server response**, not just the example response underneath.
3. Errors are part of the exercise: 401 means missing/invalid demo identity, 404 means
   unavailable case/evidence, 409 means a stale edit, and 422 means an invalid request.

### A. Investigate with a historical knowledge cutoff

Endpoint: `POST /cases/{case_id}/investigate`.

Set `case_id` to `CASE-001`, and paste:

```json
{"as_of": "2026-10-22T12:00:00Z", "max_hops": 3}
```

Expected: **200**. Available E-001, E-002 and E-003 support cited facts; E-004 is denied
and watchlist data is unavailable. The result always requires human review.

- Change `as_of` to `2026-10-21T12:00:00Z`: only E-001 supports a fact because E-002
  was not known yet and cannot bridge the graph to E-003.
- Set `max_hops` to 1: E-001 only. Set it to 4: **422**, because the budget is capped at 3.
- Use `2026-10-30T00:00:00Z`: stale evidence, no current supporting facts.
- Try `CASE-002`: **404**, because analyst A does not own it.

### B. Correct an observation without rewriting history

Endpoint: `POST /cases/{case_id}/evidence/{evidence_id}/corrections`.

Set `case_id` to `CASE-001` and `evidence_id` to `E-001`. Paste:

```json
{
  "expected_version": 1,
  "source": "account-a",
  "target": "device-x",
  "relationship": "used_device",
  "description": "Corrected synthetic device observation from source reconciliation.",
  "event_time": "2026-10-20T09:00:00Z",
  "source_system": "synthetic-reconciliation",
  "batch_id": "manual-demo-002",
  "reason": "Reconciled the observation with the synthetic source."
}
```

Expected on a fresh demo: **201**, with `version: 2`, `known_at`, and `audit_id`.
Copy the exact returned `known_at` value for the next step; you cannot choose/backdate it.

Now call **investigate** again:

- With the historical `2026-10-22T12:00:00Z` cutoff: E-001 is still **version 1**.
- With `as_of` set to the returned `known_at`: E-001 is **version 2**, with the new
  description, source and batch. It will be **stale**, since the event is over 7 days old;
  that does not mean the correction failed.
- Resubmit the correction unchanged: **409**, not a second write. If another demo user
  already corrected E-001, you may see 409 on your first attempt too. Investigate using
  the current time, inspect its version, and use that as `expected_version` for a new edit.
- Try E-004: **404**; the demo identity cannot correct restricted evidence.
- Add `known_at` to the request: **422**; knowledge time belongs to the server.

### C. Record a human review

Endpoint: `POST /cases/{case_id}/reviews`, case `CASE-001`:

```json
{"decision": "request_information", "rationale": "Verify the shared device lead before escalation."}
```

Expected: **201**, with the analyst identity and an audit ID. Allowed decisions are
`escalate`, `close`, and `request_information`. These record a human review; they do not
block accounts, file reports or implement a case lifecycle. Repeating a review creates
another record: review idempotency is not implemented yet.

### D. Inspect the audit trail

Endpoint: `GET /cases/{case_id}/audit`, case `CASE-001`.

Expected: **200**, containing the investigation snapshots, correction and human review,
with actor and recording time. Only your successful review request creates a human-review
event; an investigation does not do so automatically. Refreshing audit is read-only.

## GraphQL walkthrough

Open `/graphql` on the same running server (or use the GraphQL portal in the Amp thread).
This is **GraphiQL**, a developer playground, not Swagger. It has no separate path-field
form: put `caseId: "CASE-001"` directly in your operation as shown below.

Open **Headers** below the query editor and enter:

```json
{"Authorization": "Bearer demo-analyst-a"}
```

Unlike Swagger's Authorize dialog, this is a literal HTTP header and **must include
`Bearer `**. The public teaching token is not a secure login. GraphiQL loads its browser
assets from a CDN, so it needs internet access. You can also POST GraphQL documents with
variables using an HTTP client; it is the same `/graphql` endpoint.

Paste this into the main editor and click the triangular **Execute** button:

```graphql
mutation Investigate {
  investigate(
    caseId: "CASE-001"
    input: {asOf: "2026-10-22T12:00:00Z", maxHops: 3}
  ) {
    caseId
    requiresHumanReview
    findings { text citations }
    evidence { id state description version knownAt }
    limitations
  }
}
```

Expected: `data.investigate` with E-001–E-003 supporting facts, denied E-004 and an
unavailable watchlist source. Change the cutoff to `2026-10-21T12:00:00Z`: E-001 only.
Delete `evidence` from the selection to see a smaller response; this does **not** skip
evidence checks or remove evidence from the complete persisted audit snapshot.
It is a mutation because every execution records an investigation audit event.

To inspect the audit without adding another event, replace the editor contents with:

```graphql
query Audit {
  audit(caseId: "CASE-001") { id action actor recordedAt payload }
}
```

`payload` is a JSON scalar containing the event-specific snapshot. To record a human review:

```graphql
mutation Review {
  review(caseId: "CASE-001", input: {
    decision: "request_information"
    rationale: "Verify the synthetic shared device lead before escalation."
  }) { auditId decision actor }
}
```

To correct evidence, use this operation and put the JSON below into **Variables**
(not Headers). It uses the same version checks and history as REST:

```graphql
mutation Correct($input: CorrectionInput!) {
  correctEvidence(caseId: "CASE-001", evidenceId: "E-001", input: $input) {
    id version knownAt auditId
  }
}
```

```json
{
  "input": {
    "expectedVersion": 1,
    "source": "account-a",
    "target": "device-x",
    "relationship": "used_device",
    "description": "Corrected synthetic observation using GraphQL.",
    "eventTime": "2026-10-20T09:00:00Z",
    "sourceSystem": "synthetic-graphql",
    "batchId": "graphql-demo-002",
    "reason": "Reconciled against the synthetic source."
  }
}
```

On a fresh case this returns version 2. Repeat it: `errors[0].extensions.code` is
`CONFLICT`. If you already corrected this evidence via REST, it may conflict on the first
GraphQL attempt; inspect its current version before editing. Use the returned `knownAt`
as the investigation cutoff to see version 2 (stale under the demo's freshness policy).
The historical October 22 cutoff continues to select version 1.

**GraphQL errors differ from REST status codes:** resolver failures usually have HTTP 200
and an `errors` array. Missing/invalid identity gives `UNAUTHENTICATED`; another analyst's
case gives `NOT_FOUND`; invalid hops, a timezone-less date or an invalid review decision
gives `BAD_USER_INPUT`; a stale edit gives `CONFLICT`. These errors include the equivalent
REST status in `extensions.status`. Syntax, schema, variable coercion and request-limit
errors are GraphQL errors too, but do not necessarily have these extension codes.
Do not assume HTTP 200 means success. Failed validation/access checks do not write audit
events. Multiple mutations are not atomic together: earlier successful fields may already
be committed if a later field fails. Repeated successful reviews create more records.

## Automated checks

From the repository root, run `uv run pytest -q` for SQLite contracts. Set
`TEST_DATABASE_URL` to a disposable PostgreSQL database to run both backends; see README.md.
Tests use isolated databases/schemas and do not alter the shared portal demo.

For the separate entity-resolution lab (CLI only, not an API endpoint yet), run:

```sh
uv run --extra entity python entity_resolution.py
```

This prints pair metrics and false-positive examples, not confirmed identities or fraud
decisions. It does not write to the investigation database.
