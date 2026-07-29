"""Authenticated FastAPI runtime for AI Personal Finance OS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import AuthContext, get_current_auth, get_redis, router as auth_router
from app.config import ROOT, settings
from app.database import get_db
from app.finance import (
    FINANCE_AGENT,
    add_transactions,
    apply_receipt,
    build_state,
    classify,
    create_ledger,
    create_receipt,
    dashboard,
    delete_transaction,
    insights_answer,
    parse_command,
    receipt_file,
    update_receipt,
    update_transaction,
)
from app.imports import (
    MAX_IMPORT_FILE_BYTES,
    import_bill_transactions,
    parse_bill,
    preview_bill,
)


WEB_DIR = ROOT / "web"
app = FastAPI(
    title="AI Personal Finance OS",
    version="2.0.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
)
app.include_router(auth_router)


class ParseRequest(BaseModel):
    text: str


class TransactionBatchRequest(BaseModel):
    ledgerName: str | None = None
    transactions: list[dict[str, Any]]


class ReceiptCreateRequest(BaseModel):
    filename: str
    data: str
    hint: str = ""


class ReceiptApplyRequest(BaseModel):
    receiptId: str
    ledgerName: str | None = None


class LedgerCreateRequest(BaseModel):
    name: str


class ImportCommitRequest(BaseModel):
    ledgerId: str
    transactions: list[dict[str, Any]]


class UpdateRequest(BaseModel):
    model_config = {"extra": "allow"}


@app.get("/health")
def health(
    response: Response,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict:
    checks = {"database": False, "redis": False}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
        checks["redis"] = bool(redis.ping())
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "service": "ai-finance-os",
        "checks": checks,
    }


@app.get("/api/state")
def state(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    return build_state(db, auth.user.id)


@app.post("/api/ledgers", status_code=201)
def ledger_create(
    body: LedgerCreateRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    try:
        ledger = create_ledger(db, auth.user.id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ledger": ledger, "state": build_state(db, auth.user.id)}


@app.post("/api/imports/preview")
async def import_preview(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    content = await file.read(MAX_IMPORT_FILE_BYTES + 1)
    try:
        parsed = parse_bill(file.filename or "账单", content)
        return preview_bill(db, auth.user.id, parsed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/imports/commit", status_code=201)
def import_commit(
    body: ImportCommitRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    try:
        imported, skipped = import_bill_transactions(
            db,
            auth.user.id,
            body.ledgerId,
            body.transactions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "importedCount": len(imported),
        "skippedCount": skipped,
        "state": build_state(db, auth.user.id),
    }


@app.get("/api/insights")
def insights(
    question: str = Query(default=""),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    return FINANCE_AGENT.answer(build_state(db, auth.user.id), question)


@app.post("/api/parse")
def parse(
    body: ParseRequest,
    _auth: AuthContext = Depends(get_current_auth),
) -> dict:
    return FINANCE_AGENT.parse(body.text)


@app.post("/api/transactions/batch", status_code=201)
def transactions_batch(
    body: TransactionBatchRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    try:
        rows = add_transactions(
            db,
            auth.user.id,
            {"transactions": body.transactions},
            body.ledgerName,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"transactions": rows, "state": build_state(db, auth.user.id)}


@app.patch("/api/transactions/{transaction_id}")
def transaction_update(
    transaction_id: str,
    body: dict,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    try:
        row = update_transaction(db, auth.user.id, transaction_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="交易不存在")
    return {"transaction": row}


@app.delete("/api/transactions/{transaction_id}")
def transaction_delete(
    transaction_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    if not delete_transaction(db, auth.user.id, transaction_id):
        raise HTTPException(status_code=404, detail="交易不存在")
    return {"deleted": transaction_id}


@app.post("/api/receipts", status_code=201)
def receipt_create(
    body: ReceiptCreateRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    try:
        row = create_receipt(db, auth.user.id, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"receipt": row}


@app.patch("/api/receipts/{receipt_id}")
def receipt_update(
    receipt_id: str,
    body: dict,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    try:
        row = update_receipt(db, auth.user.id, receipt_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="凭证不存在")
    return {"receipt": row}


@app.post("/api/receipts/apply")
def receipt_apply(
    body: ReceiptApplyRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    transaction, created = apply_receipt(
        db,
        auth.user.id,
        body.receiptId,
        body.ledgerName,
    )
    if not transaction:
        raise HTTPException(status_code=404, detail="凭证不存在")
    return {"transactions": [transaction], "created": created}


@app.get("/api/receipts/{receipt_id}/file")
def receipt_download(
    receipt_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> FileResponse:
    result = receipt_file(db, auth.user.id, receipt_id)
    if not result:
        raise HTTPException(status_code=404, detail="凭证不存在")
    path, mime_type, _original_name = result
    return FileResponse(
        path,
        media_type=mime_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/styles.css")
def styles() -> FileResponse:
    return FileResponse(WEB_DIR / "styles.css", media_type="text/css")


@app.get("/app.js")
def javascript() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js", media_type="application/javascript")


@app.get("/auth-utils.js")
def auth_utilities() -> FileResponse:
    return FileResponse(WEB_DIR / "auth-utils.js", media_type="application/javascript")


@app.get("/input-utils.js")
def input_utilities() -> FileResponse:
    return FileResponse(WEB_DIR / "input-utils.js", media_type="application/javascript")


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.server:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
