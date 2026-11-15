# Phase 4 investigation runtime

**Synthetic data only. Don’t enter real personal data.**

The API starts a durable investigation job for an authenticated workspace case. One worker at a time executes jobs under a Postgres session lock. LangGraph checkpoints synchronously in a dedicated schema. After gathering typed observations, the graph validates the draft, checks every citation against its exact observed value, and saves the report before pausing at the approval interrupt. A malformed or unsupported draft gets one repair attempt. The application records a conservative escalation if verification still fails.

The verifier checks factual grounding and two-source corroboration for block and release recommendations. It does not establish the accuracy of a recommendation against ground truth. That comparison belongs to Phase 5.

A verified analyst submits approve, override, or escalate with the expected case version and an idempotency key. The API commits the decision, optional note, and resume job together. A worker resumes the graph with the stored decision ID. The graph reads that decision and applies the local case disposition. There is no payment integration.

## Local setup

```sh
docker compose up --build -d --wait
PYTHONPATH=backend uv run python -m inquest.investigation.demo
```

The second command provisions a local workspace, one case from the shared fixture, and a one-hour bearer session. Treat the output token as a credential. Phase 6 adds GitHub and Google sign-in backed by Inquest sessions. The local provisioner uses the migration role and is intended for a development database.

| Request | What to supply |
| --- | --- |
| `POST /api/v1/cases/{case_id}/investigations` | Bearer session and `Idempotency-Key` |
| `GET /api/v1/investigations/{id}` | Bearer session. Response includes the mode, status, report, and case version. |
| `GET /api/v1/investigations/{id}/events` | Bearer session and optional `Last-Event-ID`. Use an authenticated fetch stream. |
| `POST /api/v1/investigations/{id}/decision` | Bearer session, `Idempotency-Key`, and JSON with `operation` and `expected_case_version`. Supply `action` for override and an optional `note`. |

The event stream emits committed job, tool, report and decision events in sequence. It closes once it has delivered the events for review, completion or failure. Reconnect with the last event ID after a disconnect or after submitting a decision. Timeline summaries describe the recorded tool call or status.

## Providers, quotas and replay

Compose loads `INQUEST_GROQ_API_KEY` from the root `.env` and passes it to the API container. Groq GPT-OSS 20B is the default live provider. The DB switch starts off. To enable model calls on the local database for a smoke test, run:

```sh
docker compose exec -T db psql -U postgres -d inquest \
  -c 'UPDATE operations.runtime_controls SET llm_enabled = true WHERE singleton'
```

Set the value to `false` to stop new outbound reservations. A provider request already in flight can finish. Native Gemini use requires `uv sync --extra gemini`, `INQUEST_LLM_PROVIDER=gemini`, and `INQUEST_GEMINI_API_KEY`. Its live project quota has not been verified.

The worker allows up to six planning rounds, eight tool calls, one repair, and a 90-second provider-call window. The 6,000-token investigation budget and global daily budget reserve conservatively before each outbound call, including retries. Successful calls reconcile to provider-reported usage. Ambiguous failures keep the reservation. The workspace default is eight live starts per UTC day. Investigation starts are limited to ten per source IP per minute. The local proxy configuration ignores forwarded headers. A stable IP HMAC secret and ingress configuration are needed for a hosted installation. Public signup limits belong to the hosted signup endpoint.

The SQLite cache persists on a local Compose volume. Cache keys include provider identity, prompt version and exact prompt content. On quota or provider failure, the worker uses a checked-in recording if one matches the focal fixture transaction and its facts verify. The initial corpus contains a verified live Groq recommendation captured for default fixture attempt 150 and rebound to the current run’s evidence IDs. Other attempts show an inconclusive escalation when a recording is unavailable. Recorded and live runs have separately labeled modes.

## Phase 4 verification

The local Compose API completed one live Groq investigation on attempt 150. It accounted for 1,384 provider tokens, delivered nine ordered events before approval, emitted completion after reconnect, and peaked at approximately 129 MiB against the 512 MiB API limit. This was a synthetic workflow smoke test. The local LLM switch was returned to off after the test. [Groq JSON mode](https://console.groq.com/docs/structured-outputs) · [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) · [FastAPI SSE](https://fastapi.tiangolo.com/tutorial/server-sent-events/)

The integration suite exercises approval after worker replacement, stale versions, idempotent decision replay, ordered SSE, a repaired citation, and quota fallback without an outbound model request. Run it with `INQUEST_TEST_POSTGRES=1 uv run pytest -q` after starting Compose.
