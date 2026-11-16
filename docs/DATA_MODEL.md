# Data model and synthetic world

Phase 0 approved scope · 14 November 2026

## What the world represents

Generate payment attempts from a seeded, versioned world. The default configuration uses INR, Indian cities, and configurable category and customer amount distributions. Each customer has a home city, time-of-day and weekday habits, preferred merchants and categories, a spending distribution, and recurring devices. Merchants have a category, location, supported payment channels, and an observable risk tier. Generate routines across approximately six months, with customer heterogeneity, occasional outages or declines, seasonality, and travel. Start with a configurable target prevalence around 0.5% of attempts and report the realized rate by channel, scenario, and time window. This is a fixture setting, independent of industry prevalence.

Stripe's review workflow motivates a risk-ranked queue and an analyst decision after inspecting payment context. Its card-testing guidance motivates modeling low-value attempts, rapid retries, and declines. The Fraud Detection Handbook and CardSim provide examples of generating transactions from customer and merchant behavior. Inquest adds linked histories and deliberately overlapping signals for investigation. [Stripe reviews](https://docs.stripe.com/radar/transaction-reviews) · [Stripe card testing](https://docs.stripe.com/disputes/prevention/card-testing) · [Fraud Detection Handbook simulator](https://fraud-detection-handbook.github.io/fraud-detection-handbook/Chapter_3_GettingStarted/SimulatedDataset.html) · [Federal Reserve CardSim paper](https://www.federalreserve.gov/econres/feds/files/2025017pap.pdf)

| Scenario | Observable evidence | Benign overlap or ambiguity |
| --- | --- | --- |
| Account takeover | A previously unseen device and a break from category, amount, or hour patterns followed by clustered attempts | A phone replacement followed by ordinary purchases |
| Card testing | Repeated small card authorizations, sometimes declined, across instruments or concentrated on one merchant or device | Small legitimate recurring charges and duplicate retries |
| Velocity burst | Elevated count or total in a short window, sometimes across merchants | Holiday shopping, split tender, and payment retries |
| Impossible travel | Implausible elapsed time between reliable physical transaction locations | Legitimate travel, low-accuracy locations, and remote checkout |
| New device and high value | An unusual amount combined with device novelty | A legitimate one-off large purchase on a replacement phone |
| Mule or cash-out | Concentrated UPI-style transfers to shared recipients or a cash-like category after unusual activity | Legitimate group payments and recurring transfers |
| UPI collect-request scam | A new requester sends unusual or repeated collect requests followed by attempted debits | Legitimate merchant collect requests and recurring invoices |
| UPI SIM-swap takeover | Observed recent re-registration followed by unusual transfers | Legitimate SIM or handset replacement |
| Merchant collusion | A merchant shows abnormal concentration of customer-device reuse or repeated purchase amounts | A popular merchant or sale with many similar amounts |

Collect and SIM-change events are synthetic observations with ordinary legitimate counterparts. Mule patterns use linked UPI transfers to repeated recipients. The fixture models historical collect flows for investigation practice. [NPCI UPI FAQ](https://www.npci.org.in/what-we-do/upi/faqs) · [RBI fraud awareness handbook](https://systemhealth.rbi.org.in/cms.rbi.org.in/cms/assets/Documents/BEAWARE07032022.pdf)

Assign hidden episode IDs, labels, and scenario tags during generation. Vary event counts, timing, values, and missingness. Some attempts in an episode may be legitimate, so label attempts individually. Keep background and injected behavior overlapping. Merchant collusion and cash-out are simplified indicators of activity visible to this demo. Record a fixed seed, configuration, generator version, counts, time span, and checksum. Use deterministic identifiers and a stable generation order, with separately derived random streams for world creation and scenario injection.

## Postgres

| Table | Core fields and integrity |
| --- | --- |
| `workspaces`, `analysts`, `workspace_memberships` | Workspace identity, analyst identity and role. Phase 6 resolves analyst identities by provider and stable subject, using the GitHub account ID or the Google OpenID Connect subject. Actor identities drive the audit trail. Workspace ownership is enforced on case and simulator routes. |
| `oauth_identities`, `oauth_attempts`, `analyst_sessions` | Provider and stable subject map to one analyst and workspace. Authorization attempts are browser-bound and expire after ten minutes. Sessions are opaque, revocable and stored by token hash. |
| `datasets` | Shared, read-only fixture version, seed and manifest hash. |
| `replay_runs`, `replay_jobs` | Each workspace has a durable active run, cursor and state. The scheduler publishes batches from the shared, label-free scorer output. A replay creates a distinct run and retains prior cases. |
| `customers`, `merchants`, `devices` | Dataset-scoped synthetic IDs, display identifiers and allowed entity attributes. Device identities can recur across customers. Merchant risk uses an observable profile valid at the event cutoff. |
| `transactions` | Dataset and source sequence, customer, counterparty, device, synthetic payment instrument ID, event timestamp, amount in integer minor units, ISO currency, channel, authorization outcome if observed, and approximate location plus source and accuracy. Composite foreign keys prevent cross-fixture joins. Counterparties use the merchant table, with an explicit type for synthetic transfer recipients. |
| `evaluation_truth` | Transaction key, fraud label, scenario and episode ID in an evaluation-only schema. Evaluator credentials can read it. API and tool roles have no grants. |
| `transaction_scores` | Replay and transaction IDs, model and feature versions, score, threshold and top contributions. Unique by replay, source transaction, and scoring version. |
| `cases` | Score and workspace, status, optimistic version and timestamps. Unique case per replay and transaction. |
| `investigations` | Case ID, unique graph thread ID, status, lease, provider/model/config versions, report and budget counters. A partial unique index limits a case to one active investigation. |
| `tool_calls`, `investigation_events` | Validated tool inputs, observations and stable evidence IDs. Events have a per-investigation sequence, typed payload and stable deduplication key. |
| `decisions` | Append-only row with investigation ID, actor, operation, resolved disposition, prior case version, and timestamp. Unique investigation decision and workspace-scoped idempotency key. |
| `notes` | Workspace and case, author, body, timestamp and optional decision reference. Notes stay out of model prompts. |
| `workspace_usage`, `global_usage`, `ip_rate_limits` | UTC-day workspace and global budget reservations, operator kill switch, and bounded per-IP counters. Persist quota updates atomically, count starts idempotently, and use expiring keyed IP hashes. |
| `eval_runs`, `eval_case_results` | Cohort and configuration hashes, measured aggregates and per-case outcome, usage, latency and failure reason. Unique run and transaction result. |

Use Alembic revisions for application schema and grants, with a separate migration identity. Install LangGraph saver tables using its setup API in the graph phase. Store timestamps as UTC `timestamptz` and expose ISO 8601. Index `(dataset_id, customer_id, occurred_at, source_sequence)` and analogous device and merchant paths. Add queue indexes for workspace, status and cursor order, then verify with representative query plans. The shared fixture is read-only to the analyst application. Cases, investigations, decisions and notes carry `workspace_id`. Their child observations and timeline rows inherit the same scope through composite foreign keys. One tenant-scoped transaction layer binds the workspace from authenticated membership. Postgres policies fail closed without a workspace, including on pooled connections. Use separate tool, app and evaluation roles. Tool connections execute parameterized reads over approved projections.

## Replay and point-in-time rules

Import the synthetic fixture separately from replay. Investigation tools restrict history to the case’s fixture and earlier event keys `(occurred_at, source_sequence)`. A case enters the queue after the replay cursor processes its transaction. The explorer shows the shared fixture and marks alerts based on workspace-scoped cases. Give the scorer and tools the same cutoff so a preloaded fixture cannot reveal future behavior. Persist score, case creation if applicable, and replay cursor advancement atomically. A failed event can be retried with its original key.

Compute customer attempt and decline counts in trailing 5-minute, 1-hour, and 24-hour windows. Use trailing 30-day amount mean, variance and count for a z-score, with an explicit insufficient-history feature. Add distance from home, distance and elapsed time since the last reliable physical event, and prior device and merchant seen flags. Use merchant attempt statistics observable at the cutoff. Transaction geography distinguishes an observed physical point from an IP-derived or remote signal. Preserve missingness instead of inventing coordinates or travel speed. A label, an episode tag, an eventual chargeback, or a lifetime aggregate is excluded from scoring and tools. [Fraud Detection Handbook](https://fraud-detection-handbook.github.io/fraud-detection-handbook/)

Provider responses are cached on disk. When quotas are exhausted or the kill switch is set, use a versioned recording linked to the shared fixture and label it as replay. Show “Synthetic data only. Don’t enter real personal data.” at signup and the notes field. Notes stay workspace-scoped and out of prompts and logs.

Phase 1 should report scenario counts, genuine lookalike counts, realized prevalence, distributions by channel and week, missingness, and fixture size from an actual run. Test seed reproducibility, temporal ordering, label isolation, scenario invariants, and absence of duplicate source keys. See the [evaluation plan](EVAL_PLAN.md) for split rules.
