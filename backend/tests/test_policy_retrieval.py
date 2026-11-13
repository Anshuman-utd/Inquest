from pathlib import Path
from typing import Annotated

import pytest
from pydantic import Field, TypeAdapter, ValidationError

from inquest.investigation.contracts import Contract
from inquest.investigation.policy import MAX_POLICY_MATCHES, PolicyIndex, PolicySearchRequest
from inquest.investigation.tools import TOOL_REQUESTS

POLICIES = Path("policies")


class QueryExample(Contract):
    query: str
    relevant_policy: Annotated[str, Field(pattern=r"^P[0-9]{2}$")] | None


def test_policy_retrieval_benchmark() -> None:
    queries = TypeAdapter(list[QueryExample]).validate_json(
        Path("fixtures/policy_queries.json").read_text()
    )
    index = PolicyIndex(POLICIES)
    top_three = top_one = relevant_queries = negatives = 0
    for item in queries:
        observation = index.search(PolicySearchRequest(query=item.query))
        hits = [excerpt.policy_id for excerpt in observation.matches]
        assert len(hits) <= MAX_POLICY_MATCHES
        if item.relevant_policy is None:
            negatives += 1
            assert observation.outcome == "no_match" and not hits, item.query
        else:
            relevant_queries += 1
            top_one += int(bool(hits) and hits[0] == item.relevant_policy)
            top_three += int(item.relevant_policy in hits)
    assert (relevant_queries, negatives) == (16, 2)
    assert top_one >= 13 and top_three >= 14


def test_retrieval_is_deterministic_and_cites_versioned_sections() -> None:
    query = PolicySearchRequest(query="SIM-swap")
    index = PolicyIndex(POLICIES)
    first = index.search(query)
    assert first == PolicyIndex(POLICIES).search(query)
    assert first.corpus_sha256 == index.corpus_sha256
    match = first.matches[0]
    assert match.section_id == "P03/sim-re-registration" and match.version == 1
    assert len(match.content_sha256) == 64
    assert "re-registration" in match.excerpt


def test_ties_and_content_changes_are_stable(tmp_path: Path) -> None:
    document = "# P01 · Wallet tracing\n\nVersion 1\n\n## A\n\nWallet evidence.\n"
    first = tmp_path / "P01-first.md"
    second = tmp_path / "P02-second.md"
    second.write_text(document.replace("P01", "P02"))
    first.write_text(document)
    (tmp_path / "P03-other.md").write_text(
        "# P03 · Travel history\n\nVersion 1\n\n## B\n\nReview city observations.\n"
    )
    (tmp_path / "P04-other.md").write_text(
        "# P04 · Account history\n\nVersion 1\n\n## C\n\nCheck previous amounts.\n"
    )
    query = PolicySearchRequest(query="wallet tracing")
    original = PolicyIndex(tmp_path).search(query)
    assert [match.section_id for match in original.matches] == ["P01/a", "P02/a"]
    first.write_text(document.replace("Version 1", "Version 2").replace("evidence", "context"))
    updated = PolicyIndex(tmp_path).search(query)
    assert updated.corpus_sha256 != original.corpus_sha256
    updated_first = next(match for match in updated.matches if match.policy_id == "P01")
    assert updated_first.version == 2
    assert updated_first.content_sha256 != original.matches[0].content_sha256


def test_duplicate_policy_sections_fail_fast(tmp_path: Path) -> None:
    (tmp_path / "P01-test.md").write_text(
        "# P01 · Wallet tracing\n\nVersion 1\n\n## Same\n\nFirst.\n\n## Same\n\nSecond.\n"
    )
    with pytest.raises(ValueError, match="duplicate policy section ID"):
        PolicyIndex(tmp_path)


@pytest.mark.parametrize("query", ["", "x" * 241, 42])
def test_search_query_is_bounded(query: object) -> None:
    with pytest.raises(ValidationError):
        TOOL_REQUESTS.validate_python({"tool": "search_policy_docs", "query": query})
