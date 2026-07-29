from __future__ import annotations

import io
from decimal import Decimal

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


def make_alipay_csv(*, duplicate_expense: bool = False) -> bytes:
    rows = [
        "支付宝交易明细",
        "交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注",
        "2026-07-28 19:41:15,餐饮美食,盒马,/,生鲜商品,支出,33.03,信用卡,交易成功,ali-order-1,merchant-1,",
        "2026-07-28 18:00:00,退款,盒马,/,退款,收入,3.00,信用卡,退款成功,ali-order-2,merchant-2,",
        "2026-07-28 17:00:00,账户转存,余额宝,/,转入,不计收支,500.00,余额,交易成功,ali-neutral-1,merchant-3,",
    ]
    if duplicate_expense:
        rows.insert(3, rows[2])
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
    assert parsed["transactions"][0]["amount"] == 33.03


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
    assert preview["conflictCount"] == 0

    commit_response = client.post(
        "/api/imports/commit",
        json={"ledgerId": ledger_id, "transactions": preview["transactions"]},
        headers=auth["headers"],
    )
    assert commit_response.status_code == 201, commit_response.text
    assert commit_response.json()["importedCount"] == 2
    assert commit_response.json()["updatedCount"] == 0
    imported = list(
        db_session.scalars(select(Transaction).where(Transaction.ledger_id == ledger_id))
    )
    assert {row.source for row in imported} == {"alipay-import"}
    assert {row.amount for row in imported} == {Decimal("33.03"), Decimal("3.00")}

    duplicate_response = client.post(
        "/api/imports/preview",
        files={"file": ("支付宝交易明细.csv", make_alipay_csv(), "text/csv")},
        headers=auth["headers"],
    )
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["duplicateCount"] == 2
    assert duplicate_response.json()["importableCount"] == 0
    assert duplicate_response.json()["conflictCount"] == 0


def test_import_preview_deduplicates_repeated_rows_inside_one_file(client, login):
    auth = login("13800138041")
    preview_response = client.post(
        "/api/imports/preview",
        files={
            "file": (
                "支付宝重复交易.csv",
                make_alipay_csv(duplicate_expense=True),
                "text/csv",
            )
        },
        headers=auth["headers"],
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["totalRows"] == 4
    assert preview["importableCount"] == 2
    assert preview["duplicateCount"] == 1
    assert preview["conflictCount"] == 0
    duplicate = next(row for row in preview["transactions"] if row["duplicate"])
    assert duplicate["duplicateReason"] == "文件内重复"


def test_import_conflict_requires_explicit_version_choice(client, login, db_session):
    auth = login("13800138042")
    ledger_id = client.post(
        "/api/ledgers",
        json={"name": "导入冲突测试"},
        headers=auth["headers"],
    ).json()["ledger"]["id"]
    preview = client.post(
        "/api/imports/preview",
        files={"file": ("支付宝交易明细.csv", make_alipay_csv(), "text/csv")},
        headers=auth["headers"],
    ).json()
    committed = client.post(
        "/api/imports/commit",
        json={"ledgerId": ledger_id, "transactions": preview["transactions"]},
        headers=auth["headers"],
    )
    assert committed.status_code == 201, committed.text

    transaction = db_session.scalar(
        select(Transaction).where(
            Transaction.ledger_id == ledger_id,
            Transaction.note == "盒马 · 生鲜商品",
        )
    )
    changed = client.patch(
        f"/api/transactions/{transaction.id}",
        json={
            "ledgerId": ledger_id,
            "amount": "44.04",
            "type": "expense",
            "category": "购物",
            "note": "盒马调整",
            "date": "2026-07-29",
        },
        headers=auth["headers"],
    )
    assert changed.status_code == 200, changed.text

    conflict_preview = client.post(
        "/api/imports/preview",
        files={"file": ("支付宝交易明细.csv", make_alipay_csv(), "text/csv")},
        headers=auth["headers"],
    ).json()
    assert conflict_preview["conflictCount"] == 1
    assert conflict_preview["duplicateCount"] == 1
    conflict = next(row for row in conflict_preview["transactions"] if row["conflict"])
    assert conflict["amount"] == 33.03
    assert conflict["existingTransaction"]["amount"] == 44.04
    assert conflict["existingTransaction"]["note"] == "盒马调整"

    keep_existing = client.post(
        "/api/imports/commit",
        json={
            "ledgerId": ledger_id,
            "transactions": [{**conflict, "resolution": "keep-existing"}],
        },
        headers=auth["headers"],
    )
    assert keep_existing.status_code == 201, keep_existing.text
    assert keep_existing.json()["updatedCount"] == 0
    assert keep_existing.json()["skippedCount"] == 1
    db_session.refresh(transaction)
    assert transaction.amount == Decimal("44.04")
    assert transaction.note == "盒马调整"

    replace_with_file = client.post(
        "/api/imports/commit",
        json={
            "ledgerId": ledger_id,
            "transactions": [{**conflict, "resolution": "replace-existing"}],
        },
        headers=auth["headers"],
    )
    assert replace_with_file.status_code == 201, replace_with_file.text
    assert replace_with_file.json()["updatedCount"] == 1
    db_session.refresh(transaction)
    assert transaction.amount == Decimal("33.03")
    assert transaction.category == "餐饮"
    assert transaction.note == "盒马 · 生鲜商品"
    assert transaction.transaction_date.isoformat() == "2026-07-28"


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


def test_ledger_can_be_renamed_and_deleted_with_its_transactions(client, login, db_session):
    auth = login("13800138036")
    ledger = client.post(
        "/api/ledgers",
        json={"name": "旧账本"},
        headers=auth["headers"],
    ).json()["ledger"]
    create_transaction = client.post(
        "/api/transactions/batch",
        json={
            "ledgerName": "旧账本",
            "transactions": [
                {
                    "amount": "12.34",
                    "type": "expense",
                    "category": "其他",
                    "note": "待删除记录",
                    "date": "2026-07-29",
                }
            ],
        },
        headers=auth["headers"],
    )
    assert create_transaction.status_code == 201

    renamed = client.patch(
        f"/api/ledgers/{ledger['id']}",
        json={"name": "新账本"},
        headers=auth["headers"],
    )
    assert renamed.status_code == 200
    assert renamed.json()["ledger"]["name"] == "新账本"

    deleted = client.delete(f"/api/ledgers/{ledger['id']}", headers=auth["headers"])
    assert deleted.status_code == 200
    assert not db_session.scalar(select(Ledger).where(Ledger.id == ledger["id"]))
    assert not db_session.scalar(select(Transaction).where(Transaction.ledger_id == ledger["id"]))


def test_ledger_management_is_scoped_to_current_user(client, login):
    owner = login("13800138037")
    ledger_id = client.post(
        "/api/ledgers",
        json={"name": "仅本人可见"},
        headers=owner["headers"],
    ).json()["ledger"]["id"]
    other = login("13800138038")
    assert client.patch(
        f"/api/ledgers/{ledger_id}",
        json={"name": "越权重命名"},
        headers=other["headers"],
    ).status_code == 404
    assert client.delete(f"/api/ledgers/{ledger_id}", headers=other["headers"]).status_code == 404


def test_money_with_more_than_two_decimals_is_rejected_instead_of_rounded(client, login):
    auth = login("13800138039")
    response = client.post(
        "/api/transactions/batch",
        json={
            "ledgerName": "精确金额",
            "transactions": [
                {
                    "amount": "12.345",
                    "type": "expense",
                    "category": "其他",
                    "note": "不得四舍五入",
                    "date": "2026-07-29",
                }
            ],
        },
        headers=auth["headers"],
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "金额最多保留两位小数"


def test_transaction_full_details_can_be_edited_and_moved_between_ledgers(
    client, login, db_session
):
    auth = login("13800138040")
    state = client.get("/api/state", headers=auth["headers"]).json()
    transaction = next(row for row in state["transactions"] if row["note"] == "停车费")
    target_ledger = client.post(
        "/api/ledgers",
        json={"name": "报销账本"},
        headers=auth["headers"],
    ).json()["ledger"]

    response = client.patch(
        f"/api/transactions/{transaction['id']}",
        json={
            "ledgerId": target_ledger["id"],
            "amount": "112.36",
            "type": "income",
            "category": "退款报销",
            "subcategory": "公司报销",
            "tags": ["工作", "可报销"],
            "note": "停车报销",
            "date": "2026-07-09",
        },
        headers=auth["headers"],
    )
    assert response.status_code == 200, response.text
    updated = response.json()["transaction"]
    assert updated == {
        "id": transaction["id"],
        "ledgerId": target_ledger["id"],
        "amount": 112.36,
        "type": "income",
        "category": "退款报销",
        "subcategory": "公司报销",
        "tags": ["工作", "可报销"],
        "note": "停车报销",
        "date": "2026-07-09",
        "source": "manual",
    }
    stored = db_session.scalar(select(Transaction).where(Transaction.id == transaction["id"]))
    assert stored.amount == Decimal("112.36")
    assert stored.ledger_id == target_ledger["id"]
    assert stored.subcategory == "公司报销"
    assert stored.tags == ["工作", "可报销"]


def test_transaction_cannot_be_moved_to_another_users_ledger(client, login):
    owner = login("13800138041")
    owner_state = client.get("/api/state", headers=owner["headers"]).json()
    transaction_id = owner_state["transactions"][0]["id"]
    other = login("13800138042")
    other_ledger_id = client.get("/api/state", headers=other["headers"]).json()["ledgers"][0]["id"]

    response = client.patch(
        f"/api/transactions/{transaction_id}",
        json={"ledgerId": other_ledger_id},
        headers=owner["headers"],
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "目标账本不存在"


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
