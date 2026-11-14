from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection, connect
from psycopg.rows import DictRow, dict_row
from sqlalchemy.engine import make_url

from inquest.settings import Settings


@contextmanager
def checkpoint_connection(url: str) -> Iterator[Connection[DictRow]]:
    dsn = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    with connect(
        dsn,
        autocommit=True,
        row_factory=dict_row,
        prepare_threshold=None,
        options="-c search_path=agent_checkpoints -c statement_timeout=5000",
        connect_timeout=3,
    ) as connection:
        yield connection


def setup() -> None:
    with checkpoint_connection(Settings().migration_database_url) as connection:
        PostgresSaver(connection).setup()
        connection.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA agent_checkpoints "
            "TO inquest_api"
        )


if __name__ == "__main__":
    setup()
