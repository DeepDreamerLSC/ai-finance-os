"""Explicitly import a legacy state.json into one already-created user account."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.auth import normalize_phone
from app.categories import classify_transaction
from app.database import SessionLocal
from app.finance import ensure_ledger
from app.models import Receipt, Transaction, User


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import legacy demo state only after explicitly naming its owner."
    )
    parser.add_argument("--phone", required=True)
    parser.add_argument("--state-file", required=True, type=Path)
    parser.add_argument("--upload-root", type=Path)
    args = parser.parse_args()

    phone = normalize_phone(args.phone)
    state = json.loads(args.state_file.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == phone))
        if not user:
            raise SystemExit("The owner must log in once before importing legacy data.")
        ledger_map = {}
        for item in state.get("ledgers", []):
            ledger = ensure_ledger(db, user.id, str(item.get("name") or "历史账本"))
            ledger_map[str(item.get("id"))] = ledger.id
        transaction_map = {}
        for item in state.get("transactions", []):
            legacy_ledger_id = str(item.get("ledgerId"))
            ledger_id = ledger_map.get(legacy_ledger_id)
            if not ledger_id:
                ledger_id = ensure_ledger(db, user.id, "历史账本").id
            classification = classify_transaction(
                str(item.get("note") or "历史记录"),
                item.get("type", "expense"),
                existing_category=item.get("category"),
                source=item.get("source", "legacy"),
                tags=item.get("tags"),
            )
            transaction = Transaction(
                ledger_id=ledger_id,
                amount=Decimal(str(item["amount"])),
                type=item.get("type", "expense"),
                category=classification["category"],
                subcategory=item.get("subcategory") or classification["subcategory"],
                tags=classification["tags"],
                note=item.get("note", "历史记录"),
                transaction_date=datetime.strptime(item["date"], "%Y-%m-%d").date(),
                source=item.get("source", "legacy"),
            )
            db.add(transaction)
            db.flush()
            transaction_map[str(item.get("id"))] = transaction.id
        for item in state.get("receipts", []):
            if not args.upload_root:
                continue
            legacy_url = str(item.get("url") or "")
            source = args.upload_root / Path(legacy_url).name
            if not source.is_file():
                continue
            destination = Path(f"{user.id}/legacy-{source.name}")
            from app.config import settings

            target = settings.upload_dir / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            db.add(
                Receipt(
                    user_id=user.id,
                    transaction_id=transaction_map.get(str(item.get("transactionId"))),
                    original_name=item.get("filename", source.name),
                    storage_key=str(destination),
                    mime_type="application/octet-stream",
                    merchant=item.get("merchant", "历史凭证"),
                    amount=Decimal(str(item.get("amount", 0))),
                    receipt_date=datetime.strptime(item["date"], "%Y-%m-%d").date(),
                    category=item.get("category", "其他"),
                )
            )
        db.commit()
    print("Legacy state imported for the explicitly selected account.")


if __name__ == "__main__":
    main()
