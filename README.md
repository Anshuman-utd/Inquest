# Inquest

Inquest is a portfolio project for investigating synthetic card and UPI-style payments. Its workflow combines a fraud scorer, a read-only evidence-gathering agent, and a human decision.

**Synthetic data only. Don’t enter real personal data.**

## Analyst workflow

The API scores shared synthetic transactions with a small LightGBM model and returns signed TreeSHAP contributions. Postgres holds the shared fixture, evaluation truth, and workspace-scoped case records. The [investigation tool layer](docs/INVESTIGATION_TOOLS.md) gathers scoped evidence and retrieves versioned policy excerpts. The [investigation runtime](docs/AGENT_RUNTIME.md) adds LangGraph checkpoints, grounded reports, analyst approval, budgets, and reconnectable SSE. The web console supports GitHub and Google sign-in, a workspace case queue, evidence review, a transaction explorer, and held-out evaluations.

## Local development

Add one or both OAuth credential pairs to the root `.env` using the [OAuth setup guide](docs/OAUTH_SETUP.md). Run `docker compose up --build` and open [the console](http://localhost:5173). Compose migrates Postgres, seeds the shared fixture, and starts the API and web proxy. Sign in, open **Simulator**, and select **Start**. Open a queued case and select **Start investigation**. Search for `TX-150` once the cursor has passed 150 to try the existing prerecorded investigation.

The API exposes `/health`, `/ready`, and [interactive docs](http://localhost:8000/docs). The console uses the [pinned OpenAPI contract](docs/openapi.json). For frontend development, run `docker compose up -d api`, then `npm --prefix frontend ci` and `npm --prefix frontend run dev` with the Compose web service stopped. The dev server proxies API traffic to port 8000.

For a native Python 3.12 environment, install `libomp` on macOS with `brew install libomp`. Then run `uv sync --locked`, then run `uv run pytest`, `uv run ruff check`, and `uv run mypy`.

With the Compose database running, run `INQUEST_TEST_POSTGRES=1 uv run pytest` to exercise the tenant boundary against Postgres. The API role can read the shared fixture and can access workspace records only within a scoped transaction. The migration and test setup use a separate database role.

## Score a transaction

With Compose running, get the default dataset and score an example attempt.

```sh
curl -fsS http://localhost:8000/api/v1/scorer
curl -fsS http://localhost:8000/api/v1/datasets/v1-6ad7511a3aebaf4750c16dcd506c93bb04962a0c03867087ae58a41551d120e9/transactions/150/score
```

The score preview reads the shared fixture as of the transaction’s timestamp and source sequence. The response contains the estimated fraud probability, fixed threshold, alert flag, and five signed contributions in raw-margin units. The preview performs no writes. The simulator advances a durable workspace cursor in 500-attempt batches. It creates cases using the locked scorer threshold and preserves earlier cases when replay starts again.

The [scorer results and threshold sweep](docs/SCORER_THRESHOLD_SWEEP.md) give the chronological validation and held-out metrics, the test misses, and the training command.

## Agent evaluation

Both evaluated full-agent versions escalated all 17 sampled alerts per cohort, preserving flagged fraud for review and clearing zero legitimate alerts. The versioned aggregates are served at `GET /api/v1/evaluations`. [Measured results](docs/AGENT_EVALUATION_RESULTS.md) · [Runbook](docs/AGENT_EVALUATION_RUNBOOK.md)

## Synthetic fixture

The default configuration is [fixtures/india.json](fixtures/india.json). It defines the seed, INR, Indian cities, local time zone, and category-level amount distributions. Each import uses the fixture content hash as its dataset ID, so repeating the same import leaves the stored data unchanged. Fraud truth lives in a separate Postgres schema.

Generate the [dataset summary](docs/DATASET_SUMMARY.md) with `PYTHONPATH=backend uv run python -m inquest.synthetic.seed --report docs/DATASET_SUMMARY.md`. Add `--config /path/to/config.json` to generate from a different fixture configuration.

The [synthetic policy corpus](policies/README.md) defines the demo’s review and evidence guidelines.

See the [project plan](docs/PLAN.md) for phase gates and the [decision log](docs/DECISIONS.md) for engineering trade-offs.


## Refresh the console contracts

```sh
PYTHONPATH=backend uv run python -m inquest.export_openapi > docs/openapi.json
npm --prefix frontend run generate:api
```

After updating the serving scorer or shared fixture, regenerate the label-free replay artifact with `PYTHONPATH=backend uv run python -m inquest.console.prepare`. The API verifies the fixture and model identifiers at startup. The replay can run with the model provider disabled. When a case has no matching investigation recording, it receives an inconclusive report for analyst review.
