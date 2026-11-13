# Phase 2 scorer results

Model `lgbm-367c9bee181a850b` uses 44 point-in-time features and the default INR fixture. The locked probability threshold is **0.042512972997826436**. The scorer met the recall and alert targets on validation. Recall fell to **44.2%** on the untouched test and **58.6%** on the shifted fixture. The threshold was held fixed.

## Cohorts and selection

The default 180-day fixture uses these half-open UTC windows. An episode spanning a boundary is excluded from all metric cohorts, and its observable transactions remain eligible as history. The default run excluded zero spanning episodes.

| Cohort | Start (inclusive) | End (exclusive) | Attempts | Fraud |
| --- | --- | --- | ---: | ---: |
| Warm-up | 2025-01-01 | 2025-01-31 | History only | — |
| Fit | 2025-01-31 | 2025-04-19 | 17,806 | 112 |
| Calibration | 2025-04-19 | 2025-05-01 | 2,543 | 3 |
| Validation | 2025-05-01 | 2025-05-31 | 6,991 | 20 |
| Test | 2025-05-31 | 2025-06-30 | 6,908 | 52 |

The fit compares logistic regression, unweighted LightGBM and LightGBM with a positive weight of 30. The weight is the training negative-to-positive ratio capped at 30. Validation and test keep natural prevalence. LightGBM uses 140 rounds, depth at most four, and one CPU thread. A logistic calibrator maps each booster’s raw margin to an estimated fraud probability.

| Validation candidate at review capacity | Average precision | Precision | Recall | Alerts / 1,000 |
| --- | ---: | ---: | ---: | ---: |
| logistic | 0.304 | 9.1% | 95.0% | 29.90 |
| lightgbm_unweighted | 0.503 | 9.1% | 95.0% | 29.90 |
| lightgbm_weighted | 0.538 | 9.1% | 95.0% | 29.90 |

Of the LightGBM candidates meeting both validation constraints, weighted LightGBM had the highest average precision. Its locked operating point is the highest observed validation score retaining at least 90% recall within 30 alerts per 1,000 attempts. The capacity table above compares the candidates at approximately the same alert volume.

## Locked operating point

| Cohort | TP | FP | FN | TN | Precision | Recall | AP | Alerts / 1,000 | Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Validation | 18 | 27 | 2 | 6,944 | 40.0% | 90.0% | 0.538 | 6.44 | 0.00191 |
| Untouched test | 23 | 33 | 29 | 6,823 | 41.1% | 44.2% | 0.335 | 8.11 | 0.00724 |
| Shifted test | 17 | 46 | 12 | 8,106 | 27.0% | 58.6% | 0.373 | 7.70 | 0.00300 |

AP is average precision, the reported precision-recall summary. The shift run uses seed 1730, 15% higher amount medians, and 20% higher activity.

| Scenario | Untouched test caught / fraud | Shifted test caught / fraud | Untouched legitimate lookalikes alerted / total |
| --- | ---: | ---: | ---: |
| account_takeover | 5/11 (45%) | 3/6 (50%) | 2/5 |
| card_testing | 5/8 (62%) | 6/6 (100%) | 8/16 |
| impossible_travel | 0/2 (0%) | 0/1 (0%) | 0/0 |
| merchant_collusion | 4/6 (67%) | — (0 fraud) | 12/20 |
| mule_cash_out | 5/18 (28%) | 0/6 (0%) | 1/9 |
| new_device_high_value | 3/4 (75%) | 2/3 (67%) | 2/4 |
| upi_collect_scam | — (0 fraud) | — (0 fraud) | 3/7 |
| upi_sim_swap | — (0 fraud) | 2/2 (100%) | 0/0 |
| velocity_burst | 1/3 (33%) | 4/5 (80%) | 3/8 |

The default test window missed 13 of 18 mule/cash-out attempts and both impossible-travel attempts. It contained no labeled collect-request scams or SIM-swap attacks. Thirty-one of 33 false positives came from designed lookalike episodes, including 12 merchant-collusion lookalikes. Validation covered only five fraud scenarios, with zero positive examples for mule cash-out. That sparse coverage limits how much the selected threshold can tell us about later episodes.

## Calibration and explanations

The calibrator saw three fraud attempts. In the untouched window the highest probability bin contained 12 attempts with mean estimated probability 74.0% and observed fraud of 16.7%. Treat these probabilities as estimates for the synthetic demo. The CLI exports reliability bins and full precision-recall coordinates for validation and both test cohorts.

LightGBM’s native TreeSHAP values are signed contributions in raw-margin space. The base margin plus every contribution reconstructs the booster’s raw margin. The API returns the five largest absolute contributions. Calibration is applied after the margin is computed.

## Reproduce

```sh
uv sync --locked
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=backend uv run python -m inquest.evaluation.train
```

On macOS, install the LightGBM OpenMP runtime with `brew install libomp`. Output goes to `artifacts/scorer/`, including the LightGBM model, manifest, validation candidates, and machine-readable evaluation. Use `--validation-only` to stop before scoring the test windows. The small default model and its manifest are checked in under `models/scorer/` so Compose can start with the evaluated scorer. The manifest includes the training fixture and model digests.

## Serving check

The local Linux ARM64 API container answered 100 score requests with four concurrent clients in 0.26 seconds. Its cgroup reported a peak of 103,321,600 bytes (98.5 MiB) against the 512 MiB limit. This check covered database-backed scoring and explanations, with Postgres in its own container. The full simulator and investigation workload remains to be measured.

A repeat of the training command on the same locked local toolchain produced byte-identical model and manifest files.
