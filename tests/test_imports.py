from __future__ import annotations

import io

from openpyxl import Workbook
from sqlalchemy import select

from app.imports import parse_bill
from app.models import Ledger, Transaction


def make_wechat_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["微信支付账单明细"])
    sheet.append([])
    sheet.append(
        [
            "交易时间",
            "交易类型",
            "交易对方",
            "商品",
            "收/支",
            "金额(元)",
            "支付方式",
            "当前状态",
            "交易单号",
            "商户单号",
            "备注",
        ]
    )
    sheet.append(
        [
            "2026-07-27 19:17:19",
            "商户消费",
            "停车场",
            "车辆停车缴费",
            "支出",
            10,
            "银行卡",
            "支付成功",
            "wx-order-1",
            "merchant-1",
            "/",
        ]
    )
    sheet.append(
        [
            "2026-07-27 18:00:00",
            "零钱提现",
            "银行",
            "/",
            "/",
            100,
            "银行卡",
            "提现已到账",
            "wx-neutral-1",
            "/",
            "/",
        ]
    )
    sheet.append(
        [
            "2026-07-27 17:00:00",
            "商户消费",
            "失败订单",
            "商品",
            "支出",
            20,
            "银行卡",
            "支付失败",
            "wx-failed-1",
            "/",
            "/",
        ]
    )
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def make_alipay_csv() -> bytes:
    rows = [
        "支付宝交易明细",
        "交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注",
        "2026-07-28 19:41:15,餐饮美食,盒马,/,生鲜商品,支出,33.03,信用卡,交易成功,ali-order-1,merchant-1,",
        "2026-07-28 18:00:00,退款,盒马,/,退款,收入,3.00,信用卡,退款成功,ali-order-2,merchant-2,",
        "2026-07-28 17:00:00,账户转存,余额宝,/,转入,不计收支,500.00,余额,交易成功,ali-neutral-1,merchant-3,",
    ]
    return "\r\n".join(rows).encode("gb18030")


def test_parse_wechat_xlsx_skips_neutral_and_failed_transactions():
    parsed = parse_bill("微信支付账单.xlsx", make_wechat_xlsx())
    assert parsed["provider"] == "wechat"
    assert parsed["totalRows"] == 3
    assert parsed["skippedCount"] == 2
    assert len(parsed["transactions"]) == 1
    assert parsed["transactions"][0]["source"] == "wechat-import"
    assert parsed["transactions"][0]["category"] == "交通"


def test_parse_alipay_gb18030_keeps_expense_and_refund():
    parsed = parse_bill("支付宝交易明细.csv", make_alipay_csv())
    assert parsed["provider"] == "alipay"
    assert parsed["totalRows"] == 3
    assert parsed["skippedCount"] == 1
    assert [row["type"] for row in parsed["transactions"]] == ["expense", "income"]
    assert parsed["transactions"][0]["category"] == "餐饮"


def test_import_preview_commit_and_duplicate_detection(client, login, db_session):
    auth = login("13800138031")
    ledger_response = client.post(
        "/api/ledgers",
        json={"name": "支付平台账单"},
        headers=auth["headers"],
    )
    assert ledger_response.status_code == 201
    ledger_id = ledger_response.json()["ledger"]["id"]

    preview_response = client.post(
        "/api/imports/preview",
        files={"file": ("支付宝交易明细.csv", make_alipay_csv(), "text/csv")},
        headers=auth["headers"],
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["importableCount"] == 2
    assert preview["duplicateCount"] == 0

    commit_response = client.post(
        "/api/imports/commit",
        json={"ledgerId": ledger_id, "transactions": preview["transactions"]},
        headers=auth["headers"],
    )
    assert commit_response.status_code == 201, commit_response.text
    assert commit_response.json()["importedCount"] == 2
    imported = list(
        db_session.scalars(select(Transaction).where(Transaction.ledger_id == ledger_id))
    )
    assert {row.source for row in imported} == {"alipay-import"}

    duplicate_response = client.post(
        "/api/imports/preview",
        files={"file": ("支付宝交易明细.csv", make_alipay_csv(), "text/csv")},
        headers=auth["headers"],
    )
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["duplicateCount"] == 2
    assert duplicate_response.json()["importableCount"] == 0


def test_import_cannot_target_another_users_ledger(client, login, db_session):
    first = login("13800138032")
    ledger_id = client.post(
        "/api/ledgers",
        json={"name": "私有账本"},
        headers=first["headers"],
    ).json()["ledger"]["id"]
    second = login("13800138033")
    preview = client.post(
        "/api/imports/preview",
        files={"file": ("支付宝交易明细.csv", make_alipay_csv(), "text/csv")},
        headers=second["headers"],
    ).json()
    response = client.post(
        "/api/imports/commit",
        json={"ledgerId": ledger_id, "transactions": preview["transactions"]},
        headers=second["headers"],
    )
    assert response.status_code == 400
    assert "目标账本不存在" in response.text
    assert db_session.scalar(select(Ledger).where(Ledger.id == ledger_id))


def test_duplicate_ledger_name_is_rejected(client, login):
    auth = login("13800138034")
    first = client.post(
        "/api/ledgers",
        json={"name": "家庭账本"},
        headers=auth["headers"],
    )
    second = client.post(
        "/api/ledgers",
        json={"name": "家庭账本"},
        headers=auth["headers"],
    )
    assert first.status_code == 201
    assert second.status_code == 400


def test_import_rejects_tampered_preview_rows(client, login):
    auth = login("13800138035")
    ledger_id = client.post(
        "/api/ledgers",
        json={"name": "安全账本"},
        headers=auth["headers"],
    ).json()["ledger"]["id"]
    response = client.post(
        "/api/imports/commit",
        json={
            "ledgerId": ledger_id,
            "transactions": [
                {
                    "importKey": "invalid",
                    "source": "alipay-import",
                    "type": "expense",
                    "amount": "not-a-number",
                    "date": "2026-07-28",
                }
            ],
        },
        headers=auth["headers"],
    )
    assert response.status_code == 400
    assert "重新预览账单" in response.text
