from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Connection, Engine, text


class WorkspaceAccessDenied(Exception):
    """The authenticated analyst is not a member of this workspace."""


class TenantDatabase:
    """Bind a verified membership for every transaction using the restricted API role."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self, *, workspace_id: UUID, analyst_id: UUID) -> Iterator[Connection]:
        with self._engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('inquest.workspace_id', :workspace, true)"),
                {"workspace": str(workspace_id)},
            )
            membership = connection.execute(
                text("""
                    SELECT 1
                    FROM operations.workspace_memberships
                    WHERE workspace_id = :workspace AND analyst_id = :analyst
                """),
                {"workspace": workspace_id, "analyst": analyst_id},
            ).scalar_one_or_none()
            if membership is None:
                raise WorkspaceAccessDenied
            yield connection
