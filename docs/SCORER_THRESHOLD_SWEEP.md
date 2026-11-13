# Phase 2 threshold follow-up

The active scorer is `lgbm-5e143a31879bae22` with a fixed threshold of **0.0087867826518**. It met the target of at least 90% recall within 30 alerts per 1,000 attempts on validation and both fresh synthetic tests. The [initial results](SCORER_RESULTS.md) preserve the earlier model and its held-out shortfall.

## What changed

The original model caught 45 of 52 fraud attempts (86.5%) at the alert ceiling when swept on the previously inspected test scores. This retrospective diagnostic showed the effect of threshold choice and was excluded from model selection. The refit adds point-in-time recipient burst counts, recent distinct and new senders, UPI push counts, inter-attempt timing, amount similarity, prior recipient familiarity, and short-interval travel distance. Existing amount and velocity features remain available.

Fit on three earlier worlds using seeds 1729, 2101 and 2102. Independent worlds with seeds 2103 and 2104 supplied calibration and validation. Those worlds share calendar dates and have separate generated entities and histories. Fresh later worlds use seeds 2105 and 2106. Each world reserves the first 30 days for history and excludes episodes that began during warm-up from its measured cohort. The shifted test uses 15% higher amount medians and 20% higher activity. The generator and lookalike rules were held fixed.

| Cohort | Attempts | Fraud attempts |
| --- | ---: | ---: |
| Fit | 81,861 | 440 |
| Calibration | 40,142 | 222 |
| Validation | 39,852 | 183 |
| Fresh test | 39,734 | 201 |
| Shifted test | 47,384 | 203 |

## Validation sweep

Evaluate every distinct observed validation score with tied scores included together. Choose the model and threshold that catch the most fraud within the alert ceiling. For equal fraud counts, choose fewer alerts. At a 30-per-1,000 cap, the unweighted, 10× weighted and 30× weighted candidates caught 168, 166 and 172 of 183 fraud attempts, respectively. The table shows the best threshold for each example budget on the selected 30× model.

| Maximum alerts / 1,000 | Threshold | Actual alerts / 1,000 | Recall | Precision |
| ---: | ---: | ---: | ---: | ---: |
| 5 | 0.39940923 | 4.72 | 45.4% | 44.1% |
| 10 | 0.15984419 | 9.91 | 79.8% | 37.0% |
| 15 | 0.031592677 | 13.50 | 91.3% | 31.0% |
| 20 | 0.01055611 | 19.92 | 92.9% | 21.4% |
| 25 | 0.0087867827 | 22.46 | 94.0% | 19.2% |
| 30 | 0.0087867827 | 22.46 | 94.0% | 19.2% |
| 40 | 0.0087867827 | 22.46 | 94.0% | 19.2% |
| 50 | 0.0038335727 | 48.23 | 95.1% | 9.1% |
| 75 | 0.0027748535 | 67.47 | 95.6% | 6.5% |
| 100 | 0.0021900727 | 84.91 | 96.2% | 5.2% |

## Locked test results

| Cohort | Fraud caught | Recall | Precision | Alerts / 1,000 | Average precision | Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Fresh test | 188/201 | 93.5% | 19.2% | 24.66 | 0.369 | 0.00370 |
| Shifted test | 187/203 | 92.1% | 17.7% | 22.26 | 0.418 | 0.00303 |

| Scenario | Fresh test caught / fraud | Shifted test caught / fraud |
| --- | ---: | ---: |
| account_takeover | 28/28 | 23/23 |
| card_testing | 38/38 | 37/37 |
| impossible_travel | 6/6 | 7/7 |
| merchant_collusion | 30/30 | 27/27 |
| mule_cash_out | 25/30 | 29/35 |
| new_device_high_value | 9/9 | 9/9 |
| upi_collect_scam | 15/20 | 15/19 |
| upi_sim_swap | 21/21 | 18/18 |
| velocity_burst | 16/19 | 22/28 |

The fresh test missed five collect-request scams, five mule/cash-out attempts and three velocity bursts. It generated 792 false positives. The shifted test generated 868. The aggregate recall target is met on these synthetic worlds, while these scenario misses and the high share of legitimate alerts remain important for agent evaluation.

## Reproduce

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=backend uv run python -m inquest.evaluation.refit
```

The run writes the complete threshold sweep, held-out metrics, calibration bins, model, and manifest to `artifacts/scorer-refit/`. Use `--validation-only` to run selection without generating the test worlds. The manifest identifies the fitted cohort separately from the shared fixture used by the scoring API.
