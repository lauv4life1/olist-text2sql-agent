# -*- coding: utf-8 -*-
"""生成 BI 层（Tableau / Power BI 通用）的预聚合宽表。

设计原则（与 03_agent/CALIBER.md 一致）：

1. **先按 order_id 预聚合支付**，再 JOIN —— 直接 JOIN `order_payments` 会因"一单多付"
   把金额与时长按行加权（CALIBER C21 扇出）。
2. **口径与 Agent 层同源**：本脚本跑完自带守恒断言，任何一项不成立就直接失败退出，
   避免 BI 层与 Agent 层给出两个不同的 GMV。
3. **出口即中文**：列名与取值直接复用 `04_visualization/labels.py`（同一套翻译规则），
   Tableau 里不需要再手工建别名。

产物：`06_bi/exports/*.csv`（UTF-8 with BOM，Excel 与 Tableau 都能直接读）。

用法：
    python 06_bi/make_bi_exports.py
"""

from __future__ import annotations

import csv
import os
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "03_agent"), os.path.join(ROOT, "04_visualization")):
    if p not in sys.path:
        sys.path.insert(0, p)

from db import get_connection  # noqa: E402
from labels import zh_value  # noqa: E402

OUT_DIR = os.path.join(ROOT, "06_bi", "exports")

# ---------------------------------------------------------------------------
# 守恒参照值 —— 与 CALIBER.md / caliber_check.py 同源，改动需同步三处
# ---------------------------------------------------------------------------
TOTAL_ORDERS = 99440                 # C19：各州订单数之和 = 平台总订单数（只算有支付记录的订单）
TOTAL_GMV = Decimal("16008872.12")   # C1：SUM(order_payments.payment_value)
TOTAL_PRICE = Decimal("13591643.70")  # C15：SUM(order_items.price) —— 另一套金额口径，不可混用
TOTAL_CUSTOMERS = 96095              # C14：有支付记录订单覆盖的 customer_unique_id 数
SEG_SIZE = 19219                     # C14：NTILE(5) 每档人数（5 × 19219 = 96095）

PAY_CTE = """
pay AS (
    SELECT order_id, SUM(payment_value) AS gmv
    FROM order_payments
    GROUP BY order_id
)
"""

# ---------------------------------------------------------------------------
# 四张宽表的 SQL（全部预聚合到"一行 = 一个维度成员"）
# ---------------------------------------------------------------------------
QUERIES = {
    # 1) 州维度：订单数 / 成交额 / 客单价 / 平均配送天数
    "dim_state": (
        "州维度",
        """
        WITH {pay_cte}
        , base AS (
            SELECT c.customer_state AS state,
                   o.order_id AS order_id,
                   pay.gmv AS gmv,
                   TIMESTAMPDIFF(DAY, o.order_purchase_timestamp, o.order_delivered_customer_date) AS days
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            JOIN pay ON pay.order_id = o.order_id
        )
        SELECT state,
               COUNT(DISTINCT order_id) AS orders,
               SUM(gmv) AS gmv,
               SUM(gmv) / COUNT(DISTINCT order_id) AS aov,
               AVG(days) AS avg_days
        FROM base
        GROUP BY state
        """.format(pay_cte=PAY_CTE),
    ),
    # 2) 品类维度：销售额口径用 order_items.price（C15），与成交额（payment_value）不是一回事
    "dim_category": (
        "品类维度",
        """
        SELECT COALESCE(t.product_category_name_english, p.product_category_name) AS category,
               COUNT(*) AS items,
               SUM(oi.price) AS price_sum,
               COUNT(DISTINCT oi.order_id) AS orders
        FROM order_items oi
        JOIN products p ON p.product_id = oi.product_id
        LEFT JOIN product_category_name_translation t
               ON t.product_category_name = p.product_category_name
        GROUP BY COALESCE(t.product_category_name_english, p.product_category_name)
        """,
    ),
    # 3) 月度趋势：按月必须用 order_purchase_timestamp（禁用 shipping_limit_date）
    "fct_monthly": (
        "月度趋势",
        """
        WITH {pay_cte}
        SELECT DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS ym,
               COUNT(DISTINCT o.order_id) AS orders,
               SUM(pay.gmv) AS gmv,
               SUM(pay.gmv) / COUNT(DISTINCT o.order_id) AS aov
        FROM orders o
        JOIN pay ON pay.order_id = o.order_id
        GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')
        ORDER BY ym
        """.format(pay_cte=PAY_CTE),
    ),
    # 4) 客户分层：真实用户 = customer_unique_id；总体 = 有支付记录覆盖的客户（C10 / C14 / C22）
    "dim_customer_segment": (
        "客户分层",
        """
        WITH {pay_cte}
        , cust AS (
            SELECT c.customer_unique_id AS uid,
                   COUNT(DISTINCT o.order_id) AS orders,
                   SUM(pay.gmv) AS spend
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            JOIN pay ON pay.order_id = o.order_id
            GROUP BY c.customer_unique_id
        )
        , seg AS (
            SELECT uid, orders, spend, NTILE(5) OVER (ORDER BY spend DESC) AS q
            FROM cust
        )
        SELECT q AS quintile,
               COUNT(*) AS customers,
               SUM(spend) / COUNT(*) AS spend_per_capita,
               SUM(orders) / COUNT(*) AS orders_per_capita
        FROM seg
        GROUP BY q
        ORDER BY q
        """.format(pay_cte=PAY_CTE),
    ),
}

# 输出列：中文表头 + 取值格式化（None = 不做值翻译）
MONEY = "money"
ONE_DEC = "one_dec"
TWO_DEC = "two_dec"


def fmt(v, kind):
    if v is None:
        return ""
    if kind == MONEY or kind == TWO_DEC:
        return f"{Decimal(str(v)):.2f}"
    if kind == ONE_DEC:
        return f"{Decimal(str(v)):.1f}"
    return v


def build_rows(name, rows):
    """把查询结果（DictCursor 的 dict 行）转成中文表头 + 中文数据行 + 供断言用的合计。"""
    if name == "dim_state":
        header = ["州代码", "州", "订单数", "成交额（元）", "客单价（元）", "平均配送天数"]
        out = []
        for r in sorted(rows, key=lambda r: -float(r["gmv"] or 0)):
            out.append([r["state"], zh_value("state", r["state"]), int(r["orders"]),
                        fmt(r["gmv"], MONEY), fmt(r["aov"], MONEY), fmt(r["avg_days"], ONE_DEC)])
        return {"header": header, "rows": out,
                "orders_sum": int(sum(r["orders"] for r in rows)),
                "money_sum": float(sum(r["gmv"] or 0 for r in rows))}

    if name == "dim_category":
        header = ["品类", "商品件数", "销售额（元）", "订单数"]
        out = []
        for r in sorted(rows, key=lambda r: -float(r["price_sum"] or 0)):
            out.append([zh_value("category", r["category"]) or "（未分类）", int(r["items"]),
                        fmt(r["price_sum"], MONEY), int(r["orders"])])
        return {"header": header, "rows": out,
                "money_sum": float(sum(r["price_sum"] or 0 for r in rows))}

    if name == "fct_monthly":
        header = ["月份", "月份显示", "订单数", "成交额（元）", "客单价（元）"]
        out = []
        for r in rows:
            out.append([r["ym"], zh_value("month", r["ym"]), int(r["orders"]),
                        fmt(r["gmv"], MONEY), fmt(r["aov"], MONEY)])
        return {"header": header, "rows": out,
                "orders_sum": int(sum(r["orders"] for r in rows)),
                "money_sum": float(sum(r["gmv"] or 0 for r in rows))}

    if name == "dim_customer_segment":
        header = ["消费分层", "客户数", "人均消费（元）", "人均订单数"]
        out = []
        for r in sorted(rows, key=lambda r: int(r["quintile"])):
            out.append([zh_value("quintile", int(r["quintile"])), int(r["customers"]),
                        fmt(r["spend_per_capita"], MONEY), fmt(r["orders_per_capita"], TWO_DEC)])
        return {"header": header, "rows": out,
                "seg_sizes": [int(r["customers"]) for r in rows]}

    raise KeyError(name)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    conn = get_connection(readonly=True)
    try:
        cur = conn.cursor()
        written = []
        sums = {}
        for name, (title, sql) in QUERIES.items():
            cur.execute(sql)
            rows = cur.fetchall()
            res = build_rows(name, rows)
            header, data = res["header"], res["rows"]
            path = os.path.join(OUT_DIR, name + ".csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(data)
            written.append((name, title, len(data), path))
            if "orders_sum" in res:
                sums[name + "_orders"] = res["orders_sum"]
            if "money_sum" in res:
                sums[name + "_money"] = Decimal(str(res["money_sum"]))
            if "seg_sizes" in res:
                sums["seg_sizes"] = res["seg_sizes"]
    finally:
        conn.close()

    print("=" * 72)
    print("BI 层宽表生成完成")
    print("=" * 72)
    for name, title, n, path in written:
        print(f"  {title:<8} {name}.csv   {n:>3} 行")
    print("-" * 72)

    # ---- 守恒断言：不通过就退出码 1（与 caliber_check 一致的风格）----
    checks = [
        ("C19 各州订单数之和 = 平台总订单数", sums.get("dim_state_orders"), TOTAL_ORDERS),
        ("C1  各州成交额之和 = 平台成交额", sums.get("dim_state_money", Decimal(0)), TOTAL_GMV),
        ("C15 各品类销售额之和 = 商品售价合计", sums.get("dim_category_money", Decimal(0)), TOTAL_PRICE),
        ("C19 各月订单数之和 = 平台总订单数", sums.get("fct_monthly_orders"), TOTAL_ORDERS),
        ("C1  各月成交额之和 = 平台成交额", sums.get("fct_monthly_money", Decimal(0)), TOTAL_GMV),
        ("C14 各档客户数之和 = 高价值客户总体", sum(sums.get("seg_sizes") or []), TOTAL_CUSTOMERS),
    ]
    failed = 0
    for label, got, want in checks:
        ok = got is not None and abs(Decimal(str(got)) - Decimal(str(want))) < Decimal("0.01")
        print(f"  [{'OK  ' if ok else 'FAIL'}] {label}: got={got} want={want}")
        failed += 0 if ok else 1
    seg = sums.get("seg_sizes") or []
    if seg and not all(x == SEG_SIZE for x in seg):
        print(f"  [FAIL] C14 每档人数应均为 {SEG_SIZE}，实际 {seg}")
        failed += 1

    # ---- 形状断言：守恒式抓不到"粒度错了" ----
    # 教训：DATE_FORMAT 写成字面量时 25 个月被压成 1 行，但合计依旧等于总量，
    # 上面 6 条守恒断言全部通过 —— 所以粒度必须单独断言。
    shape_expect = {
        "dim_state": (25, 30),           # 27 个州
        "dim_category": (60, 90),        # 71 个品类 + 少量未翻译回退
        "fct_monthly": (20, 30),         # 2016-09 ~ 2018-10 共 25 个月
        "dim_customer_segment": (5, 5),  # NTILE(5) 固定 5 档
    }
    for name, title, n, _ in written:
        lo, hi = shape_expect.get(name, (1, 10 ** 6))
        ok = lo <= n <= hi
        print(f"  [{'OK  ' if ok else 'FAIL'}] {title}行数在 [{lo}, {hi}] 内: 实际 {n}")
        failed += 0 if ok else 1
    print("-" * 72)
    print(f"结果：{'全部通过' if failed == 0 else str(failed) + ' 项未通过'}")
    print(f"输出目录：{OUT_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
