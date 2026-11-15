# Phase 5 agent evaluation

The two full-agent runs retained all nine sampled fraud alerts per cohort and cleared zero of eight sampled legitimate alerts per cohort. Every case stayed in review. Both runs used the fixed LightGBM threshold and compared recommendations at the approval checkpoint with synthetic ground truth.

## Method

The initial cohort uses seed 2105. The shifted confirmation uses seed 2106 with 15% higher category medians and 20% higher activity. The pilot used four alerts from seed 2104. Each main cohort sampled one fraud alert per scenario and four legitimate alerts from each of two groups. Case IDs were frozen before running the paired arms. Inverse inclusion weights estimate alert-population rates. The per-scenario sample is too small for uncertainty intervals.

The ML baseline retains every scorer alert and treats below-threshold attempts as released in the simulation. The full agent uses all enabled capabilities. No tools supplies the focal transaction as fixed input. No policy keeps entity tools enabled. No self-check keeps output validation and measures citations independently. Each run and its case outcomes are stored in Postgres.

## Results

### Original agent · held-out world

39,734 eligible transactions, 201 fraud attempts, and 980 ML alerts. The scorer captured 188 fraud attempts. Each arm saw the same 17 alerts, including 9 fraudulent attempts.

| Arm | Legit alerts cleared | Alert fraud retained | End-to-end recall | Resolved accuracy | Coverage | Grounded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ML only | 0.0% | 100.0% | 93.5% | — | 0.0% | — |
| Full agent | 0.0% | 100.0% | 93.5% | — | 0.0% | 14/17 |
| No tools | 0.0% | 100.0% | 93.5% | — | 0.0% | 17/17 |
| No policy retrieval | 0.0% | 100.0% | 93.5% | — | 0.0% | 14/17 |
| No self-check | 0.0% | 100.0% | 93.5% | — | 0.0% | 6/17 |

The rate columns use sampling weights. Grounding counts reports that match their cited evidence and satisfy the decision rubric. Failures count as escalations. ML-only escalations represent alerts sent to the review queue.

| Arm | Releases / blocks / escalations | Failures | Policy calls | Mean tools | Requests / retries / cache hits | Input / output tokens | p50 / p95 seconds | List-price equivalent |
| --- | --- | ---: | ---: | ---: | --- | --- | --- | ---: |
| ML only | 0 / 0 / 17 | 0 | 0 | 0.00 | 0 / 0 / 0 | 0 / 0 | — / — | $0.0000 |
| Full agent | 0 / 0 / 17 | 3 | 0 | 2.94 | 45 / 0 / 0 | 27,337 / 5,985 | 1.90 / 2.23 | $0.0038 |
| No tools | 0 / 0 / 17 | 0 | 0 | 0.00 | 17 / 0 / 0 | 6,826 / 3,134 | 0.68 / 1.06 | $0.0015 |
| No policy retrieval | 0 / 0 / 17 | 3 | 0 | 2.88 | 47 / 0 / 0 | 27,739 / 6,164 | 1.84 / 3.38 | $0.0039 |
| No self-check | 0 / 0 / 17 | 1 | 0 | 2.94 | 36 / 0 / 0 | 21,043 / 5,057 | 1.37 / 2.22 | $0.0031 |

| Sampled fraud scenario | Scorer caught / fraud | Full agent outcome |
| --- | ---: | --- |
| account_takeover | 28/28 | escalate 1 |
| card_testing | 38/38 | escalate 1 |
| impossible_travel | 6/6 | escalate 1, failures 1 |
| merchant_collusion | 30/30 | escalate 1 |
| mule_cash_out | 25/30 | escalate 1 |
| new_device_high_value | 9/9 | escalate 1 |
| upi_collect_scam | 15/20 | escalate 1 |
| upi_sim_swap | 21/21 | escalate 1 |
| velocity_burst | 16/19 | escalate 1 |

### Evidence-focused agent · fresh shifted world

47,384 eligible transactions, 203 fraud attempts, and 1,055 ML alerts. The scorer captured 187 fraud attempts. Each arm saw the same 17 alerts, including 9 fraudulent attempts.

| Arm | Legit alerts cleared | Alert fraud retained | End-to-end recall | Resolved accuracy | Coverage | Grounded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ML only | 0.0% | 100.0% | 92.1% | — | 0.0% | — |
| Full agent | 0.0% | 100.0% | 92.1% | — | 0.0% | 16/17 |
| No tools | 0.0% | 100.0% | 92.1% | — | 0.0% | 17/17 |
| No policy retrieval | 0.0% | 100.0% | 92.1% | — | 0.0% | 17/17 |
| No self-check | 0.0% | 100.0% | 92.1% | — | 0.0% | 5/17 |

| Arm | Releases / blocks / escalations | Failures | Policy calls | Mean tools | Requests / retries / cache hits | Input / output tokens | p50 / p95 seconds | List-price equivalent |
| --- | --- | ---: | ---: | ---: | --- | --- | --- | ---: |
| ML only | 0 / 0 / 17 | 0 | 0 | 0.00 | 0 / 0 / 0 | 0 / 0 | — / — | $0.0000 |
| Full agent | 0 / 0 / 17 | 1 | 17 | 6.00 | 29 / 1 / 0 | 18,726 / 5,856 | 1.60 / 3.49 | $0.0032 |
| No tools | 0 / 0 / 17 | 0 | 0 | 0.00 | 18 / 0 / 0 | 5,936 / 4,139 | 0.78 / 6.62 | $0.0017 |
| No policy retrieval | 0 / 0 / 17 | 0 | 0 | 5.00 | 31 / 0 / 0 | 18,058 / 6,641 | 1.45 / 2.58 | $0.0033 |
| No self-check | 0 / 0 / 17 | 0 | 17 | 6.00 | 0 / 0 / 17 | 0 / 0 | — / — | $0.0000 |

| Sampled fraud scenario | Scorer caught / fraud | Full agent outcome |
| --- | ---: | --- |
| account_takeover | 23/23 | escalate 1 |
| card_testing | 37/37 | escalate 1 |
| impossible_travel | 7/7 | escalate 1 |
| merchant_collusion | 27/27 | escalate 1 |
| mule_cash_out | 29/35 | escalate 1 |
| new_device_high_value | 9/9 | escalate 1, failures 1 |
| upi_collect_scam | 15/19 | escalate 1 |
| upi_sim_swap | 18/18 | escalate 1 |
| velocity_burst | 22/28 | escalate 1 |

Live latency excludes quota pacing between cases. The focused no-self-check arm reused 17 cached drafts and recorded p50 and p95 latencies of 0.069 and 0.142 seconds. All arms had the same weighted alert triage accuracy within each cohort, at 19.2% on the original cohort and 17.7% on the shifted cohort. End-to-end triage accuracy was 98.0% and 98.1%, respectively, dominated by legitimate transactions below the scorer threshold. Costs are calculated from reported input and output tokens. Unknown consumption is tracked in token reservations and actual billing was unavailable. [Groq model pricing](https://console.groq.com/docs/model/openai/gpt-oss-20b) · [Groq rate limits](https://console.groq.com/docs/rate-limits)

## Failure analysis

The original planner retrieved zero policy excerpts for the 17 full-arm cases. The no-policy ablation therefore tested the effect of hiding the option in the prompt, while the focused comparison tested the presence of actual retrieved content. The original no-self-check arm passed independent verification on 6 of 17 cases. Its other 11 cases include one invalid report and 10 reports with unsupported evidence. The original full arm passed on 14 of 17. One invalid report came from the impossible-travel alert at sequence `17270`.

The focused plan ran velocity, device, merchant and geography checks before asking Groq to synthesize, and ran policy retrieval in the full arm. The extra evidence helped establish why alerts stayed unresolved. Sequence `33804` had 16 prior attempts on the same device and zero with that merchant in the 30-day window. In all eight sampled legitimate alerts, the merchant check found zero prior attempts. All eight fell outside the release rubric, which requires at least three prior attempts on the device and three with the merchant. The mule alert at `25627` retrieved the generic release section `P01/release`, demonstrating that query routing can still miss scenario-specific policy. The new-device, high-value case at `17885` exhausted its investigation budget while generating a report.

The focused agent remains an evaluation variant because the release rate was zero. Testing other signals of legitimate activity would require a larger fresh cohort and a paired comparison of the two planners. The original and shifted results measure performance on different transaction distributions.

[Runbook](AGENT_EVALUATION_RUNBOOK.md) · [Original aggregates](../fixtures/evaluations/phase5-held_out.json) · [Shifted aggregates](../fixtures/evaluations/phase5-confirmation.json)
