"""SQLAlchemy engine, session, and base model configuration."""

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


def _enforce_sqlite_fk_pragma(dbapi_connection: object, connection_record: object) -> None:
    """Enable SQLite foreign key enforcement on every new connection."""
    cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _create_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine with SQLite FK pragma support."""
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(database_url, connect_args=connect_args)

    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _enforce_sqlite_fk_pragma)

    return engine


settings = get_settings()
engine = _create_engine(settings.DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""

    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def verify_fk_pragma(conn: Connection) -> bool:
    """Return True if foreign_keys pragma is enabled on the given connection."""
    result = conn.execute(text("PRAGMA foreign_keys"))
    row = result.fetchone()
    return row is not None and row[0] == 1
