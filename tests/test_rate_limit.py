import pytest

from app.core.config import get_settings
from app.core.rate_limit import ALL_LIMITERS


@pytest.fixture
def rate_limits_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    for limiter in ALL_LIMITERS:
        limiter.reset()
    yield
    for limiter in ALL_LIMITERS:
        limiter.reset()


def test_login_is_rate_limited_per_client(client, rate_limits_on):
    limit = get_settings().rate_limit_login_per_minute
    for _ in range(limit):
        resp = client.post("/auth/login", data={"username": "x@example.com", "password": "nope"})
        assert resp.status_code == 401
    resp = client.post("/auth/login", data={"username": "x@example.com", "password": "nope"})
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


def test_upload_is_rate_limited_per_user(client, make_user, rate_limits_on, monkeypatch):
    from app.api.deps import get_extractor
    from app.core import rate_limit
    from app.main import app

    app.dependency_overrides[get_extractor] = lambda: object()
    monkeypatch.setattr(rate_limit.upload_limiter, "limit", 1)
    alice, bob = make_user("alice@example.com"), make_user("bob@example.com")
    not_pdf = {"file": ("a.txt", b"not a pdf", "text/plain")}

    assert client.post("/orders/upload", headers=alice, files=not_pdf).status_code == 415
    assert client.post("/orders/upload", headers=alice, files=not_pdf).status_code == 429
    # Limits are per user, so another account is unaffected.
    assert client.post("/orders/upload", headers=bob, files=not_pdf).status_code == 415
