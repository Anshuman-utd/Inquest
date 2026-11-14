import argparse
import json
import subprocess
from collections import deque
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, text

from inquest.db.tenant import TenantDatabase
from inquest.evaluation.agent_cohort import CohortManifest, Sample
from inquest.evaluation.evidence_plan import next_evidence, synthesize_evidence
from inquest.investigation.contracts import ToolScope
from inquest.investigation.demo import provision
from inquest.investigation.graph import EVIDENCE, State, Steps, build_graph
from inquest.investigation.policy import PolicyIndex
from inquest.investigation.provider import Completion, GroqProvider, ModelGateway, ResponseCache
from inquest.investigation.replay import Recordings
from inquest.investigation.reports import Draft, Report, verify
from inquest.investigation.tools import InvestigationTools
from inquest.settings import Settings

Arm = Literal["ml_only", "full", "no_tools", "no_policy", "no_self_check"]
ARMS: tuple[Arm, ...] = ("ml_only", "full", "no_tools", "no_policy", "no_self_check")
ROOT = Path("backend/inquest/investigation")
NAMESPACE = UUID("cd659c5f-ad11-43f7-98df-f2a141beeddb")


class PacedGroq(GroqProvider):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.window: deque[tuple[float, int]] = deque()

    def wait_for_capacity(self) -> None:
        # Wait between cases so provider pacing does not eat the investigation time budget.
        while True:
            now = monotonic()
            while self.window and now - self.window[0][0] >= 60:
                self.window.popleft()
            if sum(item[1] for item in self.window) <= 4400 and len(self.window) <= 22:
                return
            sleep(max(0.05, min(2.0, 60 - (now - self.window[0][0]))))

    def complete(self, prompt: str, output_tokens: int, timeout: float) -> Completion:
        index = len(self.window)
        self.window.append((monotonic(), 800))
        result = super().complete(prompt, output_tokens, timeout)
        self.window[index] = (self.window[index][0], result.tokens)
        return result


@dataclass
class Usage:
    requests: int = 0
    retries: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class EvaluationSteps(Steps):
    def __init__(self, base: Steps, arm: Arm, revision: str) -> None:
        super().__init__(base.tenants, base.tools, base.gateway, base.daily_tokens, base.recordings)
        self.arm = arm
        self.revision = revision
        self.policy_enabled = arm != "no_policy"
        self.usage = Usage()

    def model(self, state: State, instructions: str, *, reserve_report: bool = False) -> str:
        # Session-specific IDs do not affect the model input or the response-cache key.
        # Restore the current run's evidence IDs before verification and persistence.
        ids = {
            item["evidence_id"]: str(uuid5(NAMESPACE, str(item["call_sequence"])))
            for item in state.get("observations", [])
        }
        canonical = [
            {**item, "evidence_id": ids[item["evidence_id"]]}
            for item in state.get("observations", [])
        ]
        result = super().model(
            {**state, "observations": canonical},
            instructions,
            reserve_report=reserve_report,
        )
        for actual, alias in ids.items():
            result = result.replace(alias, actual)
        return result

    def observe_model(
        self,
        kind: Literal["request", "retry", "cache", "response"],
        result: Completion | None,
    ) -> None:
        if kind == "request":
            self.usage.requests += 1
        elif kind == "retry":
            self.usage.retries += 1
        elif kind == "cache":
            self.usage.cache_hits += 1
        elif result is not None:
            self.usage.input_tokens += result.input_tokens or 0
            self.usage.output_tokens += result.output_tokens or 0

    def triage(self, state: State) -> State:
        initial = super().triage(state)
        if self.arm == "no_tools":
            # Supply the focal transaction as immutable input, without running the tool loop.
            scope = ToolScope.model_validate(state["scope"])
            focal = self.tools.execute(scope, 1, {"tool": "get_transaction"})
            return {**initial, "observations": [focal.model_dump(mode="json")], "request": None}
        return initial

    def plan(self, state: State) -> State:
        if self.arm == "no_tools":
            return {"request": None}
        if self.revision == "focused":
            return next_evidence(state, policy=self.policy_enabled)
        return super().plan(state)

    def synthesize(self, state: State) -> State:
        if self.revision == "focused":
            return synthesize_evidence(self, state)
        return super().synthesize(state)

    def check(self, state: State) -> State:
        if self.arm == "no_self_check" and state.get("draft"):
            try:
                draft = Draft.model_validate_json(state["draft"])
            except ValueError:
                return super().check(state)
            return {
                "report": Report(**draft.model_dump(), status="verified").model_dump(mode="json"),
                "error": "",
            }
        return super().check(state)


def graph_digest() -> str:
    digest = sha256()
    for name in ("graph.py", "reports.py", "provider.py", "tools.py", "policy.py", "repository.py"):
        digest.update((ROOT / name).read_bytes())
    digest.update(Path(__file__).read_bytes())
    digest.update(Path("backend/inquest/evaluation/evidence_plan.py").read_bytes())
    return digest.hexdigest()


def evaluate(
    steps: EvaluationSteps,
    manifest: CohortManifest,
    sample: Sample,
) -> dict[str, Any]:
    if steps.arm == "ml_only":
        return {
            "action": "escalate",
            "grounded": None,
            "failure": None,
            "tool_calls": 0,
            **asdict(Usage()),
        }
    demo = provision(sample.sequence, dataset_id=manifest.dataset_id)
    scope = ToolScope(
        workspace_id=UUID(demo.workspace_id),
        analyst_id=UUID(demo.analyst_id),
        investigation_id=uuid4(),
    )
    with steps.transaction(scope) as db:
        serving_score = db.execute(
            text("""
            SELECT s.score FROM operations.cases c JOIN operations.transaction_scores s
                USING (replay_id, dataset_id, source_sequence, model_version)
            WHERE c.id = :case
        """),
            {"case": UUID(demo.case_id)},
        ).scalar_one()
        if abs(serving_score - sample.score) > 1e-12:
            raise ValueError("evaluation and serving scores differ")
        db.execute(
            text("""
            INSERT INTO operations.investigations
                (workspace_id, id, case_id, status, mode, started_at)
            VALUES (:workspace, :id, :case, 'running', 'live', now())
        """),
            {
                "workspace": scope.workspace_id,
                "id": scope.investigation_id,
                "case": UUID(demo.case_id),
            },
        )
    steps.usage = Usage()
    graph = build_graph(steps, InMemorySaver())
    start = monotonic()
    config = {"configurable": {"thread_id": str(scope.investigation_id)}, "recursion_limit": 32}
    state = graph.invoke({"scope": scope.model_dump(mode="json")}, config)
    duration = monotonic() - start
    if not graph.get_state(config).interrupts:
        raise ValueError("evaluation graph failed to reach approval")
    report = Report.model_validate(state["report"])
    evidence = [EVIDENCE.validate_python(item) for item in state.get("observations", [])]
    grounded = False
    if report.status == "verified":
        try:
            verify(Draft.model_validate(report.model_dump(exclude={"status", "reason"})), evidence)
            grounded = True
        except ValueError:
            pass
    with steps.transaction(scope) as db:
        accounted_tokens = db.execute(
            text("""
            UPDATE operations.investigations SET status = 'review' WHERE id = :id
            RETURNING used_tokens
        """),
            {"id": scope.investigation_id},
        ).scalar_one()
    return {
        "action": report.recommended_action,
        "grounded": grounded,
        "failure": report.reason,
        "fallback_reason": state.get("fallback_reason"),
        "repairs": state.get("repairs", 0),
        "tool_calls": len(evidence) if steps.arm != "no_tools" else 0,
        "policy_calls": sum(
            item.status == "ok" and item.observation.tool == "search_policy_docs"
            for item in evidence
        ),
        "latency_seconds": duration,
        "report": report.model_dump(mode="json"),
        "investigation_id": str(scope.investigation_id),
        "accounted_tokens": accounted_tokens,
        **asdict(steps.usage),
    }


def run(
    settings: Settings,
    manifest: CohortManifest,
    arms: list[Arm],
    output: Path,
    revision: str,
    *,
    cache_only: bool,
) -> dict[str, Any]:
    if not settings.groq_api_key and any(arm != "ml_only" for arm in arms):
        raise ValueError("INQUEST_GROQ_API_KEY is required for live evaluation")
    key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else "unused"
    provider = PacedGroq(key)
    api = create_engine(settings.database_url)
    reader = create_engine(settings.tool_database_url)
    evaluator = create_engine(settings.evaluation_database_url)
    owner = create_engine(settings.migration_database_url)
    index = PolicyIndex(settings.policy_directory)
    tenants = TenantDatabase(api)
    gateway = ModelGateway(
        provider, ResponseCache(output / "responses.sqlite"), cache_only=cache_only
    )
    base = Steps(
        tenants,
        InvestigationTools(tenants, reader, index),
        gateway,
        settings.global_daily_tokens,
        Recordings(settings.recordings_file),
    )
    run_ids: dict[Arm, UUID] = {}
    steps = {arm: EvaluationSteps(base, arm, revision) for arm in arms}
    with evaluator.begin() as db:
        for arm in arms:
            config = {
                "arm": arm,
                "revision": revision,
                "cohort": manifest.model_dump(mode="json"),
                "provider": provider.identity,
                "git": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"],
                    text=True,
                ).strip(),
                "graph_sha256": graph_digest(),
                "policy_sha256": index.corpus_sha256,
                "cache_only": cache_only,
                "global_daily_tokens": settings.global_daily_tokens,
            }
            identity = json.dumps(
                {key: value for key, value in config.items() if key != "git"}, sort_keys=True
            )
            run_ids[arm] = uuid5(NAMESPACE, identity)
            db.execute(
                text("""
                INSERT INTO evaluation.eval_runs (id, dataset_id, configuration)
                VALUES (:run, :dataset, CAST(:config AS jsonb)) ON CONFLICT (id) DO NOTHING
            """),
                {"run": run_ids[arm], "dataset": manifest.dataset_id, "config": json.dumps(config)},
            )
    with owner.begin() as db:
        previous = db.execute(
            text("""
            SELECT llm_enabled FROM operations.runtime_controls WHERE singleton FOR UPDATE
        """)
        ).scalar_one()
        if any(arm != "ml_only" for arm in arms) and not cache_only:
            db.execute(text("UPDATE operations.runtime_controls SET llm_enabled = true"))
    rows: dict[Arm, list[dict[str, Any]]] = {arm: [] for arm in arms}
    try:
        for sample in manifest.samples:
            for arm in arms:
                params = {
                    "run": run_ids[arm],
                    "dataset": manifest.dataset_id,
                    "seq": sample.sequence,
                }
                with evaluator.connect() as db:
                    stored = db.execute(
                        text("""
                        SELECT result FROM evaluation.eval_case_results
                        WHERE eval_run_id = :run AND source_sequence = :seq
                    """),
                        params,
                    ).scalar_one_or_none()
                    label = (
                        db.execute(
                            text("""
                        SELECT is_fraud, scenario, episode_id FROM evaluation.truth
                        WHERE dataset_id = :dataset AND source_sequence = :seq
                    """),
                            params,
                        )
                        .mappings()
                        .one()
                    )
                if stored is None:
                    if arm != "ml_only" and not cache_only:
                        provider.wait_for_capacity()
                    result = evaluate(steps[arm], manifest, sample)
                    stored = {
                        **sample.model_dump(),
                        **dict(label),
                        "weight": sample.weight,
                        **result,
                    }
                    with evaluator.begin() as db:
                        db.execute(
                            text("""
                            INSERT INTO evaluation.eval_case_results
                                (eval_run_id, dataset_id, source_sequence, result)
                            VALUES (:run, :dataset, :seq, CAST(:result AS jsonb))
                        """),
                            params | {"result": json.dumps(stored)},
                        )
                    print(
                        f"{manifest.name} {sample.sequence} {arm} {stored['action']} "
                        f"{stored.get('failure') or ''}",
                        flush=True,
                    )
                rows[arm].append(stored)
    finally:
        with owner.begin() as db:
            db.execute(
                text("UPDATE operations.runtime_controls SET llm_enabled = :enabled"),
                {"enabled": previous},
            )
        for engine in (api, reader, owner, evaluator):
            engine.dispose()
    return {
        "run_ids": {arm: str(run_id) for arm, run_id in run_ids.items()},
        "cohort": manifest.model_dump(mode="json"),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run paired held-out agent ablations")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=ARMS)
    parser.add_argument("--revision", choices=("initial", "focused"), default="initial")
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()
    manifest = CohortManifest.model_validate_json(args.manifest.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    result = run(
        Settings(),
        manifest,
        list(args.arms),
        args.output,
        args.revision,
        cache_only=args.cache_only,
    )
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
