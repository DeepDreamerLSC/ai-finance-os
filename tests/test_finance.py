import pytest

from app.finance import add_transactions, dashboard, insights_answer, parse_command
from app.models import User


def test_parse_single_expense():
    parsed = parse_command("刚刚停车112元，帮我记一下")
    assert parsed["transactions"][0]["amount"] == 112
    assert parsed["transactions"][0]["type"] == "expense"
    assert parsed["transactions"][0]["category"] == "交通"
    assert parsed["transactions"][0]["subcategory"] == "停车"


def test_parse_multiple_records_and_ledger():
    parsed = parse_command("创建2026账本，把停车费112元记录进去，再把4月份销冠奖金500元放进去")
    assert parsed["ledger"]["name"] == "2026 账本"
    assert len(parsed["transactions"]) == 2
    assert parsed["transactions"][1]["type"] == "income"
    assert parsed["transactions"][1]["category"] == "工资收入"
    assert parsed["transactions"][1]["subcategory"] == "奖金"


def test_parse_treats_chinese_comma_as_a_record_separator():
    parsed = parse_command("订单1785254553268，咖啡77元")
    assert parsed["transactions"][0]["amount"] == 77
    assert parsed["transactions"][0]["note"] == "咖啡"


def test_parse_supports_standard_thousands_separator():
    parsed = parse_command("房租4,200元")
    assert parsed["transactions"][0]["amount"] == 4200


@pytest.mark.parametrize(
    ("text", "expected_type", "expected_amount"),
    [
        ("今天午饭花了23块钱", "expense", 23),
        ("客户给我转了800块", "income", 800),
        ("工资到账一共12000元", "income", 12000),
        ("我给小王转了200元", "expense", 200),
        ("公司报销到账356.8元", "income", 356.8),
    ],
)
def test_parse_voice_style_amount_and_transaction_type(text, expected_type, expected_amount):
    transaction = parse_command(text)["transactions"][0]
    assert transaction["type"] == expected_type
    assert transaction["amount"] == expected_amount


def test_parse_voice_style_meal_gets_food_category():
    transaction = parse_command("今天午饭花了23块钱")["transactions"][0]
    assert transaction["category"] == "餐饮"
    assert transaction["subcategory"] == "正餐"


def test_dashboard_and_insight_are_data_driven():
    state = {
        "ledgers": [{"id": "ledger-1", "name": "2026 账本"}],
        "receipts": [],
        "transactions": [
            {"id": "a", "ledgerId": "ledger-1", "amount": 100, "type": "expense", "category": "餐饮", "note": "外卖", "date": "2026-06-02", "source": "manual"},
            {"id": "b", "ledgerId": "ledger-1", "amount": 220, "type": "expense", "category": "餐饮", "note": "外卖", "date": "2026-07-02", "source": "manual"},
            {"id": "c", "ledgerId": "ledger-1", "amount": 500, "type": "income", "category": "奖金", "note": "奖金", "date": "2026-07-03", "source": "manual"},
        ],
    }
    data = dashboard(state)
    assert data["spend"] == 220
    assert data["income"] == 500
    assert data["increase"] == 120
    answer = insights_answer(state, "为什么这个月花这么多？")
    assert answer["reasons"][0]["category"] == "餐饮"
    assert "增加" in answer["answer"]


def test_empty_dashboard_can_answer_without_transactions():
    answer = insights_answer({"ledgers": [], "transactions": [], "receipts": []}, "为什么这个月花这么多？")
    assert answer["data"]["increase"] == 0
    assert "没有高于过去平均" in answer["answer"]


def test_transaction_amount_above_database_precision_is_rejected(db_session):
    user = User(phone="13800138999")
    db_session.add(user)
    db_session.commit()
    with pytest.raises(ValueError, match="999999999999.99"):
        add_transactions(
            db_session,
            user.id,
            {
                "transactions": [
                    {
                        "amount": 1_000_000_000_000,
                        "type": "expense",
                        "category": "其他",
                        "note": "超出边界",
                        "date": "2026-07-28",
                    }
                ]
            },
        )
