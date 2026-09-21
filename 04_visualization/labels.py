"""中文标签层（Phase 4 / 5 展示用）。

数据库列名是英文（`order_purchase_timestamp` 之类），值也常是编码（州代码 `SP`、
品类英文译名 `health_beauty`）。**可视化只面向业务读者**，所以在这里做最后一次翻译：
把列名和行值都换成中文，图表与表格统一从这里取标签。

设计要点：
- **只在展示层翻译**，不改 `sql_executor` 的结果 → 口径断言、评估脚本仍按原始列名工作。
- 三级回退：精确列名 → 关键词规则 → 保留原名。模型偶尔会造出没见过的列名
  （如 `avg_order_value`、`sales_2023`），关键词规则能兜住大部分，兜不住就原样显示
  （宁可不翻译，也不要译错）。
- 品类与州是**有限枚举**，直接内置对照表；月份做格式美化（`2017-01` → `2017 年 1 月`）。
"""
from __future__ import annotations

import re
from decimal import Decimal

# ---------------------------------------------------------------------------
# 一、列名 → 中文
# ---------------------------------------------------------------------------
COLUMN_LABELS: dict[str, str] = {
    # 维度
    "month": "月份",
    "year": "年份",
    "week": "周次",
    "date": "日期",
    # 时间戳列要显式登记：否则会被下面的关键词规则按 "order" 命中，
    # 把 `order_purchase_timestamp` 译成"订单量"（真实踩过的坑，见回归测试）
    "order_purchase_timestamp": "下单时间",
    "order_approved_at": "支付通过时间",
    "order_delivered_carrier_date": "交付承运商时间",
    "order_delivered_customer_date": "客户签收时间",
    "order_estimated_delivery_date": "预计送达时间",
    "shipping_limit_date": "发货截止时间",
    "review_creation_date": "评价创建时间",
    "review_answer_timestamp": "评价回复时间",
    "month_start": "月初",
    "first_order": "首单时间",
    "last_order": "末单时间",
    "state": "州",
    "customer_state": "州",
    "cust_state": "州",
    "city": "城市",
    "customer_city": "城市",
    "category": "商品品类",
    "product_category_name_english": "商品品类",
    "product_category_name": "商品品类",
    "product_id": "商品编号",
    "seller_id": "卖家编号",
    "customer_id": "客户编号",
    "customer_unique_id": "客户唯一编号",
    "order_id": "订单编号",
    "order_status": "订单状态",
    "entity_type": "榜单类型",
    "entity_id": "对象编号",
    "quintile": "消费分层",
    "quartile": "消费分层",
    "decile": "消费分层",
    "tier": "客户层级",
    "bucket": "消费分层",
    "rank": "排名",
    "rn": "排名",
    "payment_type": "支付方式",
    "review_score": "评分",
    # 指标
    "total_orders": "订单量",
    "orders": "订单量",
    "order_count": "订单量",
    "monthly_orders": "月度订单量",
    "delivered_orders": "已签收订单量",
    "items_sold": "售出件数",
    "customers": "客户数",
    "customer_count": "客户数",
    "total_customers": "客户总数",
    "repeat_customers": "复购客户数",
    "repurchase_customers": "复购客户数",
    "gmv": "成交额（元）",
    "total_gmv": "成交额（元）",
    "monthly_gmv": "月度成交额（元）",
    "monthly_sales": "月度销售额（元）",
    "total_payment": "成交额（元）",
    "payment_value": "支付金额（元）",
    "sales": "销售额（元）",
    "total_sales": "销售额（元）",
    "category_sales": "品类销售额（元）",
    "aov": "客单价（元）",
    "avg_order_value": "客单价（元）",
    "avg_spend": "人均消费（元）",
    "total_spend": "累计消费（元）",
    "avg_orders": "人均单数",
    "repurchase_rate": "复购率",
    "repurchase_customers": "复购客户数",
    "avg_score": "平均评分",
    "review_count": "评价数",
    "avg_delivery_days": "平均配送时长（天）",
    "days": "配送时长（天）",
    "duration": "配送时长（天）",
    "delivery_days": "配送时长（天）",
    "prev_sales": "上月销售额（元）",
    "prev_month_sales": "上月销售额（元）",
    "prev_orders": "上月订单量",
    "mom_change": "环比变化",
    "delta": "环比增减（元）",
    "share": "占比",
    "pct": "占比",
    "item_count": "商品数",
    "order_items": "商品件数",
    "freight_value": "运费（元）",
    "price": "商品售价（元）",
}

# 关键词规则（顺序敏感：越具体越靠前；泛化词放最后，避免 `monthly_orders` 只匹配到"月度"）
_COLUMN_RULES: list[tuple[str, str]] = [
    # 日期时间类必须排在 "order" 之前，否则 `order_*_timestamp` 会被译成"订单量"
    ("timestamp", "时间"),
    ("datetime", "时间"),
    ("_date", "日期"),
    ("_at", "时间"),
    ("repurchase", "复购率"),
    ("repeat_customer", "复购客户数"),
    ("avg_delivery", "平均配送时长（天）"),
    ("delivery_days", "配送时长（天）"),
    ("timediff", "时长（天）"),
    ("duration", "时长（天）"),
    ("avg_score", "平均评分"),
    ("review", "评价数"),
    ("customer_unique", "客户唯一编号"),
    ("seller", "卖家编号"),
    ("product", "商品编号"),
    ("category", "商品品类"),
    ("state", "州"),
    ("quintile", "消费分层"),
    ("gmv", "成交额（元）"),
    ("aov", "客单价（元）"),
    ("spend", "消费额（元）"),
    ("price", "售价（元）"),
    ("freight", "运费（元）"),
    ("prev", "上月"),
    ("delta", "环比增减（元）"),
    ("rank", "排名"),
    ("share", "占比"),
    ("rate", "比率"),
    ("pct", "占比"),
    ("score", "评分"),
    ("sales", "销售额（元）"),
    ("amount", "金额（元）"),
    ("revenue", "营收（元）"),
    ("payment", "支付金额（元）"),
    ("order", "订单量"),
    ("items", "件数"),
    ("customer", "客户数"),
    ("days", "天数"),
    ("month", "月份"),
    ("year", "年份"),
    ("monthly", "月度"),
]

# ---------------------------------------------------------------------------
# 二、行值 → 中文
# ---------------------------------------------------------------------------
# 巴西 27 个州 / 联邦区（Olist 客户与卖家所在地）
STATE_ZH: dict[str, str] = {
    "AC": "阿克里", "AL": "阿拉戈斯", "AM": "亚马孙", "AP": "阿马帕", "BA": "巴伊亚",
    "CE": "塞阿拉", "DF": "联邦区", "ES": "圣埃斯皮里图", "GO": "戈亚斯", "MA": "马拉尼昂",
    "MG": "米纳斯吉拉斯", "MS": "南马托格罗索", "MT": "马托格罗索", "PA": "帕拉",
    "PB": "帕拉伊巴", "PE": "伯南布哥", "PI": "皮奥伊", "PR": "巴拉那", "RJ": "里约热内卢",
    "RN": "北里奥格兰德", "RO": "朗多尼亚", "RR": "罗赖马", "RS": "南里奥格兰德",
    "SC": "圣卡塔琳娜", "SE": "塞尔希培", "SP": "圣保罗", "TO": "托坎廷斯",
}

# 品类：英文译名 → 中文（71 个，覆盖 product_category_name_translation 全表）
CATEGORY_ZH: dict[str, str] = {
    "agro_industry_and_commerce": "农牧与工商业",
    "air_conditioning": "空调",
    "art": "艺术品",
    "arts_and_craftmanship": "手工艺品",
    "audio": "音频设备",
    "auto": "汽车用品",
    "baby": "母婴用品",
    "bed_bath_table": "床品浴品桌布",
    "books_general_interest": "一般图书",
    "books_imported": "进口图书",
    "books_technical": "技术图书",
    "cds_dvds_musicals": "音乐 CD / DVD",
    "christmas_supplies": "圣诞用品",
    "cine_photo": "影像摄影",
    "computers": "电脑",
    "computers_accessories": "电脑配件",
    "consoles_games": "游戏主机",
    "construction_tools_construction": "建筑工具",
    "construction_tools_lights": "建筑照明",
    "construction_tools_safety": "建筑安全用品",
    "cool_stuff": "潮流杂货",
    "costruction_tools_garden": "园艺工具",
    "costruction_tools_tools": "五金工具",
    "diapers_and_hygiene": "纸尿裤与卫生用品",
    "drinks": "饮品",
    "dvds_blu_ray": "DVD 与蓝光",
    "electronics": "电子产品",
    "fashio_female_clothing": "女装",
    "fashion_bags_accessories": "箱包配饰",
    "fashion_childrens_clothes": "童装",
    "fashion_male_clothing": "男装",
    "fashion_shoes": "鞋履",
    "fashion_sport": "运动时尚",
    "fashion_underwear_beach": "内衣与沙滩装",
    "fixed_telephony": "固定电话",
    "flowers": "鲜花",
    "food": "食品",
    "food_drink": "食品饮料",
    "furniture_bedroom": "卧室家具",
    "furniture_decor": "家居装饰",
    "furniture_living_room": "客厅家具",
    "furniture_mattress_and_upholstery": "床垫与软包家具",
    "garden_tools": "园林工具",
    "health_beauty": "美妆个护",
    "home_appliances": "家用电器",
    "home_appliances_2": "家用电器（二类）",
    "home_comfort_2": "家居舒适（二类）",
    "home_confort": "家居舒适",
    "home_construction": "家装建材",
    "housewares": "家居日用",
    "industry_commerce_and_business": "工业与商贸",
    "kitchen_dining_laundry_garden_furniture": "厨卫与庭院家具",
    "la_cuisine": "厨房精品",
    "luggage_accessories": "行李箱与配件",
    "market_place": "平台自营市场",
    "music": "音乐",
    "musical_instruments": "乐器",
    "office_furniture": "办公家具",
    "party_supplies": "派对用品",
    "perfumery": "香水",
    "pet_shop": "宠物用品",
    "security_and_services": "安防与服务",
    "signaling_and_security": "标识与安防",
    "small_appliances": "小家电",
    "small_appliances_home_oven_and_coffee": "小家电（烤箱与咖啡）",
    "sports_leisure": "运动休闲",
    "stationery": "文具",
    "tablets_printing_image": "平板与打印影像",
    "telephony": "手机通讯",
    "toys": "玩具",
    "watches_gifts": "钟表礼品",
}

# 葡语原名 → 英文译名（翻译表缺失时基线用 COALESCE 回退葡语名，这里也要认）
PT_TO_EN: dict[str, str] = {
    "agro_industria_e_comercio": "agro_industry_and_commerce",
    "climatizacao": "air_conditioning",
    "artes": "art",
    "artes_e_artesanato": "arts_and_craftmanship",
    "audio": "audio",
    "automotivo": "auto",
    "bebes": "baby",
    "cama_mesa_banho": "bed_bath_table",
    "livros_interesse_geral": "books_general_interest",
    "livros_importados": "books_imported",
    "livros_tecnicos": "books_technical",
    "cds_dvds_musicais": "cds_dvds_musicals",
    "artigos_de_natal": "christmas_supplies",
    "cine_foto": "cine_photo",
    "pcs": "computers",
    "informatica_acessorios": "computers_accessories",
    "consoles_games": "consoles_games",
    "construcao_ferramentas_construcao": "construction_tools_construction",
    "construcao_ferramentas_iluminacao": "construction_tools_lights",
    "construcao_ferramentas_seguranca": "construction_tools_safety",
    "cool_stuff": "cool_stuff",
    "construcao_ferramentas_jardim": "costruction_tools_garden",
    "construcao_ferramentas_ferramentas": "costruction_tools_tools",
    "fraldas_higiene": "diapers_and_hygiene",
    "bebidas": "drinks",
    "dvds_blu_ray": "dvds_blu_ray",
    "eletronicos": "electronics",
    "fashion_roupa_feminina": "fashio_female_clothing",
    "fashion_bolsas_e_acessorios": "fashion_bags_accessories",
    "fashion_roupa_infanto_juvenil": "fashion_childrens_clothes",
    "fashion_roupa_masculina": "fashion_male_clothing",
    "fashion_calcados": "fashion_shoes",
    "fashion_esporte": "fashion_sport",
    "fashion_underwear_e_moda_praia": "fashion_underwear_beach",
    "telefonia_fixa": "fixed_telephony",
    "flores": "flowers",
    "alimentos": "food",
    "alimentos_bebidas": "food_drink",
    "moveis_quarto": "furniture_bedroom",
    "moveis_decoracao": "furniture_decor",
    "moveis_sala": "furniture_living_room",
    "moveis_colchao_e_estofado": "furniture_mattress_and_upholstery",
    "ferramentas_jardim": "garden_tools",
    "beleza_saude": "health_beauty",
    "eletrodomesticos": "home_appliances",
    "eletrodomesticos_2": "home_appliances_2",
    "casa_conforto_2": "home_comfort_2",
    "casa_conforto": "home_confort",
    "casa_construcao": "home_construction",
    "utilidades_domesticas": "housewares",
    "industria_comercio_e_negocios": "industry_commerce_and_business",
    "moveis_cozinha_area_de_servico_jantar_e_jardim": "kitchen_dining_laundry_garden_furniture",
    "la_cuisine": "la_cuisine",
    "malas_acessorios": "luggage_accessories",
    "market_place": "market_place",
    "musica": "music",
    "instrumentos_musicais": "musical_instruments",
    "moveis_escritorio": "office_furniture",
    "artigos_de_festas": "party_supplies",
    "perfumaria": "perfumery",
    "pet_shop": "pet_shop",
    "seguros_e_servicos": "security_and_services",
    "sinalizacao_e_seguranca": "signaling_and_security",
    "eletroportateis": "small_appliances",
    "portateis_casa_forno_e_cafe": "small_appliances_home_oven_and_coffee",
    "esporte_lazer": "sports_leisure",
    "papelaria": "stationery",
    "tablets_impressao_imagem": "tablets_printing_image",
    "telefonia": "telephony",
    "brinquedos": "toys",
    "relogios_presentes": "watches_gifts",
}

ENTITY_TYPE_ZH = {"product": "商品榜", "seller": "卖家榜", "category": "品类榜"}
ORDER_STATUS_ZH = {
    "delivered": "已签收", "shipped": "已发货", "canceled": "已取消",
    "invoiced": "已开票", "processing": "处理中", "unavailable": "无法供货",
    "approved": "已批准", "created": "已创建", "in_transit": "运输中",
}
PAYMENT_TYPE_ZH = {
    "credit_card": "信用卡", "boleto": "票据支付", "voucher": "代金券",
    "debit_card": "借记卡", "not_defined": "未定义",
}
QUINTILE_ZH = {
    1: "第 1 档（高消费）", 2: "第 2 档", 3: "第 3 档", 4: "第 4 档", 5: "第 5 档（低消费）",
}

# 哪些列要做"值翻译"（列名 → 映射表）
_VALUE_MAPS: dict[str, dict] = {
    "state": STATE_ZH,
    "customer_state": STATE_ZH,
    "cust_state": STATE_ZH,
    "shipping_state": STATE_ZH,
    "category": CATEGORY_ZH,
    "product_category_name_english": CATEGORY_ZH,
    "product_category_name": CATEGORY_ZH,
    "entity_type": ENTITY_TYPE_ZH,
    "order_status": ORDER_STATUS_ZH,
    "payment_type": PAYMENT_TYPE_ZH,
    "quintile": QUINTILE_ZH,
}

_YM = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")
MONEY_RE = re.compile(r"（元）$")


# ---------------------------------------------------------------------------
# 三、对外接口
# ---------------------------------------------------------------------------
def zh_column(col: str) -> str:
    """列名 → 中文显示名；认不出来时原样返回。"""
    if col is None:
        return ""
    key = str(col)
    if key in COLUMN_LABELS:
        return COLUMN_LABELS[key]
    low = key.lower()
    for frag, label in _COLUMN_RULES:
        if frag in low:
            return label
    return key


def zh_category(value: str) -> str:
    """品类名 → 中文（支持英文译名与葡语原名两种写法）。"""
    if value is None:
        return ""
    key = str(value).strip()
    if key in CATEGORY_ZH:
        return CATEGORY_ZH[key]
    en = PT_TO_EN.get(key)
    if en:
        return CATEGORY_ZH.get(en, key)
    return key


def zh_value(col: str, value):
    """行值 → 中文（仅对已知枚举列生效；其他值保持原样，避免误译）。"""
    if value is None:
        return value
    key = str(col).lower()
    if key in _VALUE_MAPS:
        m = _VALUE_MAPS[key]
        if type(value) is int and value in m:
            return m[value]
        s = str(value).strip()
        if s in m:
            return m[s]
        if key in ("category", "product_category_name_english", "product_category_name"):
            return zh_category(s)
    # 月份美化：2017-01 → 2017 年 1 月
    if key in ("month", "year_month") and isinstance(value, str):
        m = _YM.match(value)
        if m:
            return f"{m.group(1)} 年 {int(m.group(2))} 月"
    return value


def _is_num(v) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def display_rows(rows: list[dict], columns: list[str] | None = None) -> tuple[list[str], list[dict]]:
    """把结果集翻成中文列名 + 中文取值，返回 (中文列名列表, 新行列表)。

    列名冲突时保留原名（例如同时出现 `sales` 与 `category_sales`，中文都可能落到
    "销售额（元）" —— 那就给后一列改回原名，避免 DataFrame 出现重复列）。
    """
    if not rows:
        return [], []
    cols = list(columns or rows[0].keys())
    m = {c: zh_column(c) for c in cols}
    # 去重：重复的中文名回退成原名
    seen: set[str] = set()
    for c in cols:
        name = m[c]
        if name in seen:
            m[c] = c
        seen.add(m[c])
    out_cols = [m[c] for c in cols]
    out_rows = [{m[c]: zh_value(c, r.get(c)) for c in cols} for r in rows]
    return out_cols, out_rows


def display_frame(result: dict):
    """把 `sql_executor` 的结果转成 pandas DataFrame（中文列名 + 中文取值）。"""
    import pandas as pd

    cols, rows = display_rows(result.get("rows") or [], result.get("columns"))
    return pd.DataFrame(rows, columns=cols)
