from __future__ import annotations

import base64

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
    assert client.post(
        f"/api/receipts/{receipt_a['id']}/link",
        headers=headers_b,
        json={"transactionId": state_b["transactions"][0]["id"]},
    ).status_code == 404
    assert client.get(
        receipt_a["fileUrl"],
        headers=headers_b,
    ).status_code == 404

    own_file = client.get(state_b["receipts"][0]["fileUrl"], headers=headers_b)
    assert own_file.status_code == 200
    assert own_file.headers["content-type"].startswith("image/")


def test_receipt_can_match_link_replace_and_update_a_transaction(client):
    headers = _auth(client, "13800138102")
    state = client.get("/api/state", headers=headers).json()
    transaction = next(row for row in state["transactions"] if not row.get("receiptId"))
    upload = client.post(
        "/api/receipts",
        headers=headers,
        json={
            "filename": f"测试凭证-{transaction['amount']}元.png",
            "data": base64.b64encode(b"fake-png-one").decode(),
            "hint": transaction["note"],
        },
    )
    assert upload.status_code == 201
    payload = upload.json()
    assert any(row["id"] == transaction["id"] for row in payload["candidates"])

    linked = client.post(
        f"/api/receipts/{payload['receipt']['id']}/link",
        headers=headers,
        json={"transactionId": transaction["id"]},
    )
    assert linked.status_code == 200
    assert linked.json()["transaction"]["receiptId"] == payload["receipt"]["id"]

    replacement = client.post(
        "/api/receipts",
        headers=headers,
        json={
            "filename": "盒马-99.99元.png",
            "data": base64.b64encode(b"fake-png-two").decode(),
            "hint": "盒马",
        },
    ).json()["receipt"]
    conflict = client.post(
        f"/api/receipts/{replacement['id']}/link",
        headers=headers,
        json={"transactionId": transaction["id"]},
    )
    assert conflict.status_code == 409
    replaced = client.post(
        f"/api/receipts/{replacement['id']}/link",
        headers=headers,
        json={"transactionId": transaction["id"], "replaceExisting": True, "updateTransaction": True},
    )
    assert replaced.status_code == 200
    assert replaced.json()["transaction"]["amount"] == 99.99
    assert replaced.json()["transaction"]["note"] == "盒马鲜生"
