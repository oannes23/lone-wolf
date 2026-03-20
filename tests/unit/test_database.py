"""Tests for app/database.py — engine setup, FK pragma, and session management."""

import contextlib

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.database import Base, _enforce_sqlite_fk_pragma, engine, get_db, verify_fk_pragma


class TestFKPragma:
    def test_pragma_enabled_on_engine_connections(self) -> None:
        """SQLite FK pragma must be ON for every connection from the module-level engine."""
        with engine.connect() as conn:
            assert verify_fk_pragma(conn) is True

    def test_pragma_enabled_on_fresh_in_memory_engine(self) -> None:
        """FK pragma helper correctly identifies an engine with pragma enabled."""
        mem_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        event.listen(mem_engine, "connect", _enforce_sqlite_fk_pragma)
        with mem_engine.connect() as conn:
            assert verify_fk_pragma(conn) is True

    def test_pragma_off_without_listener(self) -> None:
        """Without the FK listener, SQLite FK enforcement is OFF by default."""
        mem_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        with mem_engine.connect() as conn:
            assert verify_fk_pragma(conn) is False

    def test_fk_violation_raises_with_pragma_on(self) -> None:
        """A FK violation should raise an IntegrityError when foreign_keys pragma is ON."""
        mem_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        event.listen(mem_engine, "connect", _enforce_sqlite_fk_pragma)

        class _FKBase(DeclarativeBase):
            pass

        class _Parent(_FKBase):
            __tablename__ = "fk_test_parent"
            id = Column(Integer, primary_key=True)
            name = Column(String(50))

        class _Child(_FKBase):
            __tablename__ = "fk_test_child"
            id = Column(Integer, primary_key=True)
            parent_id = Column(Integer, ForeignKey("fk_test_parent.id"), nullable=False)

        _FKBase.metadata.create_all(mem_engine)

        MSession = sessionmaker(bind=mem_engine)
        # Insert a child referencing a non-existent parent — must raise at execute time
        with MSession() as session, pytest.raises(IntegrityError):
            session.execute(text("INSERT INTO fk_test_child (id, parent_id) VALUES (1, 9999)"))

    def test_fk_no_violation_with_valid_reference(self) -> None:
        """A valid FK reference should insert successfully when pragma is ON."""
        mem_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        event.listen(mem_engine, "connect", _enforce_sqlite_fk_pragma)

        class _FKBase2(DeclarativeBase):
            pass

        class _Parent2(_FKBase2):
            __tablename__ = "fk2_parent"
            id = Column(Integer, primary_key=True)
            name = Column(String(50))

        class _Child2(_FKBase2):
            __tablename__ = "fk2_child"
            id = Column(Integer, primary_key=True)
            parent_id = Column(Integer, ForeignKey("fk2_parent.id"), nullable=False)

        _FKBase2.metadata.create_all(mem_engine)

        MSession = sessionmaker(bind=mem_engine)
        with MSession() as session:
            session.execute(text("INSERT INTO fk2_parent (id, name) VALUES (1, 'Alice')"))
            session.execute(text("INSERT INTO fk2_child (id, parent_id) VALUES (1, 1)"))
            session.commit()  # Should not raise


class TestBase:
    def test_base_is_declarative_base(self) -> None:
        """Base must be a DeclarativeBase subclass."""
        assert issubclass(Base, DeclarativeBase)

    def test_base_metadata_exists(self) -> None:
        assert isinstance(Base.metadata, MetaData)


class TestGetDb:
    def test_get_db_yields_session(self) -> None:
        """get_db dependency must yield a SQLAlchemy Session."""
        gen = get_db()
        session = next(gen)
        assert isinstance(session, Session)
        with contextlib.suppress(StopIteration):
            next(gen)

    def test_get_db_closes_session_after_yield(self) -> None:
        """get_db must close the session (releasing its connection) after teardown."""
        gen = get_db()
        session = next(gen)
        # Trigger an implicit transaction by executing a statement
        session.execute(text("SELECT 1"))
        assert session.in_transaction()
        # Close the generator (simulates FastAPI dependency teardown)
        gen.close()
        # After close(), the session must have released its connection/transaction
        assert not session.in_transaction()
