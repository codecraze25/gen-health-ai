def test_register_login_me(client, auth):
    resp = client.get("/auth/me", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert "hashed_password" not in body


def test_duplicate_email_is_rejected_case_insensitively(client, auth):
    resp = client.post(
        "/auth/register", json={"email": "ALICE@example.com", "password": "another-pass"}
    )
    assert resp.status_code == 409


def test_wrong_password_and_unknown_user_get_same_error(client, auth):
    wrong = client.post("/auth/login", data={"username": "alice@example.com", "password": "nope"})
    unknown = client.post("/auth/login", data={"username": "bob@example.com", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_short_password_rejected(client):
    resp = client.post("/auth/register", json={"email": "c@example.com", "password": "short"})
    assert resp.status_code == 422


def test_protected_routes_require_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/orders").status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert client.get("/orders", headers=bad).status_code == 401
