"""Alembic environment configuration."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Alembic Config object — access to alembic.ini values.
config = context.config

# Set up Python logging from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import app config and Base so autogenerate can detect model changes.
import app.models  # noqa: E402, F401 — registers all ORM models into Base.metadata
from app.config import get_settings  # noqa: E402
from app.database import Base  # noqa: E402

# Override sqlalchemy.url with the value from app settings.
_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.DATABASE_URL)

target_metadata = Base.metadata


def _enforce_sqlite_fk_pragma(dbapi_connection: object, connection_record: object) -> None:
    """Enable SQLite foreign key enforcement for Alembic connections."""
    cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a live DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (applies changes to a live DB connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    from sqlalchemy import event

    event.listen(connectable, "connect", _enforce_sqlite_fk_pragma)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
