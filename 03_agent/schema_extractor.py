"""从 MySQL 的 information_schema 提取表结构，生成精简 schema 文本供 prompt 注入。

设计决策（面试考点）：Schema 精简注入——不把全量 DDL 塞进 prompt，
而是按需只注入相关表，避免 token 浪费和噪音干扰。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_connection  # noqa: E402

# 手写的关系/口径说明，帮 LLM 少踩 Olist 的坑（比让模型自己猜更可靠）
# 注意：本库表名为短名（orders / order_items / order_payments ...）
RELATION_NOTES = """\
关键关系与口径（务必遵守）：
- orders 是订单主表，含 customer_id、下单时间 order_purchase_timestamp、签收时间 order_delivered_customer_date，但没有金额。
- 金额在两张表之一：order_items(price, freight_value 商品明细) 或 order_payments(payment_value 实付)。"成交额/GMV"默认用 payment_value。
- 一个订单在 order_items / order_payments 里可能有多行（多商品、多期支付）；统计"订单数"必须 COUNT(DISTINCT order_id)。
- 真实用户是 customers.customer_unique_id（同一个人可能有多个 customer_id，需经 customer_id 关联 orders）。
- 商品品类在 products.product_category_name（葡语），可 JOIN product_category_name_translation 取英文名。
- 评分在 order_reviews.review_score（订单粒度）。"""


def extract_schema(include_tables: list[str] | None = None) -> str:
    """返回形如 "表名(列 类型, ...)" 的 schema 文本。include_tables 为空则取全部。"""
    db = os.getenv("MYSQL_DATABASE", "olist_ecommerce")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name AS t, column_name AS c, data_type AS d
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position
                """,
                (db,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    tables: dict[str, list[str]] = {}
    for r in rows:
        if include_tables and r["t"] not in include_tables:
            continue
        tables.setdefault(r["t"], []).append(f"{r['c']} {r['d']}")

    lines = [f"{name}({', '.join(cols)})" for name, cols in tables.items()]
    return "数据库表结构：\n" + "\n".join(lines)


def build_schema_context(include_tables: list[str] | None = None) -> str:
    """schema + 关系说明，作为 prompt 的 schema 段。"""
    return extract_schema(include_tables) + "\n\n" + RELATION_NOTES


if __name__ == "__main__":
    from db import load_env

    load_env()
    print(build_schema_context())
