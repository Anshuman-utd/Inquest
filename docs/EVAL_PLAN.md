# Evaluation plan

Phase 0 approved protocol · 14 November 2026

The evaluation asks whether the investigation helps analysts release legitimate alerts while retaining fraud cases for review. Synthetic ground truth supports reproducible comparisons and specific failure analysis. It provides no estimate of live payment performance. Phase 0 contains no measured results.

## Scorer protocol

- Partition by event time into a history warm-up followed by chronological train, validation, and untouched test windows. Propose roughly 60/20/20 after warm-up, with boundaries recorded as dates before training. Drop episodes crossing split boundaries from metric cohorts. Preserve earlier observable events as history and keep episode truth out of all inputs.
- Build point-in-time features offline using the same definitions and cutoffs as replay. Test parity for same-timestamp ordering, novel entities, and missing values. Report the realized fraud rate and class counts by split.
- Compare logistic regression and shallow LightGBM. Test class weighting against an unweighted fit using validation precision and recall. Preserve natural prevalence for validation and test. If the product displays a fraud probability, fit a simple calibrator on a held-out slice of validation and check calibration with a reliability plot and Brier score. Use a separate validation slice for the operating point. Label raw, uncalibrated output as a risk score.
- Choose the highest threshold that meets a predeclared validation recall target and review-capacity constraint. The approved starting target is at least 90% recall and at most 30 alerts per 1,000 transactions. If the targets conflict, publish the trade-off and seek agreement before opening the test results.
- Report precision, recall, average precision as the PR summary, confusion counts, alerts per 1,000 and a precision-recall curve. Report per-scenario recall, including below-threshold misses. Include hard legitimate cases with overlapping signal combinations, such as high-value travel purchases on a new phone and legitimate UPI transfers following SIM replacement. Check native LightGBM contributions sum to the raw margin with the bias term and use absolute magnitude for ranking while retaining sign. State clearly that contributions explain the model's margin and remain separate from calibrated probability.

Chronological validation approximates scoring future attempts from past behavior and avoids random splits that share overlapping history and episodes. Add a separately seeded, parameter-shifted world as a robustness check. [Fraud Detection Handbook validation](https://fraud-detection-handbook.github.io/fraud-detection-handbook/Chapter_5_ModelValidationAndSelection/ValidationStrategies.html) · [LightGBM Booster API](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.Booster.html) · [SHAP TreeExplainer](https://shap.readthedocs.io/en/latest/generated/shap.TreeExplainer.html)

## Agent protocol

Freeze the dataset manifest, model artifact, threshold, policies, prompts, provider/model, configuration, and sampled case IDs before the main run. Pilot on validation cases to check cost and correctness. Use one held-out alert cohort and identical case snapshots for each arm. Evaluate all alerts if quota permits. Otherwise take a reproducible probability sample stratified by truth and scenario, and record stratum sizes and inclusion probabilities. Use weighting for estimates representing the alert population. Keep a targeted challenge set separate for failure analysis.

| Arm | What it does |
| --- | --- |
| ML-only | The locked score gate sends flagged attempts to review and treats below-threshold attempts as released in the simulation. |
| ML plus agent | The gate selects the same alerts. The graph recommends release, block, or escalation. |
| No tools | The graph sees the focal transaction and scorer output, with read tools and policy retrieval disabled. |
| No policy RAG | Entity tools and the same minimum evidence rubric stay enabled. Scenario-specific retrieved excerpts are omitted. |
| No self-check | Disable claim verification in the offline harness. Keep Pydantic validation and human action controls. Score grounding independently against stored observations. |

Run to the approval checkpoint. The measured outcome is the recommendation. An explicit test actor may exercise resume in integration tests. Keep below-threshold cases as released in every end-to-end comparison. Provider errors and timeouts count as escalations and are reported as failures. Freeze the initial results before prompt or policy changes. Any retest on the same cases is exploratory and final confirmation uses a fresh cohort.

## Definitions and report

- **Resolved decision accuracy** is correct block or release recommendations divided by all block or release recommendations. Publish coverage as that denominator divided by all evaluated attempts. Also report correct resolved decisions divided by all attempts, counting unresolved cases as unresolved rather than successful. The alert-only ML baseline has zero resolved decisions and undefined resolved accuracy.
- **Triage accuracy** compares the binary choice to retain for intervention (review, block or escalate) or release against the fraud label. This yields a comparable accuracy for ML-only and each agent arm. Show class counts and alert-only and full-stream values so class imbalance stays visible.
- **False-positive reduction** is the share of baseline legitimate alerts correctly recommended for release. Also show how many legitimate alerts were blocked, escalated, or hit an error, so reduced review volume cannot hide bad blocks.
- **Fraud recall retained** is the share of baseline fraudulent alerts recommended for block or escalation. Show successful escalations and error-driven escalations separately. End-to-end retention divides retained fraud by all test fraud, including attempts the scorer missed.
- **Scenario performance** includes case counts, correct block or release rate, escalation, bad release, and evidence-grounding failure by scenario and genuine lookalike group. Aggregate results include an episode-clustered interval when sample size supports it.
- **Operational measures** include p50/p95 time to recommendation, tool calls, provider requests, retries, cache hits, token usage, quota consumption, equivalent list-price cost and actual billed cost when verifiable. Report live and cache-only timing separately. Track evidence validity with the same independent verifier across arms.

Log per-case records and aggregate results to Postgres and export a versioned results table for the UI. Record eligibility and denominators, failure codes, cohort hash, seed, git revision, model/corpus/prompt hashes, cache status and timestamp. Review misclassified, unsupported, abstained and scorer-missed cases by scenario. Record the cause, a linked example, and any follow-up run. Publish only measured results in the README.

## Public benchmark decision

Use the synthetic world for the first milestone. The ULB credit-card data supports an optional standalone imbalance and scorer sanity check, but its anonymized PCA inputs cannot supply customer and device evidence. IEEE-CIS offers joinable transaction and identity tables with anonymized fields and would add work to align a separate feature pipeline. PaySim is the closest analog for mobile transfers and cash-out, but its simulator targets a different transaction model. Revisit public data only if an isolated external benchmark would answer a specific scorer question. Keep any resulting benchmark separate from the agent results and document its dataset terms. [ULB dataset](https://www.kaggle.com/mlg-ulb/creditcardfraud/) · [IEEE-CIS competition data](https://www.kaggle.com/c/ieee-fraud-detection/data) · [PaySim author thesis](https://bth.diva-portal.org/smash/get/diva2%3A955852/FULLTEXT06.pdf)

## Phase 2 default cohort

The 180-day default fixture uses day offsets 0–29 for history warm-up, 30–107 for fitting, 108–119 for calibration, 120–149 for operating-point selection, and 150–179 for the final test. Use half-open UTC windows. Exclude every labeled episode spanning a split boundary from metric and fitting cohorts, while retaining its observable transactions in historical features. The shift fixture uses seed 1730, 15% higher category medians and 20% higher activity. Use the same locked model, calibration and threshold for both test windows.

## Phase 5 sampling and reporting

The original comparison uses the locked Phase 2 scorer and independent test world seed 2105. The shifted confirmation uses seed 2106, 15% larger category medians, and 20% higher activity. The live validation pilot uses seed 2104. The first 30 days supply history. Episodes crossing warm-up are omitted from metrics. The sampled alert IDs, fixture configuration, scorer hash, threshold, group sizes, and sampling seed are frozen before each run.

The paid-equivalent cost uses provider-reported input and output tokens at public list prices. Quota accounting also includes conservative reservations for failed responses. Latency measures time inside the graph and includes request retries. Pacing between cases is excluded. Billing is reported only when independently verified.

Sample each fraud scenario and two legitimate strata (routine and scenario-tagged) under free-tier quota. Use inverse inclusion weights for population estimates and publish the raw sample counts beside them. A single sampled case per fraud scenario makes its individual result descriptive. The design does not support an episode-clustered uncertainty interval for the fraud strata.
