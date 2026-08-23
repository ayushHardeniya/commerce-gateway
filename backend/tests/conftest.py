"""Shared test infrastructure: a real, ephemeral PostgreSQL instance.

Local development uses the docker-compose PostgreSQL instance (see
`docker-compose.yml` / `README.md`), but the automated test suite starts its
own throwaway PostgreSQL server (via `pgserver`) for the session instead of
pointing at that same instance. This keeps the suite exercising the real
database engine and the real Alembic migrations — rather than a different
database (e.g. SQLite) or a different schema-creation path — while staying
hermetic: no dependency on a Docker daemon being up, no shared state with a
developer's own dev database, and no port conflicts running tests and
`docker compose up -d` at the same time.
"""

from collections.abc import Iterator
from pathlib import Path

import pgserver
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from alembic import command
from app.db.session import get_db
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def postgres_uri(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    data_dir = tmp_path_factory.mktemp("pgdata")
    server = pgserver.get_server(str(data_dir))
    try:
        yield server.get_uri().replace("postgresql://", "postgresql+psycopg://")
    finally:
        server.cleanup()


@pytest.fixture(scope="session")
def db_engine(postgres_uri: str) -> Iterator[Engine]:
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_uri)
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(postgres_uri)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session bound to its own connection/transaction, rolled back after the test.

    Uses `join_transaction_mode="create_savepoint"` so that even if a test (or
    the code under test) calls `session.commit()`/`session.rollback()` — e.g.
    after asserting a constraint violation — it operates on a SAVEPOINT rather
    than ending the outer transaction, keeping the whole test isolated and
    reverted on teardown regardless.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """A TestClient whose FastAPI `get_db` dependency is the test's own session,
    so API calls and test setup see the same in-progress (uncommitted) data."""

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
