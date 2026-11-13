# Inquest

Inquest is a portfolio project for investigating synthetic card and UPI-style payments. Its planned workflow combines a fraud scorer, a read-only evidence-gathering agent, and a human decision.

**Synthetic data only. Don’t enter real personal data.**

## Local development

Run `docker compose up --build` and check `http://localhost:8000/health`. Compose starts Postgres and applies the database migration before starting the API. Check `/ready` for database readiness. The API schema is available at `http://localhost:8000/docs`.

For a native Python 3.12 environment, run `uv sync --locked`, then run `uv run pytest`, `uv run ruff check`, and `uv run mypy`.

With the Compose database running, run `INQUEST_TEST_POSTGRES=1 uv run pytest` to exercise the tenant boundary against Postgres. The API role can read the shared fixture and can access workspace records only within a scoped transaction. The migration and test setup use a separate database role.

See the [project plan](docs/PLAN.md) for phase gates and the [decision log](docs/DECISIONS.md) for engineering trade-offs.
