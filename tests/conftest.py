import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
# Every test registers at least one user, and bcrypt at the production cost
# factor made hashing the single largest line item in the suite's runtime.
os.environ.setdefault("BCRYPT_ROUNDS", "4")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.rate_limit import reset_rate_limits  # noqa: E402
from app.core.storage import LocalObjectStorage, get_storage  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

# Import models so their tables are registered on Base.metadata before create_all.
from app.models import membership, organization, user  # noqa: E402,F401

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    """Rate limit counters live in the process, so they leak between tests.

    Without this every test shares one budget and later tests start failing
    with 429s that have nothing to do with what they assert.
    """
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture()
def db() -> Session:
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def storage(tmp_path) -> LocalObjectStorage:
    """Attachment bytes land in a per-test directory, never the real root."""
    return LocalObjectStorage(str(tmp_path / "attachments"))


@pytest.fixture()
def client(db: Session, storage: LocalObjectStorage) -> TestClient:
    def _get_db_override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_storage] = lambda: storage
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_storage, None)
        storage.clear()
