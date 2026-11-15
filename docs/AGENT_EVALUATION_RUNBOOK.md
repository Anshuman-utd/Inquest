# Run the agent evaluation

Use a local Compose database. Live calls use the configured Groq free-tier key from the root `.env`. Start with a separate validation pilot before spending quota on a held-out cohort.

```sh
docker compose up --build -d --wait
export PYTHONPATH=backend
uv run python -m inquest.evaluation.agent_cohort pilot artifacts/phase5/pilot.json
uv run --env-file .env python -m inquest.evaluation.agent_runner \
  artifacts/phase5/pilot.json artifacts/phase5/pilot-run --arms full
```

To regenerate the test fixtures and run the complete comparison:

```sh
uv run python -m inquest.evaluation.agent_cohort held_out artifacts/phase5/held_out.json
uv run python -m inquest.evaluation.agent_cohort confirmation artifacts/phase5/confirmation.json
uv run --env-file .env python -m inquest.evaluation.agent_runner \
  artifacts/phase5/held_out.json artifacts/phase5/initial
uv run --env-file .env python -m inquest.evaluation.agent_runner \
  artifacts/phase5/confirmation.json artifacts/phase5/focused --revision focused
```

The runner temporarily enables the local database’s live-call switch for a live comparison and restores it on normal exit or keyboard interruption. It checks each sampled score against the serving feature path, writes each result as it finishes, and reuses completed rows when the run identity is unchanged. The per-investigation and global budget checks apply. If a remaining daily budget is too small to complete a useful comparison, schedule the next run after the quota resets. Failed cases are counted as escalations with their failure code preserved.

```sh
uv run python -m inquest.evaluation.agent_metrics artifacts/phase5/initial/results.json \
  --public-output fixtures/evaluations/phase5-held_out.json
uv run python -m inquest.evaluation.agent_metrics artifacts/phase5/focused/results.json \
  --public-output fixtures/evaluations/phase5-confirmation.json
```

The aggregate exports are served at `GET /api/v1/evaluations`. They contain synthetic cohort counts, estimates, operational metrics, and run provenance. Raw drafts, credentials, notes, and per-case ground truth remain outside the endpoint.

The focused revision uses stable evidence IDs in cache keys and restores the current investigation IDs before verification. To measure cache replay latency, copy `responses.sqlite` into a fresh output directory and run the focused comparison there with `--cache-only`. This preserves the live run's local export. Cache misses are recorded as failures. The original run used investigation-specific evidence IDs. Live reruns can vary with provider responses.
