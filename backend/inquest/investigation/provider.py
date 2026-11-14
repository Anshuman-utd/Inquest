import hashlib
import json
import random
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from time import monotonic, sleep
from typing import Protocol

from groq import APIConnectionError, APIStatusError, Groq
from pydantic import Field

from inquest.investigation.contracts import Contract


class ProviderUnavailable(Exception):
    """The provider or an investigation budget is unavailable."""


class RetryableProviderError(Exception):
    def __init__(self, retry_after: float = 0) -> None:
        self.retry_after = retry_after


class Completion(Contract):
    content: str = Field(max_length=16_384)
    tokens: int = Field(ge=0)


class Provider(Protocol):
    identity: str

    def complete(self, prompt: str, output_tokens: int, timeout: float) -> Completion: ...


class GroqProvider:
    def __init__(self, key: str, model: str = "openai/gpt-oss-20b") -> None:
        self.client = Groq(api_key=key, max_retries=0)
        self.model = model
        self.identity = f"groq:{model}"

    def complete(self, prompt: str, output_tokens: int, timeout: float) -> Completion:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                reasoning_effort="low",
                include_reasoning=False,
                max_completion_tokens=output_tokens,
                response_format={"type": "json_object"},
                timeout=timeout,
            )
        except APIConnectionError as exc:
            raise RetryableProviderError from exc
        except APIStatusError as exc:
            if exc.status_code == 429 or exc.status_code >= 500:
                try:
                    delay = max(0, float(exc.response.headers.get("retry-after", "0")))
                except ValueError:
                    delay = 0
                raise RetryableProviderError(delay) from exc
            raise ProviderUnavailable("provider_rejected_request") from exc
        if not response.choices or response.usage is None:
            raise ProviderUnavailable("missing_provider_result")
        return Completion(
            content=response.choices[0].message.content or "", tokens=response.usage.total_tokens
        )


class ResponseCache:
    def __init__(self, path: Path, max_entries: int = 2000) -> None:
        self.path = path
        self.max_entries = max_entries
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS responses (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, created INTEGER NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=3)

    def get(self, key: str) -> Completion | None:
        with closing(self._connect()) as db, db:
            row = db.execute("SELECT value FROM responses WHERE key = ?", (key,)).fetchone()
        return Completion.model_validate_json(row[0]) if row else None

    def put(self, key: str, value: Completion) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO responses VALUES (?, ?, unixepoch())",
                (key, value.model_dump_json()),
            )
            db.execute(
                """
                DELETE FROM responses WHERE key IN (
                    SELECT key FROM responses ORDER BY created DESC, rowid DESC LIMIT -1 OFFSET ?
                )
            """,
                (self.max_entries,),
            )


class ModelGateway:
    def __init__(
        self, provider: Provider, cache: ResponseCache, *, cache_only: bool = False
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.cache_only = cache_only

    def complete(
        self,
        prompt: str,
        *,
        deadline: float,
        reserve: Callable[[int], None],
        reconcile: Callable[[int, int], None],
    ) -> str:
        output = 750
        # One token per UTF-8 byte is a conservative text bound. Leave room for message framing.
        reservation = len(prompt.encode()) + 256 + output
        key = hashlib.sha256(
            json.dumps([self.provider.identity, output, prompt], ensure_ascii=False).encode()
        ).hexdigest()
        if (cached := self.cache.get(key)) is not None:
            return cached.content
        if self.cache_only:
            raise ProviderUnavailable("response_cache_miss")
        for attempt in range(2):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ProviderUnavailable("deadline_exhausted")
            reserve(reservation)
            try:
                result = self.provider.complete(prompt, output, min(remaining, 15))
            except RetryableProviderError as exc:
                delay = max(exc.retry_after, 0.5 + random.uniform(0, 0.25))
                if attempt or delay >= deadline - monotonic():
                    raise ProviderUnavailable("provider_retry_exhausted") from exc
                sleep(delay)
                continue
            reconcile(reservation, result.tokens)
            if result.tokens > reservation:
                raise ProviderUnavailable("provider_usage_exceeded_reservation")
            self.cache.put(key, result)
            return result.content
        raise AssertionError("retry loop exhausted")
