from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


MONEY_QUANTUM = Decimal("0.01")
MAX_MONEY = Decimal("999999999999.99")


def money_decimal(value: Any, *, field: str = "金额") -> Decimal:
    """Parse a monetary value without binary-float rounding."""
    text = str(value).strip().replace(",", "").replace("¥", "").replace("￥", "")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field}格式不正确") from exc
    if not amount.is_finite() or amount <= 0 or amount > MAX_MONEY:
        raise ValueError(f"{field}必须在 0.01 到 999999999999.99 元之间")
    if amount.as_tuple().exponent < -2:
        raise ValueError(f"{field}最多保留两位小数")
    return amount.quantize(MONEY_QUANTUM)

