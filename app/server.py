"""Small dependency-free API and static server for the AI Finance OS MVP."""

from __future__ import annotations

import base64
import json
import math
import mimetypes
import os
import re
import signal
import threading
import uuid
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "runtime" / "data"))
UPLOADS_DIR = DATA_DIR / "uploads"
STATE_FILE = DATA_DIR / "state.json"
PORT = int(os.getenv("PORT", "8080"))
HOST = os.getenv("HOST", "0.0.0.0")
STATE_LOCK = threading.RLock()

CATEGORY_RULES = (
    ("交通", ("停车", "打车", "地铁", "公交", "交通", "加油")),
    ("餐饮", ("外卖", "餐", "吃", "咖啡", "餐饮")),
    ("购物", ("盒马", "超市", "购物", "采购", "商场")),
    ("住房", ("房租", "住房", "物业")),
    ("奖金", ("奖金", "销冠", "提成")),
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean_amount(value: str) -> float:
    return float(value.replace(",", "").replace("，", ""))


def _money(value: float) -> str:
    return f"¥{value:,.0f}"


def classify(text: str) -> str:
    for category, keywords in CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "其他"


def _transaction_type(text: str) -> str:
    return "income" if any(word in text for word in ("奖金", "收入", "工资", "薪资", "到账", "退款", "提成")) else "expense"


def _extract_date(text: str) -> str:
    match = re.search(r"(20\d{2})[年\-/](\d{1,2})[月\-/](\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return date.today().isoformat()


def parse_command(text: str) -> dict:
    """Turn supported natural-language demo commands into editable records."""
    normalized = re.sub(r"\s+", "", text.strip())
    ledger_match = re.search(r"(20\d{2})账本", normalized)
    ledger = {"name": f"{ledger_match.group(1)} 账本"} if ledger_match else None
    amounts = list(re.finditer(r"([+-]?\d[\d,，]*(?:\.\d+)?)\s*元", normalized))
    transactions: list[dict] = []
    separators = "，,；;。"
    for index, match in enumerate(amounts):
        amount = _clean_amount(match.group(1))
        previous = max((normalized.rfind(separator, 0, match.start()) for separator in separators), default=-1)
        next_positions = [normalized.find(separator, match.end()) for separator in separators]
        next_positions = [position for position in next_positions if position >= 0]
        start = previous + 1 if previous >= 0 else max(0, match.start() - 16)
        end = min(len(normalized), min(next_positions) + 1 if next_positions else match.end() + 18)
        context = normalized[start:end]
        transaction_type = _transaction_type(context)
        category = classify(context)
        if category == "其他" and transaction_type == "income":
            category = "收入"
        note = context.replace(match.group(0), "").strip("，,。；; ") or "自然语言记录"
        transactions.append({"amount": amount, "type": transaction_type, "category": category, "note": note[:32], "date": _extract_date(normalized), "source": "natural-language", "sequence": index + 1})
    return {"ledger": ledger, "transactions": transactions, "raw": text}


def _seed_state() -> dict:
    today = date.today()
    ledger_id = "ledger-default"

    def d(months_ago: int, day: int) -> str:
        month_index = today.year * 12 + today.month - 1 - months_ago
        year, month_zero = divmod(month_index, 12)
        return f"{year:04d}-{month_zero + 1:02d}-{min(day, 28):02d}"

    transactions = [
        {"id": "tx-seed-1", "ledgerId": ledger_id, "amount": 268, "type": "expense", "category": "购物", "note": "盒马采购", "date": d(0, 5), "source": "receipt", "receiptId": "receipt-seed-1"},
        {"id": "tx-seed-2", "ledgerId": ledger_id, "amount": 112, "type": "expense", "category": "交通", "note": "停车费", "date": d(0, 8), "source": "manual"},
        {"id": "tx-seed-3", "ledgerId": ledger_id, "amount": 500, "type": "income", "category": "奖金", "note": "销冠奖金", "date": d(0, 10), "source": "manual"},
        {"id": "tx-seed-4", "ledgerId": ledger_id, "amount": 860, "type": "expense", "category": "餐饮", "note": "外卖", "date": d(0, 12), "source": "manual"},
        {"id": "tx-seed-5", "ledgerId": ledger_id, "amount": 620, "type": "expense", "category": "餐饮", "note": "餐厅聚餐", "date": d(1, 11), "source": "manual"},
        {"id": "tx-seed-6", "ledgerId": ledger_id, "amount": 4200, "type": "expense", "category": "住房", "note": "房租", "date": d(1, 2), "source": "manual"},
        {"id": "tx-seed-7", "ledgerId": ledger_id, "amount": 740, "type": "expense", "category": "餐饮", "note": "外卖", "date": d(2, 15), "source": "manual"},
        {"id": "tx-seed-8", "ledgerId": ledger_id, "amount": 3800, "type": "expense", "category": "住房", "note": "房租", "date": d(2, 3), "source": "manual"},
        {"id": "tx-seed-9", "ledgerId": ledger_id, "amount": 420, "type": "expense", "category": "交通", "note": "打车", "date": d(3, 18), "source": "manual"},
    ]
    return {"ledgers": [{"id": ledger_id, "name": f"{today.year} 账本", "createdAt": _now_iso()}], "transactions": transactions, "receipts": [{"id": "receipt-seed-1", "filename": "盒马小票.png", "merchant": "盒马鲜生", "amount": 268, "date": d(0, 5), "category": "购物", "url": "", "createdAt": _now_iso()}]}


def _ensure_data() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        _write_state(_seed_state())


def _read_state() -> dict:
    _ensure_data()
    with STATE_LOCK:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = _seed_state()
            _write_state(state)
            return state


def _write_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, STATE_FILE)


def ensure_ledger(state: dict, name: str) -> dict:
    for ledger in state["ledgers"]:
        if ledger["name"] == name:
            return ledger
    ledger = {"id": f"ledger-{uuid.uuid4().hex[:10]}", "name": name, "createdAt": _now_iso()}
    state["ledgers"].append(ledger)
    return ledger


def add_transactions(parsed: dict, ledger_name: str | None = None) -> list[dict]:
    with STATE_LOCK:
        state = _read_state()
        name = ledger_name or (parsed.get("ledger") or {}).get("name") or state["ledgers"][0]["name"]
        ledger = ensure_ledger(state, name)
        added = []
        for item in parsed.get("transactions", []):
            tx = {"id": f"tx-{uuid.uuid4().hex[:10]}", "ledgerId": ledger["id"], "amount": round(float(item["amount"]), 2), "type": item.get("type", "expense"), "category": item.get("category", "其他"), "note": item.get("note", "自然语言记录"), "date": item.get("date") or date.today().isoformat(), "source": item.get("source", "manual")}
            if item.get("receiptId"):
                tx["receiptId"] = item["receiptId"]
            state["transactions"].append(tx)
            added.append(tx)
        _write_state(state)
        return added


def update_transaction(transaction_id: str, updates: dict) -> dict | None:
    """Apply the small set of fields exposed by the MVP ledger editor."""
    allowed = {"amount", "type", "category", "note", "date"}
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported fields: {', '.join(sorted(unknown))}")
    normalized: dict = {}
    if "amount" in updates:
        amount = float(updates["amount"])
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("amount must be a positive number")
        normalized["amount"] = round(amount, 2)
    if "type" in updates:
        transaction_type = str(updates["type"])
        if transaction_type not in {"expense", "income"}:
            raise ValueError("type must be expense or income")
        normalized["type"] = transaction_type
    if "category" in updates:
        category = str(updates["category"]).strip()
        if not category:
            raise ValueError("category cannot be empty")
        normalized["category"] = category[:24]
    if "note" in updates:
        note = str(updates["note"]).strip()
        if not note:
            raise ValueError("note cannot be empty")
        normalized["note"] = note[:80]
    if "date" in updates:
        transaction_date = str(updates["date"]).strip()
        try:
            datetime.strptime(transaction_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("date must use YYYY-MM-DD") from exc
        normalized["date"] = transaction_date
    if not normalized:
        raise ValueError("no editable fields supplied")

    with STATE_LOCK:
        state = _read_state()
        transaction = next((item for item in state["transactions"] if item["id"] == transaction_id), None)
        if transaction is None:
            return None
        transaction.update(normalized)
        _write_state(state)
        return transaction


def update_receipt(receipt_id: str, updates: dict) -> dict | None:
    """Update fields extracted from a receipt before it is linked to a transaction."""
    allowed = {"merchant", "amount", "category", "date"}
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported fields: {', '.join(sorted(unknown))}")
    normalized: dict = {}
    if "merchant" in updates:
        merchant = str(updates["merchant"]).strip()
        if not merchant:
            raise ValueError("merchant cannot be empty")
        normalized["merchant"] = merchant[:80]
    if "amount" in updates:
        amount = float(updates["amount"])
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("amount must be a positive number")
        normalized["amount"] = round(amount, 2)
    if "category" in updates:
        category = str(updates["category"]).strip()
        if not category:
            raise ValueError("category cannot be empty")
        normalized["category"] = category[:24]
    if "date" in updates:
        receipt_date = str(updates["date"]).strip()
        try:
            datetime.strptime(receipt_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("date must use YYYY-MM-DD") from exc
        normalized["date"] = receipt_date
    if not normalized:
        raise ValueError("no editable fields supplied")

    with STATE_LOCK:
        state = _read_state()
        receipt = next((item for item in state["receipts"] if item["id"] == receipt_id), None)
        if receipt is None:
            return None
        receipt.update(normalized)
        _write_state(state)
        return receipt


def delete_transaction(transaction_id: str) -> bool:
    with STATE_LOCK:
        state = _read_state()
        original_count = len(state["transactions"])
        state["transactions"] = [item for item in state["transactions"] if item["id"] != transaction_id]
        if len(state["transactions"]) == original_count:
            return False
        _write_state(state)
        return True


def create_receipt(payload: dict) -> dict:
    filename = str(payload.get("filename") or "receipt.bin")
    safe_name = re.sub(r"[^A-Za-z0-9_.-\u4e00-\u9fff]", "_", filename)[:80] or "receipt.bin"
    receipt_id = f"receipt-{uuid.uuid4().hex[:10]}"
    raw_data = base64.b64decode(payload.get("data", ""), validate=False)
    path = UPLOADS_DIR / f"{receipt_id}-{safe_name}"
    path.write_bytes(raw_data)
    text = f"{filename} {payload.get('hint', '')}"
    amount_match = re.search(r"([0-9][\d,]*(?:\.\d+)?)\s*元?", text)
    amount = _clean_amount(amount_match.group(1)) if amount_match else 268.0
    merchant = "盒马鲜生" if "盒马" in text else "待确认商户"
    receipt = {"id": receipt_id, "filename": filename, "merchant": merchant, "amount": amount, "date": date.today().isoformat(), "category": classify(text), "url": f"/uploads/{path.name}", "createdAt": _now_iso()}
    with STATE_LOCK:
        state = _read_state()
        state["receipts"].append(receipt)
        _write_state(state)
    return receipt


def dashboard(state: dict) -> dict:
    transactions = state["transactions"]
    if not transactions:
        return {"month": date.today().strftime("%Y-%m"), "spend": 0, "income": 0, "net": 0, "categories": {}, "trend": [], "recent": [], "priorAverage": 0, "increase": 0, "increasePercent": 0, "insight": "还没有交易，先用一句话记下第一笔账。"}
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
        trend.append({"month": month_key, "value": round(sum(tx["amount"] for tx in transactions if tx["date"].startswith(month_key) and tx["type"] == "expense"), 2)})
    prior_values = [item["value"] for item in trend[:-1] if item["value"] > 0]
    average = sum(prior_values) / len(prior_values) if prior_values else 0
    top_category, _ = max(categories.items(), key=lambda item: item[1], default=("其他", 0))
    increase = max(0, spend - average)
    if average and increase > 0:
        percent = round(increase / average * 100)
        insight = f"本月{top_category}消费占比最高；整体支出比过去平均增加约 {percent}%，主要来自{top_category}。"
    else:
        insight = f"本月{top_category}是主要支出类别，继续保持对高频消费的关注。"
    return {"month": focus_month, "spend": round(spend, 2), "income": round(income, 2), "net": round(income - spend, 2), "categories": categories, "trend": trend, "recent": sorted(transactions, key=lambda tx: tx["date"], reverse=True)[:8], "priorAverage": round(average, 2), "increase": round(increase, 2), "increasePercent": round(increase / average * 100) if average else 0, "insight": insight}


def insights_answer(state: dict, question: str) -> dict:
    data = dashboard(state)
    if "为什" in question or "花" in question or "支出" in question:
        categories = sorted(data["categories"].items(), key=lambda item: item[1], reverse=True)
        reasons = [{"category": category, "amount": amount} for category, amount in categories[:3]]
        comparison = f"比过去平均增加 {_money(data['increase'])}（约 {data['increasePercent']}%）" if data["increase"] > 0 else "没有高于过去平均"
        return {"answer": f"本月支出为 {_money(data['spend'])}，{comparison}。主要原因来自 {reasons[0]['category'] if reasons else '暂无分类'}，我把变化拆解如下。", "reasons": reasons, "suggestion": "优先减少高频、非计划支出，同时保留必要的生活与体验预算。", "data": data}
    return {"answer": "我可以解释本月支出、分类变化、现金流和可执行建议。试试问我：为什么这个月花这么多？", "reasons": [], "suggestion": "", "data": data}


class FinanceAgent:
    """Stable provider boundary; the MVP uses deterministic local behavior."""

    provider = os.getenv("AI_PROVIDER", "demo")

    def parse(self, text: str) -> dict:
        return parse_command(text)

    def answer(self, state: dict, question: str) -> dict:
        return insights_answer(state, question)


FINANCE_AGENT = FinanceAgent()


class Handler(BaseHTTPRequestHandler):
    server_version = "AIFinanceOS/1.0"

    def log_message(self, format: str, *args) -> None:
        print(f"{self.command} {self.path} - {format % args}")

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 8_000_000:
            raise ValueError("request too large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "service": "ai-finance-os"})
            return
        if path == "/api/state":
            state = _read_state()
            self._json(HTTPStatus.OK, {**state, "dashboard": dashboard(state)})
            return
        if path == "/api/insights":
            question = parse_qs(parsed.query).get("question", [""])[0]
            self._json(HTTPStatus.OK, FINANCE_AGENT.answer(_read_state(), question))
            return
        if path.startswith("/uploads/"):
            self._serve_upload(path.removeprefix("/uploads/"))
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            payload = self._read_json()
            if path == "/api/parse":
                self._json(HTTPStatus.OK, FINANCE_AGENT.parse(str(payload.get("text", ""))))
                return
            if path == "/api/transactions/batch":
                added = add_transactions({"transactions": payload.get("transactions", [])}, payload.get("ledgerName"))
                self._json(HTTPStatus.CREATED, {"transactions": added, "state": _read_state()})
                return
            if path == "/api/receipts":
                self._json(HTTPStatus.CREATED, {"receipt": create_receipt(payload)})
                return
            if path == "/api/receipts/apply":
                receipt_id = str(payload.get("receiptId", ""))
                state = _read_state()
                receipt = next((item for item in state["receipts"] if item["id"] == receipt_id), None)
                if not receipt:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "receipt not found"})
                    return
                added = add_transactions({"transactions": [{"amount": receipt["amount"], "type": "expense", "category": receipt["category"], "note": receipt["merchant"], "date": receipt["date"], "receiptId": receipt_id, "source": "receipt"}]}, payload.get("ledgerName"))
                self._json(HTTPStatus.CREATED, {"transactions": added})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            print(f"request failed: {type(exc).__name__}")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal server error"})

    def do_PATCH(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/receipts/"):
            receipt_id = path.removeprefix("/api/receipts/")
            if not receipt_id or "/" in receipt_id:
                self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
                return
            try:
                updated = update_receipt(receipt_id, self._read_json())
                if updated is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "receipt not found"})
                    return
                self._json(HTTPStatus.OK, {"receipt": updated})
            except (ValueError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                print(f"request failed: {type(exc).__name__}")
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal server error"})
            return
        transaction_id = path.removeprefix("/api/transactions/")
        if not transaction_id or "/" in transaction_id or transaction_id == "batch":
            self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            return
        try:
            updated = update_transaction(transaction_id, self._read_json())
            if updated is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "transaction not found"})
                return
            self._json(HTTPStatus.OK, {"transaction": updated})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            print(f"request failed: {type(exc).__name__}")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal server error"})

    def do_DELETE(self) -> None:
        path = unquote(urlparse(self.path).path)
        transaction_id = path.removeprefix("/api/transactions/")
        if not transaction_id or "/" in transaction_id or transaction_id == "batch":
            self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            return
        try:
            if not delete_transaction(transaction_id):
                self._json(HTTPStatus.NOT_FOUND, {"error": "transaction not found"})
                return
            self._json(HTTPStatus.OK, {"deleted": transaction_id})
        except Exception as exc:
            print(f"request failed: {type(exc).__name__}")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal server error"})

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        candidate = (WEB_DIR / relative).resolve()
        try:
            candidate.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return
        if not candidate.exists() or not candidate.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, candidate.read_bytes(), f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)

    def _serve_upload(self, name: str) -> None:
        candidate = (UPLOADS_DIR / name).resolve()
        try:
            candidate.relative_to(UPLOADS_DIR.resolve())
        except ValueError:
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return
        if not candidate.exists() or not candidate.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return
        self._send(HTTPStatus.OK, candidate.read_bytes(), mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")


def main() -> None:
    _ensure_data()
    server = ThreadingHTTPServer((HOST, PORT), Handler)

    def stop_server(_signum, _frame) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    print(f"AI Personal Finance OS listening on {HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
