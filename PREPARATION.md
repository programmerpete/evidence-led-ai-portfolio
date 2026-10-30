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
cited source facts, explicit evidence states, demo case access, persisted human reviews.

Next slices, in priority order:

1. **Governed data:** move to PostgreSQL with versioned migrations; model typed links,
   source IDs, ingestion batches, effective/known timestamps and append-only corrections.
   Demonstrate that replaying a historical investigation reproduces the facts then known,
   while later corrections are visible only at later knowledge cutoffs.
2. **Entity resolution:** use Splink on synthetic name/address variations with labelled
   duplicate/nonduplicate pairs. Hold out labels; measure pair precision/recall and show
   false merges. Never equate shared devices or addresses with confirmed same identity.
   Keep match confidence, provenance and reviewer overrides separate from fraud suspicion.
3. **Human review UI:** Next.js App Router screen showing evidence, cutoff, limitations,
   and source paths. Bind reviews to an investigation version and require a rationale.
   Demonstrate stale, denied and partial-source states, not just the happy path.
4. **Constrained LLM drafting:** allow only typed, scoped read tools; keep evidence text
   untrusted; enforce tool/node/row budgets. Validate citations and abstain on unsupported
   claims. Preserve deterministic output when provider calls fail. Add prompt-injection,
   fabricated-citation and denied-data-leak evaluation cases before claiming safe drafting.
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
