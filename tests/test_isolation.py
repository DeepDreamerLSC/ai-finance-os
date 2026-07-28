from __future__ import annotations

from fastapi.testclient import TestClient

from app.server import app


def _auth(client: TestClient, phone: str) -> dict:
    sent = client.post("/api/auth/sms/send", json={"phone": phone})
    response = client.post(
        "/api/auth/login/sms",
        json={"phone": phone, "sms_code": sent.json()["debug_code"]},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_finance_apis_require_authentication(client):
    for method, path in [
        ("get", "/api/state"),
        ("get", "/api/insights"),
        ("post", "/api/parse"),
        ("post", "/api/transactions/batch"),
        ("post", "/api/receipts"),
    ]:
        response = (
            client.post(path, json={})
            if method == "post"
            else client.get(path)
        )
        assert response.status_code in {401, 422}


def test_users_cannot_read_or_mutate_each_others_finance_data(client, fake_redis):
    headers_a = _auth(client, "13800138100")
    state_a = client.get("/api/state", headers=headers_a).json()
    transaction_a = state_a["transactions"][0]
    receipt_a = state_a["receipts"][0]

    fake_redis.flushall()
    client.cookies.clear()
    headers_b = _auth(client, "13800138101")
    state_b = client.get("/api/state", headers=headers_b).json()
    assert {row["id"] for row in state_a["ledgers"]}.isdisjoint(
        {row["id"] for row in state_b["ledgers"]}
    )

    assert client.patch(
        f"/api/transactions/{transaction_a['id']}",
        headers=headers_b,
        json={"note": "越权修改"},
    ).status_code == 404
    assert client.delete(
        f"/api/transactions/{transaction_a['id']}",
        headers=headers_b,
    ).status_code == 404
    assert client.patch(
        f"/api/receipts/{receipt_a['id']}",
        headers=headers_b,
        json={"merchant": "越权修改"},
    ).status_code == 404
    assert client.post(
        "/api/receipts/apply",
        headers=headers_b,
        json={"receiptId": receipt_a["id"]},
    ).status_code == 404
    assert client.get(
        receipt_a["fileUrl"],
        headers=headers_b,
    ).status_code == 404

    own_file = client.get(state_b["receipts"][0]["fileUrl"], headers=headers_b)
    assert own_file.status_code == 200
    assert own_file.headers["content-type"].startswith("image/")
