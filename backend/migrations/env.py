from alembic import context
from sqlalchemy import create_engine, pool

from inquest.settings import Settings

if context.is_offline_mode():
    context.configure(url=Settings().migration_database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(Settings().migration_database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
