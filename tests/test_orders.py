VALID_ORDER = {
    "patient_first_name": "Marie",
    "patient_last_name": "Curie",
    "patient_dob": "1950-12-05",
    "provider_name": "Arjun Raj",
    "provider_npi": "1234567893",
}


def test_create_complete_order_is_ready(client, auth):
    resp = client.post("/orders", json=VALID_ORDER, headers=auth)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["validation_issues"] == []
    assert body["provider_npi"] == "1234567893"


def test_partial_order_needs_review_until_completed(client, auth):
    partial = {k: v for k, v in VALID_ORDER.items() if k != "patient_dob"}
    order = client.post("/orders", json=partial, headers=auth).json()
    assert order["status"] == "needs_review"
    assert order["patient_dob"] is None

    resp = client.patch(f"/orders/{order['id']}", json={"patient_dob": "1950-12-05"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_get_list_update_delete(client, auth):
    order_id = client.post("/orders", json=VALID_ORDER, headers=auth).json()["id"]

    assert client.get(f"/orders/{order_id}", headers=auth).json()["id"] == order_id

    listing = client.get("/orders", headers=auth).json()
    assert listing["total"] == 1
    assert [o["id"] for o in listing["items"]] == [order_id]

    resp = client.patch(f"/orders/{order_id}", json={"notes": "Called office"}, headers=auth)
    assert resp.json()["notes"] == "Called office"
    assert resp.json()["patient_first_name"] == "Marie"

    assert client.delete(f"/orders/{order_id}", headers=auth).status_code == 204
    assert client.get(f"/orders/{order_id}", headers=auth).status_code == 404


def test_list_pagination_and_status_filter(client, auth):
    for _ in range(3):
        client.post("/orders", json=VALID_ORDER, headers=auth)
    client.post("/orders", json={"patient_first_name": "Ann"}, headers=auth)

    page = client.get("/orders?limit=2&offset=0", headers=auth).json()
    assert page["total"] == 4
    assert len(page["items"]) == 2

    review = client.get("/orders?status=needs_review", headers=auth).json()
    assert review["total"] == 1
    assert review["items"][0]["patient_first_name"] == "Ann"


def test_users_cannot_see_or_modify_each_others_orders(client, make_user):
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    order_id = client.post("/orders", json=VALID_ORDER, headers=alice).json()["id"]

    assert client.get("/orders", headers=bob).json()["total"] == 0
    assert client.get(f"/orders/{order_id}", headers=bob).status_code == 404
    assert client.patch(f"/orders/{order_id}", json={"notes": "x"}, headers=bob).status_code == 404
    assert client.delete(f"/orders/{order_id}", headers=bob).status_code == 404
    assert client.get(f"/orders/{order_id}", headers=alice).status_code == 200


def test_invalid_npi_rejected(client, auth):
    # The NPI printed on the sample fax; it fails the CMS check digit.
    resp = client.post("/orders", json={**VALID_ORDER, "provider_npi": "9182734556"}, headers=auth)
    assert resp.status_code == 422
    assert "check-digit" in resp.text

    resp = client.post("/orders", json={**VALID_ORDER, "provider_npi": "12345"}, headers=auth)
    assert resp.status_code == 422


def test_npi_formatting_is_normalized(client, auth):
    resp = client.post(
        "/orders", json={**VALID_ORDER, "provider_npi": "123-456 7893"}, headers=auth
    )
    assert resp.status_code == 201
    assert resp.json()["provider_npi"] == "1234567893"


def test_future_dob_and_bad_names_rejected(client, auth):
    resp = client.post("/orders", json={**VALID_ORDER, "patient_dob": "2999-01-01"}, headers=auth)
    assert resp.status_code == 422
    resp = client.post("/orders", json={**VALID_ORDER, "patient_last_name": "Cur1e"}, headers=auth)
    assert resp.status_code == 422


def test_unknown_order_id_and_malformed_id(client, auth):
    missing = client.get("/orders/00000000-0000-0000-0000-000000000000", headers=auth)
    assert missing.status_code == 404
    assert client.get("/orders/not-a-uuid", headers=auth).status_code == 422
