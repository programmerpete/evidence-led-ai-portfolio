# Role preparation: evidence first

## Review of the supplied screenshots

The advertisement describes a senior **hands-on** AI/full-stack/data engineering role
with explicit financial-crime domain experience, safety, traceability and human authority.
It is not primarily a people-leadership role.

The accompanying analysis describes experience; it is not independent verification of
that experience, and no CV has been supplied here. Based on those descriptions:

| Area | Positioning and action |
| --- | --- |
| Controlled agent workflows | Strong transferable story: explain approvals, tool limits, failure handling and who remained accountable. Bring an anonymised example you are allowed to discuss. |
| TypeScript/React and typed contracts | Transferable full-stack strength. Next.js App Router is a specific skill to demonstrate, not assume from React alone. |
| Release/incident ownership | Use concrete examples of rollout, rollback, diagnostics and recovery. |
| Offline systems/telemetry | Relevant to late data and unavailable sources, but not automatically proof of governed data engineering expertise. Demonstrate lineage and time semantics directly. |
| Python/SQL | Build and explain the backend yourself: schemas, validation, transactions, access checks, tests and query choices. |
| Entity resolution/investigation graphs | Shared devices are links, not identity matches. Route optimisation is adjacent graph experience, not equivalent to entity resolution or financial-crime investigation. |
| ML/RAG/evaluation | Demonstrate a rules baseline, held-out metrics, evaluation failures and safe fallback before claiming AI expertise. |
| Fraud/AML domain | Material experience gap if the screenshot is accurate. Payments, biometrics and tokens are fraud-adjacent; personal projects do not turn them into professional AML experience. |

The advert says Sydney/Melbourne hybrid. Confirm location flexibility with the hiring
manager if you intend to remain Gold Coast-based; the screenshot's earlier analysis
mentions Gold Coast, but that is not confirmed in this conversation. Also ask whether
direct financial-crime experience is a hard requirement or transferable experience plus
demonstrable learning is acceptable. Do not assume a portfolio overrides that requirement.

## Recommended sequence

### A. Investigation assistant (started)

**Learning goal:** Python service engineering plus evidence-aware investigation controls.

Current foundation: runnable API, reproducible late-arrival fixture, bounded traversal,
cited source facts, explicit evidence states, demo case access, persisted human reviews,
PostgreSQL/SQLite storage, Alembic migration, typed links, source/batch lineage and
append-only corrections with historical replay and competing-edit protection.
There is also a separate Splink/DuckDB lab with supervised training, held-out pair
evaluation, blocking recall and explicit false-positive/missed-match examples.
REST and Strawberry GraphQL now expose the same investigation, correction, review and
audit operations, with shared validation and policies. GraphiQL is a developer playground,
separate from the new `/analyst` workbench. The workbench uses persisted investigation
snapshots and a real LangGraph human-review interrupt, with restart/resume and safe retries.

Next slices, in priority order:

1. **Governed data (first slice implemented):** PostgreSQL and migration-backed evidence
   versions now preserve facts at earlier knowledge cutoffs. Next add validated ingestion
   contracts, source attestations and policy-versioned replay. Current event timestamps
   are point assertions, not full valid-time intervals; API append-only history is not
   database-enforced immutability. Move case-history selection to bounded SQL queries
   before increasing dataset size. CI runs contracts against both storage engines.
2. **Entity resolution (lab implemented):** Splink scores synthetic name/address variations
   against held-out person labels and reports pair precision/recall, blocking misses and
   false-positive pairs. Shared device IDs do not contribute to matching. Next persist
   reviewable candidate links, model versions and reviewer accept/reject decisions;
   never equate a score, shared device or address with confirmed identity or fraud.
3. **Human review UI (first slice implemented):** framework-independent workbench showing
   evidence, cutoff, limitations and cited facts. Reviews bind to a frozen run, require a
   rationale and resume a persisted LangGraph checkpoint. Next.js App Router remains a
   separate skill gap; the current UI does not demonstrate React/Next.js proficiency.
   Next add independent-reviewer policy, workflow-version migration and recovery tooling.
4. **Model decision support (first slice implemented):** opt-in OpenAI/OpenRouter advice
   uses permitted available evidence, structured outputs and citation membership checks.
   Advice freezes with the run and never supplies the human decision. Provider failures
   preserve deterministic facts and review. This is not a validated fraud classifier or
   proof of grounding: next add labelled recommendation-quality and prompt-injection
   evaluations, calibrated abstention and spending controls before any operational use.
5. **Operational readiness:** real identity/purpose checks, denied-access audit, idempotent
   review submissions, versioned model/prompt/config, diagnostic logs with no sensitive
   payloads, deployment/rollback runbook and tested database recovery.

### B. Fraud signal evaluation (started)

**Learning goal:** distinguish conventional ML from an agent and reason about operating costs.

Current experiment: rules vs logistic regression, train/validation/test separation,
frozen thresholds, average precision, confusion counts and an explicitly shifted period.

Next: public permitted dataset with a data card; true chronological split; prevent
customer/entity leakage; compare thresholds at reviewer capacity; report uncertainty;
separate covariate shift from concept drift; define an alert and human-reviewed promotion
policy. Only use data that is licensed and suitable for a public personal project.

## Domain learning alongside the code

Use current official AUSTRAC guidance for AML/CTF obligations and SMR/TTR/IFTI concepts;
use current official sources for Australian privacy and scams requirements. Verify dates,
scope and applicability rather than repeating the screenshots' legal summaries as advice.
No legal claims from those summaries have been independently validated in this repository.

Explain the difference between fraud loss prevention, authorised-payment scams and AML
investigation. A synthetic alert is not proof of crime and a score alone is not a basis
for a regulatory filing. Ask an authorised domain specialist to review your scenario
definitions; do not request or bring real customer cases into this portfolio.

## Interview demo and honest positioning

- Explain why a late link must not appear in an earlier investigation.
- Show a false identity inference you deliberately avoid (a shared household device).
- Compare precision and recall under the same validation alert budget; explain why
  high accuracy is misleading for rare positive cases.
- Show that an investigation cannot silently create a human review decision.
- Name what is missing before this could be used in a bank.

Suggested positioning after you understand and can modify the implementation:

> I have built controlled agent workflows and owned delivery in my existing engineering
> work. To develop my Python and evidence-led investigation skills, I built a synthetic
> portfolio lab covering time-aware evidence, bounded graph exploration, cited facts,
> access-policy checks and human review, plus a separate ML evaluation experiment.
> This is learning evidence, not a claim of production fraud/AML investigation experience.

Do not claim to have designed every line unaided: AI-assisted implementation is useful,
but be ready to explain the choices, modify the code and diagnose failing scenarios yourself.
