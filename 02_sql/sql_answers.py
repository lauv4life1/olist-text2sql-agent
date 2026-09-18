"""Olist Text2SQL 项目 —— Phase 2 手写 SQL 基线。

作用：为 10 个业务问题各写一条"标准答案" SQL，并在 MySQL 上执行，
产出 baseline_results.json，作为 Phase 3 Text2SQL Agent 准确率评估的 ground truth。

数据库：olist_ecommerce（表名为短名：orders / order_items / order_payments ...）

用法：
    python 02_sql/sql_answers.py        # 读取项目根 .env 的连接信息

依赖：pymysql（见 requirements.txt）
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# 10 条手写 SQL（key = 题目 id）
# 口径统一：成交额以 order_payments.payment_value（实付）为准。
# 表名：orders / order_items / order_payments / customers / products /
#       sellers / order_reviews / product_category_name_translation
# ---------------------------------------------------------------------------
SQL_BY_ID: dict[int, str] = {
    # Q1 总订单数 / 总成交额 / 客单价
    # 坑：order_payments 一个订单可能多行（分期），订单数必须 COUNT(DISTINCT order_id)
    1: """
        SELECT
          COUNT(DISTINCT order_id)                                AS total_orders,
          ROUND(SUM(payment_value), 2)                            AS gmv,
          ROUND(SUM(payment_value) / COUNT(DISTINCT order_id), 2) AS aov
        FROM order_payments
    """,
    # Q2 每月销售趋势
    # 坑：时间戳在 orders、金额在 order_payments，必须 JOIN
    2: """
        SELECT
          DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')        AS month,
          ROUND(SUM(p.payment_value), 2)                          AS monthly_gmv,
          COUNT(DISTINCT o.order_id)                              AS monthly_orders
        FROM orders o
        JOIN order_payments p ON o.order_id = p.order_id
        GROUP BY month
        ORDER BY month
    """,
    # Q3 各品类销售额排名
    # 口径：销售额用 order_items.price（商品售价，不含运费，单表聚合无扇出）；
    #       品类名用翻译表英文译名，翻译缺失时回退葡语原名
    3: """
        SELECT
          COALESCE(t.product_category_name_english, p.product_category_name) AS category,
          ROUND(SUM(oi.price), 2)                                 AS category_sales,
          COUNT(*)                                                AS items_sold
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        LEFT JOIN product_category_name_translation t
               ON p.product_category_name = t.product_category_name
        GROUP BY category
        ORDER BY category_sales DESC
        LIMIT 10
    """,
    # Q4 复购率
    # 坑：真实用户用 customer_unique_id（经 customers 表关联）；先子查询再算占比
    4: """
        SELECT
          COUNT(*)                                                AS total_customers,
          SUM(order_count >= 2)                                   AS repeat_customers,
          ROUND(SUM(order_count >= 2) / COUNT(*), 4)              AS repurchase_rate
        FROM (
          SELECT c.customer_unique_id, COUNT(*) AS order_count
          FROM orders o
          JOIN customers c ON o.customer_id = c.customer_id
          GROUP BY c.customer_unique_id
        ) t
    """,
    # Q5 各州订单分布 + 配送天数（orders + customers + order_payments 三表）
    # 坑：JOIN order_payments 会让订单行翻倍 → 先按"订单粒度"算配送天数再聚合
    # 口径：配送天数统一用 TIMESTAMPDIFF(DAY)（与 Q8 一致，满 24 小时算一天）
    5: """
        WITH per_order AS (
          SELECT
            o.order_id,
            c.customer_state,
            TIMESTAMPDIFF(DAY, o.order_purchase_timestamp, o.order_delivered_customer_date) AS delivery_days
          FROM orders o
          JOIN customers c ON o.customer_id = c.customer_id
        ),
        order_gmv AS (
          SELECT order_id, SUM(payment_value) AS gmv
          FROM order_payments
          GROUP BY order_id
        )
        SELECT
          po.customer_state                                       AS state,
          COUNT(*)                                                AS orders,
          ROUND(SUM(g.gmv), 2)                                    AS gmv,
          ROUND(AVG(po.delivery_days), 1)                         AS avg_delivery_days
        FROM per_order po
        JOIN order_gmv g ON po.order_id = g.order_id
        GROUP BY po.customer_state
        ORDER BY orders DESC
    """,
    # Q6 评分最高的产品 + 卖家（两条独立榜单）
    # 口径：题面问"产品和卖家分别是哪些" → 拆成产品榜与卖家榜各 Top10；
    #       HAVING COUNT(*) >= 20 过滤样本量，避免"1 条 5 星"刷榜
    6: """
        WITH product_scores AS (
          SELECT
            oi.product_id,
            ROUND(AVG(r.review_score), 2)                           AS avg_score,
            COUNT(*)                                                AS review_count
          FROM order_items oi
          JOIN order_reviews r ON oi.order_id = r.order_id
          GROUP BY oi.product_id
          HAVING COUNT(*) >= 20
          ORDER BY avg_score DESC, review_count DESC
          LIMIT 10
        ),
        seller_scores AS (
          SELECT
            oi.seller_id,
            ROUND(AVG(r.review_score), 2)                           AS avg_score,
            COUNT(*)                                                AS review_count
          FROM order_items oi
          JOIN order_reviews r ON oi.order_id = r.order_id
          GROUP BY oi.seller_id
          HAVING COUNT(*) >= 20
          ORDER BY avg_score DESC, review_count DESC
          LIMIT 10
        )
        SELECT 'product' AS entity_type, product_id AS entity_id, avg_score, review_count
        FROM product_scores
        UNION ALL
        SELECT 'seller'  AS entity_type, seller_id  AS entity_id, avg_score, review_count
        FROM seller_scores
        ORDER BY entity_type, avg_score DESC, review_count DESC
    """,
    # Q7 Top5 卖家月销售趋势（CTE 先取 Top5，再按月聚合 = 两个聚合层级）
    7: """
        WITH top5 AS (
          SELECT seller_id
          FROM order_items
          GROUP BY seller_id
          ORDER BY SUM(price) DESC
          LIMIT 5
        )
        SELECT
          oi.seller_id                                            AS seller_id,
          DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')        AS month,
          ROUND(SUM(oi.price), 2)                                 AS monthly_sales
        FROM order_items oi
        JOIN top5 t ON oi.seller_id = t.seller_id
        JOIN orders o ON oi.order_id = o.order_id
        GROUP BY oi.seller_id, month
        ORDER BY oi.seller_id, month
    """,
    # Q8 下单到签收平均时长（TIMESTAMPDIFF，按月趋势）
    8: """
        SELECT
          DATE_FORMAT(order_purchase_timestamp, '%Y-%m')          AS month,
          COUNT(*)                                                AS delivered_orders,
          ROUND(AVG(TIMESTAMPDIFF(DAY, order_purchase_timestamp, order_delivered_customer_date)), 1) AS avg_delivery_days
        FROM orders
        WHERE order_delivered_customer_date IS NOT NULL
        GROUP BY month
        ORDER BY month
    """,
    # Q9 销售额环比下降的月份（LAG 取上一月）
    9: """
        WITH monthly AS (
          SELECT
            DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')      AS month,
            SUM(p.payment_value)                                  AS sales
          FROM orders o
          JOIN order_payments p ON o.order_id = p.order_id
          GROUP BY month
        )
        SELECT
          month,
          ROUND(sales, 2)                                         AS sales,
          ROUND(prev_sales, 2)                                    AS prev_sales,
          ROUND(sales - prev_sales, 2)                            AS delta
        FROM (
          SELECT month, sales,
                 LAG(sales) OVER (ORDER BY month) AS prev_sales
          FROM monthly
        ) t
        WHERE sales < prev_sales
        ORDER BY month
    """,
    # Q10 高价值客户画像（CTE + NTILE 五分位，quintile=1 为最高消费组）
    10: """
        WITH spend AS (
          SELECT
            c.customer_unique_id,
            SUM(p.payment_value)                                  AS total_spend,
            COUNT(DISTINCT o.order_id)                            AS orders
          FROM orders o
          JOIN customers c       ON o.customer_id = c.customer_id
          JOIN order_payments p  ON o.order_id = p.order_id
          GROUP BY c.customer_unique_id
        ),
        ranked AS (
          SELECT *, NTILE(5) OVER (ORDER BY total_spend DESC) AS quintile
          FROM spend
        )
        SELECT
          quintile,
          COUNT(*)                                                AS customers,
          ROUND(AVG(total_spend), 2)                              AS avg_spend,
          ROUND(AVG(orders), 2)                                   AS avg_orders
        FROM ranked
        GROUP BY quintile
        ORDER BY quintile
    """,
}


def _load_dotenv() -> None:
    """极简 .env 读取（避免额外依赖）。"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def get_connection():
    import pymysql  # 延迟导入，便于未安装时给出友好提示

    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "olist_ecommerce"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        read_timeout=60,
    )


def run_all() -> dict:
    """执行全部 10 条 SQL，返回结果字典并写入 baseline_results.json。"""
    questions = {}
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("questions", ROOT / "01_data" / "questions.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        questions = {q["id"]: q for q in mod.QUESTIONS}
    except Exception:  # noqa: BLE001
        pass

    conn = get_connection()
    results: dict[str, dict] = {}
    try:
        with conn.cursor() as cur:
            for qid, sql in SQL_BY_ID.items():
                meta = questions.get(qid, {})
                try:
                    cur.execute(sql)
                    rows = cur.fetchall()
                    results[str(qid)] = {
                        "id": qid,
                        "title": meta.get("title", ""),
                        "question": meta.get("question", ""),
                        "skill": meta.get("skill", ""),
                        "sql": " ".join(sql.split()),
                        "row_count": len(rows),
                        "rows": rows,
                        "status": "ok",
                    }
                    print(f"[Q{qid:>2}] OK  {len(rows)} 行  {meta.get('title','')}")
                except Exception as exc:  # noqa: BLE001
                    results[str(qid)] = {
                        "id": qid,
                        "title": meta.get("title", ""),
                        "sql": " ".join(sql.split()),
                        "status": "error",
                        "error": str(exc),
                    }
                    print(f"[Q{qid:>2}] ERR {exc}")
    finally:
        conn.close()

    out_path = ROOT / "02_sql" / "baseline_results.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    print(f"\n完成：{ok}/{len(SQL_BY_ID)} 条成功，结果已写入 {out_path}")
    return results


if __name__ == "__main__":
    _load_dotenv()
    run_all()
