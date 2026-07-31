from __future__ import annotations

from collections.abc import Iterable
from typing import Any


CATEGORY_TAXONOMY = {
    "expense": {
        "餐饮": ["正餐", "外卖", "早餐", "咖啡茶饮", "零食", "聚餐", "买菜", "其他"],
        "交通": ["公交地铁", "打车", "停车", "加油", "充电", "高速费", "维修保养", "其他"],
        "住房": ["房租", "房贷", "物业", "水电燃气", "宽带", "家居", "维修", "其他"],
        "购物": ["日用品", "服饰", "美妆", "数码", "家电", "母婴", "宠物", "其他"],
        "娱乐": ["游戏", "电影", "音乐", "演出", "会员订阅", "兴趣爱好", "其他"],
        "旅行": ["机票", "火车", "酒店", "景点", "当地交通", "旅行餐饮", "其他"],
        "医疗健康": ["挂号", "药品", "体检", "牙科", "健身", "保险", "其他"],
        "教育成长": ["课程", "书籍", "考试", "培训", "软件工具", "其他"],
        "人情社交": ["礼物", "红包", "请客", "婚礼", "孝敬家人", "其他"],
        "金融费用": ["手续费", "利息", "罚金", "税费", "汇兑损失", "其他"],
        "公益捐赠": ["公益", "捐款", "宗教", "其他"],
        "其他支出": ["其他"],
    },
    "income": {
        "工资收入": ["基本工资", "绩效", "奖金", "补贴", "加班费", "其他"],
        "经营收入": ["销售收入", "项目收入", "服务收入", "店铺收入", "其他"],
        "兼职收入": ["咨询", "稿费", "佣金", "临时工作", "其他"],
        "投资收益": ["利息", "分红", "基金收益", "股票收益", "数字资产", "其他"],
        "资产收入": ["房租收入", "资产出售", "二手交易", "其他"],
        "礼金赠与": ["红包", "礼金", "家庭转账", "其他"],
        "退款报销": ["消费退款", "公司报销", "保险理赔", "其他"],
        "其他收入": ["其他"],
    },
}

TAG_SUGGESTIONS = ["日常支出", "固定支出", "可报销", "家庭", "工作", "旅行", "微信", "支付宝", "有凭证"]

_RULES = (
    ("income", "退款报销", "保险理赔", ("保险理赔",)),
    ("income", "退款报销", "公司报销", ("报销",)),
    ("income", "退款报销", "消费退款", ("退款", "退货")),
    ("income", "工资收入", "奖金", ("奖金", "销冠", "年终奖")),
    ("income", "工资收入", "绩效", ("绩效",)),
    ("income", "工资收入", "补贴", ("补贴", "津贴")),
    ("income", "工资收入", "加班费", ("加班费",)),
    ("income", "工资收入", "基本工资", ("工资", "薪资", "薪酬")),
    ("income", "兼职收入", "咨询", ("咨询",)),
    ("income", "兼职收入", "稿费", ("稿费",)),
    ("income", "兼职收入", "佣金", ("佣金", "提成")),
    ("income", "投资收益", "分红", ("分红",)),
    ("income", "投资收益", "基金收益", ("基金收益",)),
    ("income", "投资收益", "股票收益", ("股票收益",)),
    ("income", "投资收益", "利息", ("利息",)),
    ("income", "资产收入", "房租收入", ("房租收入", "租金收入")),
    ("income", "资产收入", "二手交易", ("二手", "闲鱼")),
    ("income", "礼金赠与", "红包", ("红包",)),
    ("income", "礼金赠与", "礼金", ("礼金",)),
    ("income", "经营收入", "销售收入", ("销售收入", "货款")),
    ("income", "经营收入", "项目收入", ("项目收入",)),
    ("income", "经营收入", "服务收入", ("服务收入",)),
    ("expense", "旅行", "机票", ("机票", "航空")),
    ("expense", "旅行", "火车", ("火车票", "高铁票", "铁路")),
    ("expense", "旅行", "酒店", ("酒店", "宾馆", "民宿", "住宿")),
    ("expense", "旅行", "景点", ("景点", "门票", "旅行", "旅游")),
    ("expense", "交通", "停车", ("停车", "车场")),
    ("expense", "交通", "打车", ("打车", "滴滴", "出租车", "网约车")),
    ("expense", "交通", "公交地铁", ("地铁", "公交", "公共交通")),
    ("expense", "交通", "加油", ("加油", "汽油", "中石化", "中石油")),
    ("expense", "交通", "充电", ("充电桩", "汽车充电")),
    ("expense", "交通", "高速费", ("高速", "过路费", "ETC")),
    ("expense", "交通", "维修保养", ("保养", "修车", "洗车")),
    ("expense", "餐饮", "外卖", ("外卖", "饿了么", "美团外卖")),
    ("expense", "餐饮", "早餐", ("早餐",)),
    ("expense", "餐饮", "咖啡茶饮", ("咖啡", "茶饮", "奶茶", "瑞幸", "星巴克")),
    ("expense", "餐饮", "零食", ("零食", "小吃")),
    ("expense", "餐饮", "聚餐", ("聚餐", "请客",)),
    ("expense", "餐饮", "买菜", ("买菜", "菜场", "生鲜", "盒马")),
    ("expense", "餐饮", "正餐", ("餐饮", "美食", "餐厅", "饭店", "盒饭", "冒菜", "吃饭", "午饭", "午餐", "晚饭", "晚餐", "正餐")),
    ("expense", "住房", "房租", ("房租", "租房")),
    ("expense", "住房", "房贷", ("房贷",)),
    ("expense", "住房", "物业", ("物业",)),
    ("expense", "住房", "水电燃气", ("水费", "电费", "燃气", "煤气")),
    ("expense", "住房", "宽带", ("宽带", "网费")),
    ("expense", "住房", "家居", ("家居", "家具")),
    ("expense", "购物", "服饰", ("服饰", "衣服", "鞋", "优衣库")),
    ("expense", "购物", "美妆", ("美妆", "护肤", "化妆")),
    ("expense", "购物", "数码", ("数码", "手机", "电脑", "耳机")),
    ("expense", "购物", "家电", ("家电",)),
    ("expense", "购物", "母婴", ("母婴", "奶粉", "尿不湿")),
    ("expense", "购物", "宠物", ("宠物", "猫粮", "狗粮")),
    ("expense", "购物", "日用品", ("超市", "百货", "购物", "采购", "商场", "商品", "日用")),
    ("expense", "医疗健康", "挂号", ("挂号", "医院")),
    ("expense", "医疗健康", "药品", ("药房", "药店", "药品", "买药")),
    ("expense", "医疗健康", "体检", ("体检",)),
    ("expense", "医疗健康", "牙科", ("牙科", "口腔")),
    ("expense", "医疗健康", "健身", ("健身",)),
    ("expense", "医疗健康", "保险", ("保险",)),
    ("expense", "教育成长", "课程", ("课程", "网课")),
    ("expense", "教育成长", "书籍", ("书店", "图书", "买书", "书籍")),
    ("expense", "教育成长", "考试", ("考试", "报名费")),
    ("expense", "教育成长", "培训", ("培训", "教育")),
    ("expense", "教育成长", "软件工具", ("软件", "工具订阅")),
    ("expense", "娱乐", "游戏", ("游戏",)),
    ("expense", "娱乐", "电影", ("电影", "影院")),
    ("expense", "娱乐", "音乐", ("音乐",)),
    ("expense", "娱乐", "演出", ("演出", "展览")),
    ("expense", "娱乐", "会员订阅", ("会员", "订阅")),
    ("expense", "娱乐", "兴趣爱好", ("娱乐", "休闲", "酒吧", "游乐")),
    ("expense", "人情社交", "红包", ("红包", "转账")),
    ("expense", "人情社交", "礼物", ("礼物", "礼品")),
    ("expense", "人情社交", "婚礼", ("婚礼", "份子钱")),
    ("expense", "人情社交", "孝敬家人", ("孝敬", "给爸", "给妈")),
    ("expense", "金融费用", "手续费", ("手续费",)),
    ("expense", "金融费用", "罚金", ("罚款", "罚金")),
    ("expense", "金融费用", "税费", ("税费", "税款")),
    ("expense", "公益捐赠", "捐款", ("捐款", "捐赠")),
)

_LEGACY_ALIASES = {
    "expense": {
        "餐饮": ("餐饮", "其他"),
        "交通": ("交通", "其他"),
        "住房": ("住房", "其他"),
        "购物": ("购物", "其他"),
        "医疗": ("医疗健康", "其他"),
        "教育": ("教育成长", "其他"),
        "娱乐": ("娱乐", "其他"),
        "转账": ("人情社交", "其他"),
        "其他": ("其他支出", "其他"),
        "其他支出": ("其他支出", "其他"),
    },
    "income": {
        "奖金": ("工资收入", "奖金"),
        "工资": ("工资收入", "基本工资"),
        "收入": ("其他收入", "其他"),
        "转账": ("礼金赠与", "家庭转账"),
        "其他": ("其他收入", "其他"),
        "其他收入": ("其他收入", "其他"),
    },
}

_FIXED_EXPENSES = {
    ("住房", "房租"),
    ("住房", "房贷"),
    ("住房", "物业"),
    ("住房", "宽带"),
    ("娱乐", "会员订阅"),
    ("医疗健康", "保险"),
}


def normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    parts: Iterable[Any]
    if isinstance(value, str):
        parts = value.replace("，", ",").split(",")
    elif isinstance(value, Iterable):
        parts = value
    else:
        raise ValueError("tags must be a list or comma-separated string")
    result: list[str] = []
    for part in parts:
        tag = str(part).strip()
        if tag and tag not in result:
            result.append(tag[:16])
        if len(result) >= 12:
            break
    return result


def classify_transaction(
    text: str,
    transaction_type: str = "expense",
    *,
    existing_category: str | None = None,
    source: str | None = None,
    tags: Any = None,
    has_receipt: bool = False,
) -> dict[str, Any]:
    kind = transaction_type if transaction_type in CATEGORY_TAXONOMY else "expense"
    haystack = f"{existing_category or ''} {text}".lower()
    category = ""
    subcategory = ""
    for rule_type, primary, secondary, keywords in _RULES:
        if rule_type == kind and any(keyword.lower() in haystack for keyword in keywords):
            category, subcategory = primary, secondary
            break
    if not category:
        legacy = _LEGACY_ALIASES[kind].get((existing_category or "").strip())
        if legacy:
            category, subcategory = legacy
        elif existing_category and existing_category in CATEGORY_TAXONOMY[kind]:
            category, subcategory = existing_category, "其他"
        else:
            category = "其他收入" if kind == "income" else "其他支出"
            subcategory = "其他"

    normalized_tags = normalize_tags(tags)
    derived_tags = []
    if source == "wechat-import":
        derived_tags.append("微信")
    elif source == "alipay-import":
        derived_tags.append("支付宝")
    if has_receipt or source == "receipt":
        derived_tags.append("有凭证")
    if kind == "expense":
        derived_tags.append("固定支出" if (category, subcategory) in _FIXED_EXPENSES else "日常支出")
    for tag in derived_tags:
        if tag not in normalized_tags:
            normalized_tags.append(tag)
    return {"category": category, "subcategory": subcategory, "tags": normalized_tags}


def category_options() -> dict[str, Any]:
    return {"taxonomy": CATEGORY_TAXONOMY, "tagSuggestions": TAG_SUGGESTIONS}


def validate_classification(transaction_type: str, category: str, subcategory: str) -> None:
    categories = CATEGORY_TAXONOMY.get(transaction_type)
    if not categories or category not in categories:
        raise ValueError("分类与收支类型不匹配")
    if subcategory not in categories[category]:
        raise ValueError("二级分类与一级分类不匹配")
