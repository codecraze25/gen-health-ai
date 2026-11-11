"""End-to-end smoke test against a running deployment.

Usage: uv run python scripts/smoke_test.py https://your-service.onrender.com [path/to/order.pdf]
"""

import sys
import uuid

import httpx


def main(base_url: str, pdf_path: str | None = None) -> None:
    c = httpx.Client(base_url=base_url.rstrip("/"), timeout=120)

    def check(label: str, resp: httpx.Response, expected: int) -> httpx.Response:
        ok = resp.status_code == expected
        print(f"{'PASS' if ok else 'FAIL'}  {label}: {resp.status_code}")
        if not ok:
            print(resp.text)
            sys.exit(1)
        return resp

    def login(email: str) -> dict[str, str]:
        check(
            "register",
            c.post("/auth/register", json={"email": email, "password": "pw-12345678"}),
            201,
        )
        token = check(
            "login", c.post("/auth/login", data={"username": email, "password": "pw-12345678"}), 200
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    check("health", c.get("/health"), 200)
    alice = login(f"smoke-a-{uuid.uuid4().hex[:8]}@example.com")
    bob = login(f"smoke-b-{uuid.uuid4().hex[:8]}@example.com")

    order = check(
        "create order",
        c.post(
            "/orders",
            headers=alice,
            json={
                "patient_first_name": "Marie",
                "patient_last_name": "Curie",
                "patient_dob": "1950-12-05",
                "provider_name": "Arjun Raj",
                "provider_npi": "1234567893",
            },
        ),
        201,
    ).json()
    assert order["status"] == "ready", order
    oid = order["id"]

    assert check("list", c.get("/orders", headers=alice), 200).json()["total"] >= 1
    check("other user cannot read", c.get(f"/orders/{oid}", headers=bob), 404)
    check("patch", c.patch(f"/orders/{oid}", headers=alice, json={"notes": "smoke"}), 200)
    check(
        "bad npi rejected",
        c.patch(f"/orders/{oid}", headers=alice, json={"provider_npi": "9182734556"}),
        422,
    )
    check("delete", c.delete(f"/orders/{oid}", headers=alice), 204)
    check("deleted is gone", c.get(f"/orders/{oid}", headers=alice), 404)

    if pdf_path:
        with open(pdf_path, "rb") as f:
            resp = check(
                "upload pdf",
                c.post(
                    "/orders/upload",
                    headers=alice,
                    files={"file": (pdf_path, f, "application/pdf")},
                ),
                201,
            )
        print(resp.json())

    print("All smoke checks passed.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
