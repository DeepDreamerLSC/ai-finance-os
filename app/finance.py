from __future__ import annotations

import base64
import mimetypes
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.categories import (
    category_options,
    classify_transaction,
    normalize_tags,
    validate_classification,
)
from app.config import settings
from app.money import money_decimal
from app.models import Ledger, Receipt, Transaction, User


DEMO_RECEIPT_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1040" viewBox="0 0 720 1040">
  <rect width="720" height="1040" fill="#eef2f3"/>
  <rect x="92" y="50" width="536" height="940" rx="18" fill="#fff" stroke="#dce4e5" stroke-width="2"/>
  <text x="360" y="124" text-anchor="middle" font-family="Arial, sans-serif" font-size="36" font-weight="700" fill="#102428">盒马鲜生</text>
  <text x="360" y="166" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" fill="#66787b">演示凭证 · 非真实消费票据</text>
  <path d="M132 206H588" stroke="#cbd5d7" stroke-width="2" stroke-dasharray="8 8"/>
  <text x="132" y="254" font-family="Arial, sans-serif" font-size="20" fill="#43575a">日期</text>
  <text x="588" y="254" text-anchor="end" font-family="Arial, sans-serif" font-size="20" fill="#102428">2026-07-05</text>
  <path d="M132 346H588" stroke="#cbd5d7" stroke-width="2"/>
  <text x="132" y="454" font-family="Arial, sans-serif" font-size="20" fill="#43575a">生鲜与日用采购</text>
  <text x="588" y="454" text-anchor="end" font-family="Arial, sans-serif" font-size="20" fill="#102428">¥268.00</text>
  <path d="M132 600H588" stroke="#cbd5d7" stroke-width="2"/>
  <text x="132" y="668" font-family="Arial, sans-serif" font-size="25" font-weight="700" fill="#102428">合计</text>
  <text x="588" y="668" text-anchor="end" font-family="Arial, sans-serif" font-size="34" font-weight="700" fill="#0d8f83">¥268.00</text>
  <text x="360" y="914" text-anchor="middle" font-family="Arial, sans-serif" font-size="17" fill="#89999b">AI Personal Finance OS Demo</text>
</svg>
"""
def _money(value: float) -> str:
    return f"¥{Decimal(str(value)):,.2f}"


def classify(text: str) -> str:
    return classify_transaction(text, _transaction_type(text))["category"]


def _transaction_type(text: str) -> str:
    return "income" if any(
        word in text for word in ("奖金", "收入", "工资", "薪资", "到账", "退款", "提成")
    ) else "expense"


def _extract_date(text: str) -> str:
    match = re.search(r"(20\d{2})[年\-/](\d{1,2})[月\-/](\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return date.today().isoformat()


def parse_command(text: str) -> dict:
    normalized = re.sub(r"\s+", "", text.strip())
    ledger_match = re.search(r"(20\d{2})账本", normalized)
    ledger = {"name": f"{ledger_match.group(1)} 账本"} if ledger_match else None
    amounts = list(
        re.finditer(r"([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*元", normalized)
    )
    transactions: list[dict] = []
    separators = "，,；;。"
    for index, match in enumerate(amounts):
        amount = money_decimal(match.group(1).replace(",", "").replace("，", ""))
        previous = max((normalized.rfind(separator, 0, match.start()) for separator in separators), default=-1)
        next_positions = [normalized.find(separator, match.end()) for separator in separators]
        next_positions = [position for position in next_positions if position >= 0]
        start = previous + 1 if previous >= 0 else max(0, match.start() - 16)
        end = min(len(normalized), min(next_positions) + 1 if next_positions else match.end() + 18)
        context = normalized[start:end]
        transaction_type = _transaction_type(context)
        classification = classify_transaction(context, transaction_type, source="natural-language")
        note = context.replace(match.group(0), "").strip("，,。；; ") or "自然语言记录"
        transactions.append(
            {
                "amount": float(amount),
                "type": transaction_type,
                **classification,
                "note": note[:32],
                "date": _extract_date(normalized),
                "source": "natural-language",
                "sequence": index + 1,
            }
        )
    return {"ledger": ledger, "transactions": transactions, "raw": text}


def _ledger_payload(ledger: Ledger) -> dict:
    return {"id": ledger.id, "name": ledger.name, "createdAt": ledger.created_at.isoformat()}


def _transaction_payload(transaction: Transaction, receipt_id: str | None = None) -> dict:
    payload = {
        "id": transaction.id,
        "ledgerId": transaction.ledger_id,
        "amount": float(transaction.amount),
        "type": transaction.type,
        "category": transaction.category,
        "subcategory": transaction.subcategory,
        "tags": transaction.tags or [],
        "note": transaction.note,
        "date": transaction.transaction_date.isoformat(),
        "source": transaction.source,
    }
    if receipt_id:
        payload["receiptId"] = receipt_id
    return payload


def _receipt_payload(receipt: Receipt) -> dict:
    payload = {
        "id": receipt.id,
        "filename": receipt.original_name,
        "merchant": receipt.merchant,
        "amount": float(receipt.amount),
        "date": receipt.receipt_date.isoformat(),
        "category": receipt.category,
        "fileUrl": f"/api/receipts/{receipt.id}/file",
        "createdAt": receipt.created_at.isoformat(),
    }
    if receipt.transaction_id:
        payload["transactionId"] = receipt.transaction_id
    return payload


def ensure_ledger(db: Session, user_id: str, name: str) -> Ledger:
    ledger = db.scalar(select(Ledger).where(Ledger.user_id == user_id, Ledger.name == name))
    if ledger:
        return ledger
    ledger = Ledger(user_id=user_id, name=name[:80])
    db.add(ledger)
    db.flush()
    return ledger


def create_ledger(db: Session, user_id: str, name: str) -> dict:
    normalized = re.sub(r"\s+", " ", name).strip()
    if not normalized:
        raise ValueError("请输入账本名称")
    if len(normalized) > 80:
        raise ValueError("账本名称不能超过 80 个字符")
    if db.scalar(select(Ledger.id).where(Ledger.user_id == user_id, Ledger.name == normalized)):
        raise ValueError("同名账本已经存在")
    ledger = Ledger(user_id=user_id, name=normalized)
    db.add(ledger)
    db.commit()
    return _ledger_payload(ledger)


def update_ledger(db: Session, user_id: str, ledger_id: str, name: str) -> dict | None:
    ledger = db.scalar(select(Ledger).where(Ledger.id == ledger_id, Ledger.user_id == user_id))
    if not ledger:
        return None
    normalized = re.sub(r"\s+", " ", name).strip()
    if not normalized:
        raise ValueError("请输入账本名称")
    if len(normalized) > 80:
        raise ValueError("账本名称不能超过 80 个字符")
    duplicate = db.scalar(
        select(Ledger.id).where(
            Ledger.user_id == user_id,
            Ledger.name == normalized,
            Ledger.id != ledger_id,
        )
    )
    if duplicate:
        raise ValueError("同名账本已经存在")
    ledger.name = normalized
    db.commit()
    return _ledger_payload(ledger)


def delete_ledger(db: Session, user_id: str, ledger_id: str) -> bool:
    ledger = db.scalar(select(Ledger).where(Ledger.id == ledger_id, Ledger.user_id == user_id))
    if not ledger:
        return False
    transaction_ids = list(
        db.scalars(select(Transaction.id).where(Transaction.ledger_id == ledger.id))
    )
    if transaction_ids:
        receipts = list(
            db.scalars(
                select(Receipt).where(
                    Receipt.user_id == user_id,
                    Receipt.transaction_id.in_(transaction_ids),
                )
            )
        )
        for receipt in receipts:
            receipt.transaction_id = None
    db.delete(ledger)
    db.commit()
    return True


def seed_user_data(db: Session, user: User) -> None:
    if db.scalar(select(Ledger.id).where(Ledger.user_id == user.id)):
        return
    ledger = ensure_ledger(db, user.id, f"{date.today().year} 账本")

    def month_date(months_ago: int, day: int) -> date:
        today = date.today()
        month_index = today.year * 12 + today.month - 1 - months_ago
        year, month_zero = divmod(month_index, 12)
        return date(year, month_zero + 1, min(day, 28))

    rows = [
        (268, "expense", "购物", "盒马采购", month_date(0, 5), "receipt"),
        (112, "expense", "交通", "停车费", month_date(0, 8), "manual"),
        (500, "income", "奖金", "销冠奖金", month_date(0, 10), "manual"),
        (860, "expense", "餐饮", "外卖", month_date(0, 12), "manual"),
        (620, "expense", "餐饮", "餐厅聚餐", month_date(1, 11), "manual"),
        (4200, "expense", "住房", "房租", month_date(1, 2), "manual"),
        (740, "expense", "餐饮", "外卖", month_date(2, 15), "manual"),
        (3800, "expense", "住房", "房租", month_date(2, 3), "manual"),
        (420, "expense", "交通", "打车", month_date(3, 18), "manual"),
    ]
    transactions = []
    for amount, transaction_type, category, note, transaction_date, source in rows:
        classification = classify_transaction(
            note,
            transaction_type,
            existing_category=category,
            source=source,
            has_receipt=source == "receipt",
        )
        transactions.append(
            Transaction(
                ledger_id=ledger.id,
                amount=Decimal(str(amount)),
                type=transaction_type,
                category=classification["category"],
                subcategory=classification["subcategory"],
                tags=classification["tags"],
                note=note,
                transaction_date=transaction_date,
                source=source,
            )
        )
    db.add_all(transactions)
    db.flush()

    user_dir = settings.upload_dir / user.id
    user_dir.mkdir(parents=True, exist_ok=True)
    storage_key = f"{user.id}/demo-receipt.svg"
    (settings.upload_dir / storage_key).write_text(DEMO_RECEIPT_SVG, encoding="utf-8")
    db.add(
        Receipt(
            user_id=user.id,
            transaction_id=transactions[0].id,
            original_name="盒马演示小票.svg",
            storage_key=storage_key,
            mime_type="image/svg+xml",
            merchant="盒马鲜生",
            amount=Decimal("268"),
            receipt_date=month_date(0, 5),
            category="购物",
        )
    )


def build_state(db: Session, user_id: str) -> dict:
    ledgers = list(db.scalars(select(Ledger).where(Ledger.user_id == user_id).order_by(Ledger.created_at)))
    ledger_ids = [ledger.id for ledger in ledgers]
    transactions = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.ledger_id.in_(ledger_ids) if ledger_ids else False)
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        )
    )
    receipts = list(
        db.scalars(select(Receipt).where(Receipt.user_id == user_id).order_by(Receipt.created_at.desc()))
    )
    receipt_by_transaction = {
        receipt.transaction_id: receipt.id for receipt in receipts if receipt.transaction_id
    }
    state = {
        "ledgers": [_ledger_payload(ledger) for ledger in ledgers],
        "transactions": [
            _transaction_payload(transaction, receipt_by_transaction.get(transaction.id))
            for transaction in transactions
        ],
        "receipts": [_receipt_payload(receipt) for receipt in receipts],
        "categoryOptions": category_options(),
    }
    state["dashboard"] = dashboard(state)
    return state


def add_transactions(db: Session, user_id: str, parsed: dict, ledger_name: str | None = None) -> list[dict]:
    ledgers = list(db.scalars(select(Ledger).where(Ledger.user_id == user_id).order_by(Ledger.created_at)))
    name = ledger_name or (parsed.get("ledger") or {}).get("name") or (
        ledgers[0].name if ledgers else f"{date.today().year} 账本"
    )
    ledger = ensure_ledger(db, user_id, name)
    added = []
    for item in parsed.get("transactions", []):
        amount = money_decimal(item["amount"])
        transaction_type = item.get("type", "expense")
        classification = classify_transaction(
            str(item.get("note", "")),
            transaction_type,
            existing_category=str(item.get("category") or ""),
            source=item.get("source", "manual"),
            tags=item.get("tags"),
        )
        transaction = Transaction(
            ledger_id=ledger.id,
            amount=amount,
            type=transaction_type,
            category=classification["category"],
            subcategory=str(item.get("subcategory") or classification["subcategory"])[:32],
            tags=classification["tags"],
            note=str(item.get("note", "自然语言记录"))[:80],
            transaction_date=datetime.strptime(
                item.get("date") or date.today().isoformat(), "%Y-%m-%d"
            ).date(),
            source=item.get("source", "manual"),
        )
        db.add(transaction)
        db.flush()
        added.append(_transaction_payload(transaction))
    db.commit()
    return added


def update_transaction(db: Session, user_id: str, transaction_id: str, updates: dict) -> dict | None:
    transaction = db.scalar(
        select(Transaction)
        .join(Ledger, Transaction.ledger_id == Ledger.id)
        .where(Transaction.id == transaction_id, Ledger.user_id == user_id)
    )
    if not transaction:
        return None
    allowed = {"ledgerId", "amount", "type", "category", "subcategory", "tags", "note", "date"}
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported fields: {', '.join(sorted(unknown))}")
    if "ledgerId" in updates:
        target_ledger = db.scalar(
            select(Ledger).where(
                Ledger.id == str(updates["ledgerId"]),
                Ledger.user_id == user_id,
            )
        )
        if not target_ledger:
            raise ValueError("目标账本不存在")
        transaction.ledger_id = target_ledger.id
    if "amount" in updates:
        transaction.amount = money_decimal(updates["amount"])
    if "type" in updates:
        if updates["type"] not in {"expense", "income"}:
            raise ValueError("type must be expense or income")
        transaction.type = updates["type"]
        if "category" not in updates:
            classification = classify_transaction(
                transaction.note,
                transaction.type,
                existing_category=transaction.category,
                source=transaction.source,
                tags=transaction.tags,
            )
            transaction.category = classification["category"]
            transaction.subcategory = classification["subcategory"]
    if "category" in updates:
        category = str(updates["category"]).strip()
        if not category:
            raise ValueError("category cannot be empty")
        transaction.category = category[:24]
        if "subcategory" not in updates:
            transaction.subcategory = "其他"
    if "subcategory" in updates:
        subcategory = str(updates["subcategory"]).strip()
        if not subcategory:
            raise ValueError("subcategory cannot be empty")
        transaction.subcategory = subcategory[:32]
    if "tags" in updates:
        transaction.tags = normalize_tags(updates["tags"])
    if "note" in updates:
        note = str(updates["note"]).strip()
        if not note:
            raise ValueError("note cannot be empty")
        transaction.note = note[:80]
    if "date" in updates:
        transaction.transaction_date = datetime.strptime(str(updates["date"]), "%Y-%m-%d").date()
    validate_classification(transaction.type, transaction.category, transaction.subcategory)
    db.commit()
    return _transaction_payload(transaction)


def delete_transaction(db: Session, user_id: str, transaction_id: str) -> bool:
    transaction = db.scalar(
        select(Transaction)
        .join(Ledger, Transaction.ledger_id == Ledger.id)
        .where(Transaction.id == transaction_id, Ledger.user_id == user_id)
    )
    if not transaction:
        return False
    receipt = db.scalar(
        select(Receipt).where(Receipt.user_id == user_id, Receipt.transaction_id == transaction.id)
    )
    if receipt:
        receipt.transaction_id = None
    db.delete(transaction)
    db.commit()
    return True


def create_receipt(db: Session, user_id: str, payload: dict) -> dict:
    filename = str(payload.get("filename") or "receipt.bin")
    safe_name = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]", "_", filename)[:120] or "receipt.bin"
    try:
        raw_data = base64.b64decode(payload.get("data", ""), validate=True)
    except Exception as exc:
        raise ValueError("invalid receipt data") from exc
    if not raw_data or len(raw_data) > 8_000_000:
        raise ValueError("receipt must contain 1 byte to 8 MB")
    receipt_id = str(uuid.uuid4())
    storage_key = f"{user_id}/{receipt_id}-{safe_name}"
    target = (settings.upload_dir / storage_key).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw_data)
    text = f"{filename} {payload.get('hint', '')}"
    amount_match = re.search(r"([0-9][\d,]*(?:\.\d+)?)\s*元?", text)
    amount = money_decimal(amount_match.group(1) if amount_match else "268", field="凭证金额")
    receipt = Receipt(
        id=receipt_id,
        user_id=user_id,
        original_name=filename[:160],
        storage_key=storage_key,
        mime_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        merchant="盒马鲜生" if "盒马" in text else "待确认商户",
        amount=amount,
        receipt_date=date.today(),
        category=classify(text),
    )
    db.add(receipt)
    db.commit()
    return _receipt_payload(receipt)


def update_receipt(db: Session, user_id: str, receipt_id: str, updates: dict) -> dict | None:
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt_id, Receipt.user_id == user_id))
    if not receipt:
        return None
    allowed = {"merchant", "amount", "category", "date"}
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported fields: {', '.join(sorted(unknown))}")
    if "merchant" in updates:
        merchant = str(updates["merchant"]).strip()
        if not merchant:
            raise ValueError("merchant cannot be empty")
        receipt.merchant = merchant[:80]
    if "amount" in updates:
        receipt.amount = money_decimal(updates["amount"])
    if "category" in updates:
        category = str(updates["category"]).strip()
        if not category:
            raise ValueError("category cannot be empty")
        receipt.category = category[:24]
    if "date" in updates:
        receipt.receipt_date = datetime.strptime(str(updates["date"]), "%Y-%m-%d").date()
    db.commit()
    return _receipt_payload(receipt)


def apply_receipt(
    db: Session, user_id: str, receipt_id: str, ledger_name: str | None = None
) -> tuple[dict | None, bool]:
    receipt = db.scalar(
        select(Receipt).where(Receipt.id == receipt_id, Receipt.user_id == user_id).with_for_update()
    )
    if not receipt:
        return None, False
    if receipt.transaction_id:
        existing = db.scalar(
            select(Transaction)
            .join(Ledger, Transaction.ledger_id == Ledger.id)
            .where(Transaction.id == receipt.transaction_id, Ledger.user_id == user_id)
        )
        if existing:
            return _transaction_payload(existing, receipt.id), False
    ledger = ensure_ledger(
        db,
        user_id,
        ledger_name
        or db.scalar(select(Ledger.name).where(Ledger.user_id == user_id).order_by(Ledger.created_at))
        or f"{date.today().year} 账本",
    )
    classification = classify_transaction(
        receipt.merchant,
        "expense",
        existing_category=receipt.category,
        source="receipt",
        has_receipt=True,
    )
    transaction = Transaction(
        ledger_id=ledger.id,
        amount=receipt.amount,
        type="expense",
        category=classification["category"],
        subcategory=classification["subcategory"],
        tags=classification["tags"],
        note=receipt.merchant,
        transaction_date=receipt.receipt_date,
        source="receipt",
    )
    db.add(transaction)
    db.flush()
    receipt.transaction_id = transaction.id
    db.commit()
    return _transaction_payload(transaction, receipt.id), True


def receipt_file(db: Session, user_id: str, receipt_id: str) -> tuple[Path, str, str] | None:
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt_id, Receipt.user_id == user_id))
    if not receipt:
        return None
    root = settings.upload_dir.resolve()
    path = (root / receipt.storage_key).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path, receipt.mime_type, receipt.original_name


def dashboard(state: dict) -> dict:
    transactions = state["transactions"]
    if not transactions:
        return {
            "month": date.today().strftime("%Y-%m"),
            "spend": 0,
            "income": 0,
            "net": 0,
            "categories": {},
            "trend": [],
            "recent": [],
            "priorAverage": 0,
            "increase": 0,
            "increasePercent": 0,
            "insight": "还没有交易，先用一句话记下第一笔账。",
        }
    focus_month = max(tx["date"][:7] for tx in transactions)
    month_txs = [tx for tx in transactions if tx["date"].startswith(focus_month)]
    spend = sum(tx["amount"] for tx in month_txs if tx["type"] == "expense")
    income = sum(tx["amount"] for tx in month_txs if tx["type"] == "income")
    categories: dict[str, float] = {}
    for tx in month_txs:
        if tx["type"] == "expense":
            categories[tx["category"]] = categories.get(tx["category"], 0) + tx["amount"]
    trend = []
    focus_year, focus_month_number = map(int, focus_month.split("-"))
    focus_index = focus_year * 12 + focus_month_number - 1
    for offset in range(5, -1, -1):
        month_index = focus_index - offset
        year, month_zero = divmod(month_index, 12)
        month_key = f"{year:04d}-{month_zero + 1:02d}"
        trend.append(
            {
                "month": month_key,
                "value": round(
                    sum(
                        tx["amount"]
                        for tx in transactions
                        if tx["date"].startswith(month_key) and tx["type"] == "expense"
                    ),
                    2,
                ),
            }
        )
    prior_values = [item["value"] for item in trend[:-1] if item["value"] > 0]
    average = sum(prior_values) / len(prior_values) if prior_values else 0
    top_category, _ = max(categories.items(), key=lambda item: item[1], default=("其他", 0))
    increase = max(0, spend - average)
    insight = (
        f"本月{top_category}消费占比最高；整体支出比过去平均增加约 "
        f"{round(increase / average * 100)}%，主要来自{top_category}。"
        if average and increase > 0
        else f"本月{top_category}是主要支出类别，继续保持对高频消费的关注。"
    )
    return {
        "month": focus_month,
        "spend": round(spend, 2),
        "income": round(income, 2),
        "net": round(income - spend, 2),
        "categories": categories,
        "trend": trend,
        "recent": sorted(transactions, key=lambda tx: tx["date"], reverse=True)[:8],
        "priorAverage": round(average, 2),
        "increase": round(increase, 2),
        "increasePercent": round(increase / average * 100) if average else 0,
        "insight": insight,
    }


def insights_answer(state: dict, question: str) -> dict:
    data = dashboard(state)
    if "为什" in question or "花" in question or "支出" in question:
        categories = sorted(data["categories"].items(), key=lambda item: item[1], reverse=True)
        reasons = [{"category": category, "amount": amount} for category, amount in categories[:3]]
        comparison = (
            f"比过去平均增加 {_money(data['increase'])}（约 {data['increasePercent']}%）"
            if data["increase"] > 0
            else "没有高于过去平均"
        )
        return {
            "answer": (
                f"本月支出为 {_money(data['spend'])}，{comparison}。主要原因来自 "
                f"{reasons[0]['category'] if reasons else '暂无分类'}，我把变化拆解如下。"
            ),
            "reasons": reasons,
            "suggestion": "优先减少高频、非计划支出，同时保留必要的生活与体验预算。",
            "data": data,
        }
    return {
        "answer": "我可以解释本月支出、分类变化、现金流和可执行建议。试试问我：为什么这个月花这么多？",
        "reasons": [],
        "suggestion": "",
        "data": data,
    }


class FinanceAgent:
    provider = os.getenv("AI_PROVIDER", "demo")

    def parse(self, text: str) -> dict:
        return parse_command(text)

    def answer(self, state: dict, question: str) -> dict:
        return insights_answer(state, question)


FINANCE_AGENT = FinanceAgent()
