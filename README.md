# Inquest

Inquest is a portfolio project for investigating synthetic card and UPI-style payments. Its planned workflow combines a fraud scorer, a read-only evidence-gathering agent, and a human decision.

**Synthetic data only. Don’t enter real personal data.**

## Local development

Run `docker compose up --build` and check `http://localhost:8000/health`. The API schema is available at `http://localhost:8000/docs`.

For a native Python 3.12 environment, run `uv sync --locked`, then run `uv run pytest`, `uv run ruff check`, and `uv run mypy`.

See the [project plan](docs/PLAN.md) for phase gates and the [decision log](docs/DECISIONS.md) for engineering trade-offs.
