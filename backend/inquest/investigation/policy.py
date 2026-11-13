import json
import re
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from math import log1p
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from inquest.investigation.contracts import Contract, Evidence

MAX_POLICY_MATCHES = 3
MAX_QUERY_LENGTH = 240
MAX_EXCERPT_LENGTH = 800
MAX_POLICY_FILES = 32
MAX_POLICY_FILE_BYTES = 8192
MAX_SECTIONS = 128
RANKER_VERSION = "bm25-v1"

TOKEN = re.compile(r"[a-z0-9]+")
HEADING = re.compile(r"^## ([^\n]+)\n", re.MULTILINE)
HEADER = re.compile(r"^# (P\d{2}) · ([^\n]+)\n\nVersion ([1-9]\d*)\n")
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from had has have how i if in is it "
    "of on or our should so than that the their this to was we were what when where "
    "which who will with would you your please policy guidance explain".split()
)
ALIASES = {
    "card probing": "card testing",
    "improbable journey": "impossible travel",
    "money mule": "mule cash out",
    "handset replacement": "new device",
    "sim swap": "sim re registration",
    "payment request": "collect request",
    "rapid retries": "velocity burst",
    "shared terminal": "device sharing",
}
K1 = 1.2
B = 0.75
MIN_SCORE = 1.0


class PolicySearchRequest(Contract):
    tool: Literal["search_policy_docs"] = "search_policy_docs"
    query: Annotated[str, Field(strict=True, min_length=1, max_length=MAX_QUERY_LENGTH)]


class PolicyExcerpt(Contract):
    policy_id: str
    section_id: str
    title: str
    section: str
    version: int
    content_sha256: str
    excerpt: Annotated[str, Field(min_length=1, max_length=MAX_EXCERPT_LENGTH)]


class PolicyObservation(Contract):
    tool: Literal["search_policy_docs"] = "search_policy_docs"
    outcome: Literal["matched", "no_match"]
    corpus_sha256: str
    ranker_version: str = RANKER_VERSION
    matches: Annotated[tuple[PolicyExcerpt, ...], Field(max_length=MAX_POLICY_MATCHES)]


class PolicyEvidence(Evidence):
    status: Literal["ok"] = "ok"
    observation: PolicyObservation


def _tokens(value: str) -> list[str]:
    return [token for token in TOKEN.findall(value.casefold()) if token not in STOPWORDS]


@dataclass(frozen=True)
class IndexedSection:
    evidence: PolicyExcerpt
    terms: Counter[str]

    @property
    def length(self) -> int:
        return self.terms.total()


def _load_file(path: Path) -> list[PolicyExcerpt]:
    with path.open("rb") as source:
        content = source.read(MAX_POLICY_FILE_BYTES + 1)
    if len(content) > MAX_POLICY_FILE_BYTES:
        raise ValueError(f"policy exceeds size limit: {path.name}")
    body = content.decode("utf-8").replace("\r\n", "\n")
    header = HEADER.match(body)
    headings = list(HEADING.finditer(body))
    if not header or not headings:
        raise ValueError(f"invalid policy header or sections: {path.name}")
    policy_id, title, version = header.groups()
    if policy_id != path.name.partition("-")[0]:
        raise ValueError(f"policy ID must match filename: {path.name}")
    excerpts = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        section = heading[1]
        slug = "-".join(TOKEN.findall(section.casefold()))
        if not slug:
            raise ValueError(f"empty section ID: {path.name}")
        excerpt = body[heading.end() : end].strip()
        digest = sha256(f"{policy_id}\n{version}\n{title}\n{section}\n{excerpt}".encode())
        excerpts.append(
            PolicyExcerpt(
                policy_id=policy_id,
                section_id=f"{policy_id}/{slug}",
                title=title,
                section=section,
                version=int(version),
                content_sha256=digest.hexdigest(),
                excerpt=excerpt,
            )
        )
    return excerpts


class PolicyIndex:
    def __init__(self, directory: Path) -> None:
        paths = sorted(directory.glob("P[0-9][0-9]-*.md"))
        if not 1 <= len(paths) <= MAX_POLICY_FILES:
            raise ValueError("policy corpus file count is out of bounds")
        if len({path.name.partition("-")[0] for path in paths}) != len(paths):
            raise ValueError("duplicate policy ID")
        excerpts = sorted(
            (excerpt for path in paths for excerpt in _load_file(path)),
            key=lambda item: item.section_id,
        )
        if len(excerpts) > MAX_SECTIONS:
            raise ValueError("policy corpus section count is out of bounds")
        if len({excerpt.section_id for excerpt in excerpts}) != len(excerpts):
            raise ValueError("duplicate policy section ID")
        self._sections = tuple(
            IndexedSection(item, Counter(_tokens(f"{item.title} {item.section} {item.excerpt}")))
            for item in excerpts
        )
        self._average_length = sum(section.length for section in self._sections) / len(excerpts)
        frequency = Counter(token for section in self._sections for token in section.terms)
        self._idf = {
            token: log1p((len(excerpts) - count + 0.5) / (count + 0.5))
            for token, count in frequency.items()
        }
        manifest = {
            "ranker": RANKER_VERSION,
            "aliases": ALIASES,
            "stopwords": sorted(STOPWORDS),
            "k1": K1,
            "b": B,
            "minimum_score": MIN_SCORE,
            "maximum_matches": MAX_POLICY_MATCHES,
            "sections": [item.content_sha256 for item in excerpts],
        }
        self.corpus_sha256 = sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()

    def search(self, request: PolicySearchRequest) -> PolicyObservation:
        query = " ".join(TOKEN.findall(request.query.casefold()))
        expanded = " ".join(
            equivalent for phrase, equivalent in ALIASES.items() if f" {phrase} " in f" {query} "
        )
        terms = sorted(set(_tokens(f"{query} {expanded}")) & self._idf.keys())
        ranked = []
        for section in self._sections:
            norm = K1 * (1 - B + B * section.length / self._average_length)
            score = sum(
                self._idf[term] * count * (K1 + 1) / (count + norm)
                for term in terms
                if (count := section.terms[term])
            )
            if score >= MIN_SCORE:
                ranked.append((score, section.evidence))
        ranked.sort(key=lambda item: (-item[0], item[1].section_id))
        matches = tuple(item for _, item in ranked[:MAX_POLICY_MATCHES])
        return PolicyObservation(
            outcome="matched" if matches else "no_match",
            corpus_sha256=self.corpus_sha256,
            matches=matches,
        )
