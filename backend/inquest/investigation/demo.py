"""Provision a local synthetic case and a short-lived analyst session."""

import argparse
import json
import secrets
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import create_engine, text

from inquest.investigation.contracts import Contract
from inquest.settings import Settings


class DemoSession(Contract):
    case_id: str
    workspace_id: str
    analyst_id: str
    token: str


def provision(sequence: int) -> DemoSession:
    # Use the migration role only in this local provisioning command.
    from inquest.scoring.model import Scorer
    from inquest.scoring.repository import transaction_features

    settings = Settings()
    scorer = Scorer(settings.scorer_directory)
    engine = create_engine(settings.migration_database_url)
    session = DemoSession(
        case_id=str(uuid4()),
        workspace_id=str(uuid4()),
        analyst_id=str(uuid4()),
        token=secrets.token_urlsafe(32),
    )
    params = {
        "case": session.case_id,
        "workspace": session.workspace_id,
        "analyst": session.analyst_id,
        "hash": sha256(session.token.encode()).hexdigest(),
        "dataset": scorer.manifest.serving_dataset_id,
        "replay": str(uuid4()),
        "sequence": sequence,
    }
    try:
        with engine.begin() as connection:
            features = transaction_features(
                connection,
                scorer.manifest.serving_dataset_id,
                sequence,
                currency=scorer.manifest.currency,
            )
            if features is None:
                raise ValueError("transaction is unavailable in the default fixture")
            score = scorer.predict(features)
            for statement in (
                "INSERT INTO operations.workspaces VALUES (:workspace)",
                "INSERT INTO operations.analysts "
                "VALUES (:analyst, 'demo-' || CAST(:analyst AS uuid)::text)",
                "INSERT INTO operations.workspace_memberships VALUES (:workspace, :analyst)",
                """INSERT INTO operations.analyst_sessions VALUES (
                    :hash, :workspace, :analyst, now() + interval '1 hour'
                )""",
                """INSERT INTO operations.replay_runs (id, dataset_id, cursor)
                   VALUES (:replay, :dataset, :sequence)""",
            ):
                connection.execute(text(statement), params)
            values = params | {
                "score": score.fraud_probability,
                "threshold": score.threshold,
                "model": score.model_version,
                "feature": score.feature_version,
                "contributions": json.dumps(
                    [item.model_dump(mode="json") for item in score.top_contributions]
                ),
            }
            connection.execute(
                text("""
                INSERT INTO operations.transaction_scores VALUES (
                    :replay, :dataset, :sequence, :model, :feature,
                    :score, :threshold, CAST(:contributions AS jsonb)
                )
            """),
                values,
            )
            connection.execute(
                text("""
                INSERT INTO operations.cases
                    (workspace_id, id, replay_id, dataset_id, source_sequence, model_version)
                VALUES (:workspace, :case, :replay, :dataset, :sequence, :model)
            """),
                values,
            )
    finally:
        engine.dispose()
    return session


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", type=int, default=150)
    args = parser.parse_args()
    print(provision(args.sequence).model_dump_json())
