from pathlib import Path
from time import monotonic

import pytest

from inquest.investigation.provider import (
    Completion,
    ModelGateway,
    ProviderUnavailable,
    ResponseCache,
    RetryableProviderError,
)


class FakeProvider:
    identity = "test:model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str, output_tokens: int, timeout: float) -> Completion:
        self.calls += 1
        if self.calls == 1:
            raise RetryableProviderError(0.8)
        return Completion(content='{"ok":true}', tokens=15)


def test_retry_reserves_every_attempt_and_cache_survives_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr("inquest.investigation.provider.sleep", delays.append)
    provider = FakeProvider()
    path = tmp_path / "responses.sqlite"
    gateway = ModelGateway(provider, ResponseCache(path))
    reservations: list[int] = []
    charges: list[tuple[int, int]] = []

    def reconcile(reserved: int, used: int) -> None:
        charges.append((reserved, used))

    def complete(gateway: ModelGateway, prompt: str) -> str:
        return gateway.complete(
            prompt,
            deadline=monotonic() + 10,
            reserve=reservations.append,
            reconcile=reconcile,
        )

    assert complete(gateway, "prompt") == '{"ok":true}'
    assert delays == [0.8]
    assert len(reservations) == provider.calls == 2
    assert charges == [(reservations[1], 15)]
    replay = ModelGateway(provider, ResponseCache(path), cache_only=True)
    assert complete(replay, "prompt") == '{"ok":true}'
    assert provider.calls == 2
    with pytest.raises(ProviderUnavailable, match="response_cache_miss"):
        complete(replay, "new prompt")
