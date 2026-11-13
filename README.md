# Inquest

Inquest is a portfolio project for investigating synthetic card and UPI-style payments. Its planned workflow combines a fraud scorer, a read-only evidence-gathering agent, and a human decision.

**Synthetic data only. Don’t enter real personal data.**

## Phase 1 status

The API exposes liveness and database readiness. Postgres holds the shared fixture, evaluation truth, and workspace-scoped case records. Phase 2 adds model training and scoring. GitHub OAuth signup, quota enforcement, provider caching and investigation replay are planned for the phases that expose hosted access and live investigations.

## Local development

Run `docker compose up --build` and check `http://localhost:8000/health`. Compose starts Postgres and applies the database migration, and imports the shared synthetic fixture before starting the API. Check `/ready` for database readiness. The API schema is available at `http://localhost:8000/docs`.

For a native Python 3.12 environment, run `uv sync --locked`, then run `uv run pytest`, `uv run ruff check`, and `uv run mypy`.

With the Compose database running, run `INQUEST_TEST_POSTGRES=1 uv run pytest` to exercise the tenant boundary against Postgres. The API role can read the shared fixture and can access workspace records only within a scoped transaction. The migration and test setup use a separate database role.

## Synthetic fixture

The default configuration is [fixtures/india.json](fixtures/india.json). It defines the seed, INR, Indian cities, local time zone, and category-level amount distributions. Each import uses the fixture content hash as its dataset ID, so repeating the same import leaves the stored data unchanged. Fraud truth lives in a separate Postgres schema.

Generate the [dataset summary](docs/DATASET_SUMMARY.md) with `PYTHONPATH=backend uv run python -m inquest.synthetic.seed --report docs/DATASET_SUMMARY.md`. Add `--config /path/to/config.json` to generate from a different fixture configuration.

The [synthetic policy corpus](policies/README.md) defines the demo’s review and evidence guidelines.

See the [project plan](docs/PLAN.md) for phase gates and the [decision log](docs/DECISIONS.md) for engineering trade-offs.
