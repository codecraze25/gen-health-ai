import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"
os.environ["OPENAI_API_KEY"] = ""

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(client: TestClient):
    """Registers a user and returns Authorization headers for them."""

    def _make(email: str = "alice@example.com", password: str = "s3cret-pass") -> dict[str, str]:
        resp = client.post("/auth/register", json={"email": email, "password": password})
        assert resp.status_code == 201, resp.text
        resp = client.post("/auth/login", data={"username": email, "password": password})
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _make


@pytest.fixture
def auth(make_user) -> dict[str, str]:
    return make_user()
