"""Global pytest configuration — in-memory SQLite engine, session fixtures, and TestClient."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

# Import models so Base.metadata is populated before create_all
import app.models
from app.database import Base, _enforce_sqlite_fk_pragma, get_db
from app.main import app


@pytest.fixture(scope="session")
def engine():
    """Create an in-memory SQLite engine for the entire test session."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    event.listen(test_engine, "connect", _enforce_sqlite_fk_pragma)
    Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def db(engine):
    """Each test gets a connection with a transaction that is rolled back after."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    # Use a savepoint so that nested transactions work correctly inside tests
    session.begin_nested()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    """TestClient with the database dependency overridden to use the test session."""

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
