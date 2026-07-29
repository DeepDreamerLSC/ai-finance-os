import pytest

from app.categories import classify_transaction, normalize_tags, validate_classification


def test_expense_classification_has_primary_secondary_and_derived_tags():
    result = classify_transaction("滴滴出行打车", "expense", source="wechat-import")
    assert result == {
        "category": "交通",
        "subcategory": "打车",
        "tags": ["微信", "日常支出"],
    }


def test_income_legacy_category_is_upgraded():
    result = classify_transaction("四月份销冠奖金", "income", existing_category="奖金")
    assert result["category"] == "工资收入"
    assert result["subcategory"] == "奖金"


def test_manual_tags_are_normalized_without_duplicates():
    assert normalize_tags("工作，可报销, 工作") == ["工作", "可报销"]


def test_classification_pair_must_match_transaction_type():
    with pytest.raises(ValueError, match="分类与收支类型不匹配"):
        validate_classification("income", "交通", "停车")
