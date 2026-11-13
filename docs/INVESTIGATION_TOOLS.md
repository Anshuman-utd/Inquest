# Phase 3 investigation tools and policy retrieval

The internal entry point is [`InvestigationTools.execute`](../backend/inquest/investigation/tools.py). The graph worker supplies a trusted `ToolScope` with workspace, analyst, and investigation IDs plus a positive call sequence. The model supplies one allowlisted tool request. All other input fields are rejected. The tool API has no public HTTP route.

## Transaction evidence

The tenant layer verifies membership and resolves the investigation through its workspace case and replay. A focal transaction beyond the replay cursor is unavailable. Prior rows must share its dataset and currency and precede both the focal source sequence and its chronological event key. The fixture is immutable, so advancing the replay leaves prior evidence unchanged. The cutoff includes the dataset ID, UTC timestamp and source sequence.

Transaction queries use the fixture reader role in repeatable-read, read-only Postgres transactions with a three-second statement timeout. History returns up to 20 recent attempts with full-window counts and a truncation flag. All results are capped at 16 KiB of serialized JSON. Missing geographic evidence stays unknown. Time and distance refer to the approximate city coordinates in the synthetic fixture. Velocity reports the trailing 5 minutes, hour and day alongside the count in the preceding 29 days. The baseline divides by all 29 days, including days with no observed activity.

| Tool | Model input | Evidence |
| --- | --- | --- |
| `get_transaction` | Tool name | Focal transaction |
| `get_customer_profile` | Tool name | Home city and observed 30-day history summary |
| `get_customer_history` | Optional `window_days` from 1–30, default 7 | Counts, totals and up to 20 prior attempts |
| `velocity_check` | Tool name | Trailing windows and baseline |
| `geo_mismatch_check` | Tool name | Current and prior physical city, distance, elapsed time and implied speed where defined |
| `device_check` | Tool name | Prior device use, distinct recent customers and instruments, and re-registration signal |
| `merchant_risk_lookup` | Tool name | Merchant profile and recent recipient concentration, repeated amounts and UPI push counts |
| `search_policy_docs` | `query` of at most 240 characters | Up to three versioned excerpts or an explicit no-match |

Successful results carry a UUIDv5 evidence ID derived from the investigation ID and call sequence. Database failures after scope resolution can return typed unavailable evidence. Unauthorized or unavailable scope fails before exposing a result. Phase 4 will persist request/result pairs, reject conflicting reuse of a call sequence, and attach these IDs to the report verifier and event stream.

## Policy retrieval

In-process BM25 ranks sections across the 12 checked-in playbooks. The index uses lexical tokens and an explicit alias list for domain phrases. Ties sort by stable section ID. Each match includes its exact excerpt, policy and section IDs, version, and section hash. The corpus hash covers section hashes and ranker settings. The graph can pin that hash to make the retrieval configuration auditable. [Robertson and Zaragoza, BM25](https://doi.org/10.1561/1500000019)

The [query fixture](../fixtures/policy_queries.json) contains 16 independently labeled policy queries and two negative controls. The expected policy appeared first for **13/16** and within the first three sections for **14/16**. Both negative controls returned no match. The two top-three misses involved clearing a flagged payment and purchases in quick succession after a failed retry. This is a small policy-level check. Case-level grounding and policy ablations belong to the agent evaluation.

## Verify locally

```sh
docker compose up --build -d --wait
INQUEST_TEST_POSTGRES=1 uv run pytest -q backend/tests/test_investigation_tools.py backend/tests/test_policy_retrieval.py
```

Compose supplies the development tool database URL. For a native run with the default local ports, the built-in settings use the same reader account. The tests create and clean up scoped cases, exercise all eight tools, and verify that the reader role cannot write fixture data or access notes and evaluation truth.
