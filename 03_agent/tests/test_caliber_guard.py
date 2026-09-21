"""第 4 层口径断言（caliber_guard）的回归测试。

断言表里注入的全是**本项目真实踩过的坑**（来自三模型评估的失败样本），
确保这些错误一旦重现就会被抓住、且修正提示能定位到具体口径：

- C1  : 用 orders 单表数订单 → 99,441（应为 99,440）
- C14 : 高价值客户总体被过滤成"已签收/有评价" → 18,672 / 21,145
- C16 : JOIN order_payments 后 AVG(TIMESTAMPDIFF) → 时长被一单多付扇出加权（DeepSeek Q5）
- C19 : orders JOIN customers 数订单 → 各州订单数之和 99,441
- C20 : 按州统计漏输出 GMV / 时长列

以及"不许误报"的正例：基线级正确结果、按月 24 行结果都必须 0 违规。

运行： python -m unittest discover -s 03_agent/tests -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "03_agent"))

from caliber_guard import (  # noqa: E402
    HIGH_VALUE_CUSTOMERS,
    TOTAL_GMV,
    TOTAL_ORDERS,
    check,
    format_feedback,
)


def res(columns, rows, sql=""):
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


Q5_OK_ROWS = [
    {"state": "SP", "orders": 41745, "gmv": 5998226.96, "avg_delivery_days": 8.3},
    {"state": "RJ", "orders": 57695, "gmv": 10010645.16, "avg_delivery_days": 14.8},
]
Q5_COLS = ["state", "orders", "gmv", "avg_delivery_days"]

Q10_OK_ROWS = [
    {"quintile": q, "customers": 19219, "avg_spend": s, "avg_orders": 1.1}
    for q, s in zip(range(1, 6), [447.89, 165.83, 108.82, 70.69, 39.74])
]
Q10_COLS = ["quintile", "customers", "avg_spend", "avg_orders"]

# DeepSeek 在 Q5 上的真实错误：orders JOIN customers JOIN order_payments，
# 没有按 order_id 预聚合 → SUM(payment_value) 与 AVG(时长) 都被扇出放大
Q5_FANOUT_SQL = (
    "SELECT c.customer_state AS state, COUNT(DISTINCT o.order_id) AS orders, "
    "ROUND(SUM(p.payment_value), 2) AS gmv, "
    "ROUND(AVG(TIMESTAMPDIFF(DAY, o.order_purchase_timestamp, o.order_delivered_customer_date)), 1) "
    "AS avg_delivery_days "
    "FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
    "JOIN order_payments p ON o.order_id = p.order_id "
    "GROUP BY c.customer_state"
)

# 正确写法：先在子查询里按 order_id 预聚合，再在订单粒度求 AVG
Q5_PREAGG_SQL = (
    "SELECT t.state, COUNT(*) AS orders, ROUND(SUM(t.gmv), 2) AS gmv, "
    "ROUND(AVG(t.days), 1) AS avg_delivery_days FROM ("
    "SELECT o.order_id, c.customer_state AS state, SUM(p.payment_value) AS gmv, "
    "TIMESTAMPDIFF(DAY, o.order_purchase_timestamp, o.order_delivered_customer_date) AS days "
    "FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
    "JOIN order_payments p ON o.order_id = p.order_id "
    "GROUP BY o.order_id, c.customer_state) t GROUP BY t.state"
)


class TestGlobalTotals(unittest.TestCase):
    """C1：单行全局总量守恒。"""

    def test_correct_totals_pass(self):
        r = res(["total_orders", "gmv", "aov"],
                [{"total_orders": TOTAL_ORDERS, "gmv": TOTAL_GMV, "aov": 160.99}])
        self.assertEqual(check("q", "", r), [])

    def test_orders_table_denominator_caught(self):
        """把 orders 表 99,441 行当成订单数 —— 最经典的差 1 单。"""
        r = res(["total_orders", "gmv", "aov"],
                [{"total_orders": 99441, "gmv": TOTAL_GMV, "aov": 160.99}])
        v = check("q", "", r)
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].caliber, "C1")
        self.assertIn("99441", v[0].message)
        self.assertIn("99440", v[0].message)

    def test_item_price_as_gmv_caught(self):
        r = res(["total_orders", "gmv"],
                [{"total_orders": TOTAL_ORDERS, "gmv": 13_591_643.70}])
        v = check("q", "", r)
        self.assertEqual([x.caliber for x in v], ["C1"])
        self.assertIn("order_payments.payment_value", v[0].message)


class TestStateCaliber(unittest.TestCase):
    """C19 / C20：按州统计的两条守恒式 + 三列齐全。"""

    def test_correct_state_result_passes(self):
        self.assertEqual(check("q", "", res(Q5_COLS, Q5_OK_ROWS)), [])

    def test_order_count_drift_caught(self):
        rows = [dict(r) for r in Q5_OK_ROWS]
        rows[0]["orders"] += 1  # 41,746 —— 历史真实漂移
        v = check("q", "", res(Q5_COLS, rows))
        self.assertEqual([x.caliber for x in v], ["C19"])
        self.assertIn("+1", v[0].message)

    def test_gmv_fanout_caught(self):
        rows = [dict(r) for r in Q5_OK_ROWS]
        rows[1]["gmv"] = 12_000_000.00  # 被扇出放大的 GMV
        v = check("q", "", res(Q5_COLS, rows))
        self.assertEqual([x.caliber for x in v], ["C19"])
        self.assertIn("扇出", v[0].message)

    def test_missing_duration_column_caught(self):
        """C20 是**问题驱动**的：问"分布/配送天数"时必须给出对应列。"""
        cols = ["state", "orders", "gmv"]
        rows = [{"state": "SP", "orders": 41745, "gmv": 5998226.96},
                {"state": "RJ", "orders": 57695, "gmv": 10010645.16}]
        q = "订单在各州的分布如何？每个州的平均配送天数是多少？"
        v = check(q, "", res(cols, rows))
        self.assertEqual([x.caliber for x in v], ["C20"])
        self.assertIn("平均配送时长", v[0].message)

    def test_c20_does_not_demand_unasked_columns(self):
        """不能"只要出现州列就要求三列" —— 那会和 prompt 的
        「只输出回答该问题所必需的列」直接冲突，把模型逼着加列（E2E 实测发生过）。"""
        cols = ["state", "orders"]
        rows = [{"state": "SP", "orders": 41745}, {"state": "RJ", "orders": 57695}]
        # 问"每个州有多少订单" → 只要求订单数，不该追要 GMV / 配送时长
        self.assertEqual(check("每个州有多少订单？", "", res(cols, rows)), [])
        # 问"各州销售额" → 只要求金额列（SQL 用 price 口径，金额归 C15 守恒）
        self.assertEqual(
            check("各州销售额是多少？",
                  "SELECT c.customer_state AS state, SUM(oi.price) AS sales FROM order_items oi "
                  "JOIN orders o ON oi.order_id=o.order_id "
                  "JOIN customers c ON o.customer_id=c.customer_id GROUP BY c.customer_state",
                  res(["state", "sales"], [{"state": "SP", "sales": 13_591_643.70}])),
            [],
        )
        # 但问"分布/概览"→ 按项目约定仍要求三列齐全
        v = check("订单在各州的分布如何？", "", res(cols, rows))
        self.assertEqual([x.caliber for x in v], ["C20"])

    def test_empty_state_result_caught(self):
        """州维度查询返回 0 行 —— 关联键写错，必须判违规，不能豁免。"""
        v = check("q", "", res(Q5_COLS, []))
        calibers = [x.caliber for x in v]
        self.assertIn("C19", calibers)
        self.assertIn("空", next(x.message for x in v if x.caliber == "C19"))


class TestHighValuePopulation(unittest.TestCase):
    """C14：高价值客户分层总体守恒（96,095 = 5 × 19,219）。"""

    def test_correct_quintiles_pass(self):
        self.assertEqual(check("q", "NTILE(5) OVER (ORDER BY total_spend DESC)", res(Q10_COLS, Q10_OK_ROWS)), [])

    def test_overfiltered_population_caught(self):
        """历史真实错误：要求已签收/有评价 → 各档人数不再等于 19,219。"""
        rows = [
            {"quintile": 1, "customers": 21145, "avg_spend": 402.1, "avg_orders": 1.12},
            {"quintile": 2, "customers": 18672, "avg_spend": 150.2, "avg_orders": 1.03},
            {"quintile": 3, "customers": 18901, "avg_spend": 101.3, "avg_orders": 1.02},
        ]
        v = check("q", "NTILE(5)", res(Q10_COLS, rows))
        self.assertEqual([x.caliber for x in v], ["C14"])
        self.assertIn(str(HIGH_VALUE_CUSTOMERS), v[0].message.replace("96,095", "96095"))
        self.assertIn("customer_unique_id", v[0].message)

    def test_customer_id_instead_of_unique_caught(self):
        """用 customer_id 分层 → 总体偏大。"""
        rows = [
            {"quintile": q, "customers": 19876, "avg_spend": 100.0, "avg_orders": 1.0}
            for q in range(1, 6)
        ]
        v = check("q", "NTILE(5)", res(Q10_COLS, rows))
        self.assertEqual([x.caliber for x in v], ["C14"])

    def test_outer_join_fanout_inflates_customers_caught(self):
        """历史真实错误（GLM-4.5-Air）：分层后又 JOIN 回订单明细，
        COUNT(*) 被扇出成 99,440（= 订单数），反馈必须点明"偏大 / 被放大"。"""
        rows = [
            {"quintile": 1, "customers": 21145, "avg_spend": 412.3, "avg_orders": 1.1},
            {"quintile": 2, "customers": 20003, "avg_spend": 168.0, "avg_orders": 1.04},
            {"quintile": 3, "customers": 19652, "avg_spend": 110.2, "avg_orders": 1.02},
            {"quintile": 4, "customers": 19388, "avg_spend": 71.4, "avg_orders": 1.01},
            {"quintile": 5, "customers": 19252, "avg_spend": 40.1, "avg_orders": 1.0},
        ]
        v = check("q", "NTILE(5)", res(Q10_COLS, rows))
        self.assertEqual([x.caliber for x in v], ["C14"])
        self.assertIn("偏大", v[0].message)
        self.assertIn("99440", v[0].message)

    def test_empty_layered_result_caught(self):
        """历史真实错误（GLM-4.6V）：用 customer_unique_id JOIN orders.customer_id
        → 关联键写错、0 行。空结果不能被豁免。"""
        cols = ["quintile", "customers", "avg_spend", "avg_orders"]
        v = check("q", "NTILE(5)", res(cols, []))
        self.assertEqual([x.caliber for x in v], ["C14"])
        self.assertIn("0 行", v[0].message)

    def test_overfiltered_message_says_too_small(self):
        rows = [{"quintile": q, "customers": 18672, "avg_spend": 1.0, "avg_orders": 1.0}
                for q in range(1, 6)]
        v = check("q", "NTILE(5)", res(Q10_COLS, rows))
        self.assertIn("偏小", v[0].message)


class TestDurationFanout(unittest.TestCase):
    """C16：时长不得被"一单多行"扇出加权。"""

    def test_deepseek_q5_fanout_caught(self):
        v = check("q", Q5_FANOUT_SQL, res(Q5_COLS, Q5_OK_ROWS))
        self.assertIn("C16", [x.caliber for x in v])
        self.assertIn("扇出", next(x.message for x in v if x.caliber == "C16"))

    def test_preaggregated_sql_passes(self):
        v = check("q", Q5_PREAGG_SQL, res(Q5_COLS, Q5_OK_ROWS))
        self.assertEqual(v, [])

    def test_in_subquery_does_not_false_positive(self):
        """payment 只在 IN 子查询里出现，不会扇出行 → 不该报。"""
        sql = (
            "SELECT c.customer_state AS state, COUNT(DISTINCT o.order_id) AS orders, "
            "ROUND(AVG(TIMESTAMPDIFF(DAY, o.order_purchase_timestamp, o.order_delivered_customer_date)), 1) "
            "AS avg_delivery_days FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
            "WHERE o.order_id IN (SELECT order_id FROM order_payments) GROUP BY c.customer_state"
        )
        cols = ["state", "orders", "gmv", "avg_delivery_days"]
        rows = [{"state": "SP", "orders": 41745, "gmv": 5998226.96, "avg_delivery_days": 8.3},
                {"state": "RJ", "orders": 57695, "gmv": 10010645.16, "avg_delivery_days": 14.8}]
        self.assertEqual(check("q", sql, res(cols, rows)), [])


class TestNoFalsePositive(unittest.TestCase):
    """正常结果不得被误报。"""

    def test_monthly_trend_untouched(self):
        cols = ["month", "monthly_gmv"]
        rows = [{"month": f"2016-{m:02d}", "monthly_gmv": 100.0 * m} for m in range(1, 13)]
        self.assertEqual(check("q", "SELECT DATE_FORMAT(...) ... GROUP BY month", res(cols, rows)), [])

    def test_empty_result_no_crash(self):
        self.assertEqual(check("q", "", res(["a"], [])), [])

    def test_single_row_review_not_mistaken_for_totals(self):
        self.assertEqual(check("q", "", res(["avg_score", "review_count"], [{"avg_score": 4.9, "review_count": 22}])), [])

    def test_guard_never_raises_on_garbage(self):
        self.assertEqual(check("q", "NOT SQL", {"columns": None, "rows": [object()]}), [])


class TestDuplicateMetricColumns(unittest.TestCase):
    """C22：分层结果里不得出现互为副本的数值列。"""

    def test_avg_spend_copied_into_avg_orders_caught(self):
        """两个 GLM 的真实错误：人均单数写成 `SUM(total_spend)/COUNT(*)`，
        与人均消费逐行相等（那其实是人均消费，不是单数）。"""
        cols = ["quintile", "customers", "avg_spend", "avg_order_value"]
        rows = [
            {"quintile": 1, "customers": 19219, "avg_spend": 447.89, "avg_order_value": 447.89},
            {"quintile": 2, "customers": 19219, "avg_spend": 165.83, "avg_order_value": 165.83},
            {"quintile": 3, "customers": 19219, "avg_spend": 108.82, "avg_order_value": 108.82},
        ]
        v = check("q", "NTILE(5)", res(cols, rows))
        self.assertIn("C22", [x.caliber for x in v])
        msg = next(x.message for x in v if x.caliber == "C22")
        self.assertIn("人均单数", msg)
        self.assertIn("avg_order_value", msg)

    def test_distinct_metrics_no_false_positive(self):
        self.assertEqual(check("q", "NTILE(5)", res(Q10_COLS, Q10_OK_ROWS)), [])

    def test_same_columns_outside_layered_shape_not_flagged(self):
        """非分层形状不做重复列判定，避免误伤正常的对比列（如 sales vs prev_sales）。"""
        cols = ["month", "sales", "prev_sales"]
        rows = [
            {"month": "2017-01", "sales": 100.0, "prev_sales": 100.0},
            {"month": "2017-02", "sales": 100.0, "prev_sales": 100.0},
        ]
        self.assertEqual(check("q", "SELECT ... GROUP BY month", res(cols, rows)), [])


class TestTruncatedScopeGate(unittest.TestCase):
    """守恒式在 TopN / LIMIT 场景必须**主动跳过**，不能误报。

    来源：高压测试真实误报 —— 问"各州客单价排名前十的州是哪些？"，
    正确 SQL（外层 LIMIT 10）被 C19 判成"订单数之和 = 3497 ≠ 99440"、
    又被 C20 判成"缺少平均配送时长"，结果被反复回灌改错、最终标 caliber_ok=false。

    守恒式的前提是"分组覆盖全集"，TopN 时前提不成立 → 宁可不判，也不误报。
    """

    Q10_AOV_TOP10 = (
        "WITH state_orders AS (SELECT c.customer_state, COUNT(DISTINCT o.order_id) AS order_count, "
        "SUM(p.payment_value) AS total_gmv FROM orders o JOIN customers c ON o.customer_id=c.customer_id "
        "JOIN order_payments p ON o.order_id=p.order_id GROUP BY c.customer_state) "
        "SELECT customer_state AS state, order_count, ROUND(total_gmv/order_count, 2) AS aov "
        "FROM state_orders ORDER BY aov DESC LIMIT 10"
    )
    TOP10_ROWS = [
        {"state": "AP", "order_count": 68, "aov": 274.5},
        {"state": "AC", "order_count": 15, "aov": 231.0},
        {"state": "PB", "order_count": 517, "aov": 202.1},
    ]
    TOP10_COLS = ["state", "order_count", "aov"]

    def test_topn_state_query_not_flagged(self):
        v = check("各州客单价排名前十的州是哪些？", self.Q10_AOV_TOP10,
                  res(self.TOP10_COLS, self.TOP10_ROWS))
        self.assertEqual([x.caliber for x in v], [], "TopN 场景不应触发守恒式")

    def test_same_shape_without_limit_still_caught(self):
        """去掉 LIMIT（= 真的在统计全集）时，守恒式必须照常生效 —— 不能把闸门开太大。"""
        sql = self.Q10_AOV_TOP10.replace(" LIMIT 10", "")
        v = check("各州的订单数和客单价分别是多少？", sql,
                  res(self.TOP10_COLS, self.TOP10_ROWS))
        codes = [x.caliber for x in v]
        self.assertIn("C19", codes)
        self.assertIn("C20", codes)

    def test_q5_full_coverage_still_caught(self):
        """Q5 形状（无 LIMIT、覆盖全集）的保护不能被削弱。"""
        rows = [dict(r) for r in Q5_OK_ROWS]
        rows[0]["orders"] += 1
        v = check("每个州的订单分布如何？", "SELECT ... GROUP BY c.customer_state",
                  res(Q5_COLS, rows))
        self.assertIn("C19", [x.caliber for x in v])

    def test_window_rank_topn_question_skipped(self):
        """用 ROW_NUMBER 取前 N（无 LIMIT 关键字）时也要跳过。"""
        sql = ("WITH t AS (SELECT customer_state AS state, COUNT(*) AS orders, "
               "ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC) AS rn FROM orders GROUP BY customer_state) "
               "SELECT state, orders FROM t WHERE rn <= 10")
        v = check("订单数最多的前十个州是？", sql, res(["state", "orders"], self.TOP10_ROWS))
        self.assertEqual([x.caliber for x in v], [])

    def test_truncated_result_skipped(self):
        """结果被 1000 行上限截断时，求和只覆盖前 1000 行 → 守恒式必须跳过。

        来源：高压测试真实误报 —— "每个州每个品类每个卖家的销售额"按州×品类×卖家
        分组有数万行，被截断成 1000 行后 C19 拿 316,688 去比全平台的 16,008,872，
        把完全正确的 SQL 判成"金额被扇出放大"。
        """
        sql = ("SELECT c.customer_state AS state, SUM(oi.price) AS sales "
               "FROM order_items oi JOIN orders o ON oi.order_id=o.order_id "
               "JOIN customers c ON o.customer_id=c.customer_id "
               "GROUP BY c.customer_state, oi.seller_id")
        truncated_result = {
            "columns": ["state", "sales"],
            "rows": [{"state": "SP", "sales": 100000.0}, {"state": "RJ", "sales": 80000.0}],
            "row_count": 2,
            "truncated": True,
        }
        v = check("每个州每个卖家的销售额", sql, truncated_result)
        self.assertEqual([x.caliber for x in v], [], "被截断的结果不应触发守恒式")

    def test_price_caliber_compared_against_c15_not_gmv(self):
        """金额列来自 order_items.price 时，参照值必须是 C15（13,591,643.70），不是 GMV。

        来源：高压测试真实误报 —— SQL 用 SUM(oi.price)，列名叫 sales，
        C19 却拿 GMV 常量 16,008,872.12 去比，判定"金额被放大"。
        两套金额口径的总额本来就不同，拿错参照值 = 断言自身的 bug。
        """
        sql = ("SELECT c.customer_state AS state, SUM(oi.price) AS sales "
               "FROM order_items oi JOIN orders o ON oi.order_id=o.order_id "
               "JOIN customers c ON o.customer_id=c.customer_id GROUP BY c.customer_state")
        ok_rows = [{"state": "SP", "sales": 13_591_643.70}]
        self.assertEqual([x.caliber for x in check("各州销售额", sql, res(["state", "sales"], ok_rows))], [])

        bad_rows = [{"state": "SP", "sales": 16_008_872.12}]  # 误用了 GMV 口径
        v = check("各州销售额", sql, res(["state", "sales"], bad_rows))
        self.assertEqual([x.caliber for x in v], ["C15"])
        self.assertIn("商品售价", v[0].message)

    def test_gmv_caliber_still_compared_against_gmv(self):
        """payment_value 口径必须仍按 GMV 常量校验（别把闸门开成"钱都不查了"）。"""
        rows = [{"state": "SP", "gmv": 13_591_643.70}]  # 用售价总额冒充 GMV
        v = check("各州成交额", Q5_FANOUT_SQL, res(["state", "gmv"], rows))
        self.assertIn("C19", [x.caliber for x in v])


class TestFeedbackFormat(unittest.TestCase):
    """回灌给 LLM 的反馈必须带口径编号、可定位。"""

    def test_feedback_contains_caliber_and_sql_hint(self):
        rows = [dict(r) for r in Q5_OK_ROWS]
        rows[0]["orders"] += 1
        v = check("q", "", res(Q5_COLS, rows))
        text = format_feedback("SELECT ...", v)
        self.assertIn("[C19]", text)
        self.assertIn("口径", text)
        self.assertIn("只修正上述问题", text)

    def test_feedback_serializable(self):
        v = check("q", Q5_FANOUT_SQL, res(Q5_COLS, Q5_OK_ROWS))
        json.dumps([str(x) for x in v], ensure_ascii=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
