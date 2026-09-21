# -*- coding: utf-8 -*-
"""BI 层宽表生成器的纯函数回归测试（不连数据库，可在 CI 里跑）。

覆盖：
1. `fmt()` 的数值格式化与空值处理；
2. `build_rows()` 对四张表返回的**键名契约**（数据源用 DictCursor，返回 dict 行）；
3. 中文取值翻译（州 / 品类 / 月份 / 消费分层）；
4. 供守恒断言使用的合计字段。

为什么不测 SQL：SQL 需要 MySQL，CI 上没有；SQL 的正确性由
`make_bi_exports.py` 运行时自带的 6 条守恒断言 + 4 条形状断言负责。
本文件负责的是"Python 这一侧的转换逻辑有没有写错"。
"""

from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (
    os.path.join(ROOT, "06_bi"),
    os.path.join(ROOT, "03_agent"),
    os.path.join(ROOT, "04_visualization"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import make_bi_exports as bi  # noqa: E402


class TestFmt(unittest.TestCase):
    def test_money_two_decimals(self):
        self.assertEqual(bi.fmt(Decimal("1234.5"), bi.MONEY), "1234.50")

    def test_one_decimal(self):
        self.assertEqual(bi.fmt(Decimal("8.34"), bi.ONE_DEC), "8.3")

    def test_none_becomes_empty_string(self):
        self.assertEqual(bi.fmt(None, bi.MONEY), "")
        self.assertEqual(bi.fmt(None, bi.ONE_DEC), "")


class TestBuildRowsState(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"state": "SP", "orders": 100, "gmv": Decimal("1000.00"),
             "aov": Decimal("10.00"), "avg_days": Decimal("8.34")},
            {"state": "RJ", "orders": 50, "gmv": Decimal("2000.00"),
             "aov": Decimal("40.00"), "avg_days": None},
        ]

    def test_header_is_chinese(self):
        res = bi.build_rows("dim_state", self.rows)
        self.assertEqual(
            res["header"],
            ["州代码", "州", "订单数", "成交额（元）", "客单价（元）", "平均配送天数"],
        )

    def test_sorted_by_gmv_desc(self):
        res = bi.build_rows("dim_state", self.rows)
        self.assertEqual([r[0] for r in res["rows"]], ["RJ", "SP"])

    def test_state_translated_and_none_days_blank(self):
        res = bi.build_rows("dim_state", self.rows)
        rj, sp = res["rows"]
        self.assertEqual(rj[1], "里约热内卢")
        self.assertEqual(rj[5], "")          # avg_days 为 None → 空串，不是 "None"
        self.assertEqual(sp[1], "圣保罗")

    def test_sums_used_by_assertions(self):
        res = bi.build_rows("dim_state", self.rows)
        self.assertEqual(res["orders_sum"], 150)
        self.assertEqual(res["money_sum"], 3000.0)


class TestBuildRowsOthers(unittest.TestCase):
    def test_monthly_label_is_chinese(self):
        rows = [{"ym": "2017-01", "orders": 10, "gmv": Decimal("100.00"),
                 "aov": Decimal("10.00")}]
        res = bi.build_rows("fct_monthly", rows)
        self.assertEqual(res["header"][:2], ["月份", "月份显示"])
        self.assertEqual(res["rows"][0][1], "2017 年 1 月")
        self.assertEqual(res["orders_sum"], 10)

    def test_category_none_falls_back_to_placeholder(self):
        rows = [{"category": None, "items": 3, "price_sum": Decimal("30.00"), "orders": 2}]
        res = bi.build_rows("dim_category", rows)
        self.assertEqual(res["rows"][0][0], "（未分类）")
        self.assertEqual(res["money_sum"], 30.0)

    def test_segment_sizes_and_chinese_quintile(self):
        rows = [
            {"quintile": i, "customers": 19219, "spend_per_capita": Decimal("100.00"),
             "orders_per_capita": Decimal("1.10")}
            for i in (1, 2, 3, 4, 5)
        ]
        res = bi.build_rows("dim_customer_segment", rows)
        self.assertEqual(res["rows"][0][0], "第 1 档（高消费）")
        self.assertEqual(res["seg_sizes"], [19219] * 5)

    def test_unknown_table_raises(self):
        with self.assertRaises(KeyError):
            bi.build_rows("not_a_table", [])


class TestCaliberConstants(unittest.TestCase):
    """守恒参照值必须与 CALIBER.md / caliber_check.py 同源，防止被随手改掉。"""

    def test_reference_values(self):
        self.assertEqual(bi.TOTAL_ORDERS, 99440)
        self.assertEqual(bi.TOTAL_GMV, Decimal("16008872.12"))
        self.assertEqual(bi.TOTAL_PRICE, Decimal("13591643.70"))
        self.assertEqual(bi.TOTAL_CUSTOMERS, 96095)
        self.assertEqual(bi.SEG_SIZE * 5, bi.TOTAL_CUSTOMERS)


if __name__ == "__main__":
    unittest.main()
