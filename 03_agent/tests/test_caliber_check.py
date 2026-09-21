"""口径自检工具的回归测试：**注入项目真实踩过的 bug，确认每一类都能被抓出来**。

一个"永远返回 OK"的检查器毫无价值，所以这里逐条喂入历史上真实发生过的口径不一致，
验证 `caliber_check` 会 FAIL / WARN。

运行（仅用标准库，无需 pytest）：
    python 03_agent/tests/test_caliber_check.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "03_agent"))

import caliber_check as cc  # noqa: E402
import evaluate  # noqa: E402


class CaliberCheckRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._sql_backup = dict(cc.SQL_BY_ID)
        self._core_backup = dict(evaluate.CORE_COLS)

    def tearDown(self) -> None:
        cc.SQL_BY_ID.clear()
        cc.SQL_BY_ID.update(self._sql_backup)
        evaluate.CORE_COLS.clear()
        evaluate.CORE_COLS.update(self._core_backup)

    # -- 工具 --
    def _results(self) -> list[dict]:
        return cc.run_checks()

    def _fails(self) -> list[dict]:
        return [r for r in self._results() if r["level"] == "FAIL"]

    def _find(self, needle: str, level: str = "FAIL") -> list[dict]:
        return [r for r in self._results() if r["level"] == level and needle in r["msg"]]

    # ---- 基准：干净状态下必须零 FAIL ----
    def test_current_state_is_clean(self) -> None:
        self.assertEqual([r["msg"] for r in self._fails()], [], "当前项目状态不应有 FAIL")

    # ---- bug 1：基线里混入 DATEDIFF（历史上 prompt/基线各写一套）----
    def test_detects_datediff_in_baseline(self) -> None:
        cc.SQL_BY_ID[5] = cc.SQL_BY_ID[5].replace(
            "TIMESTAMPDIFF(DAY, o.order_purchase_timestamp, o.order_delivered_customer_date)",
            "DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp)",
        )
        self.assertTrue(self._find("datediff"), "基线里的 DATEDIFF 未被抓出")

    # ---- bug 2：按月统计用了发货时间列（模型真实犯过）----
    def test_detects_shipping_limit_date(self) -> None:
        cc.SQL_BY_ID[7] = cc.SQL_BY_ID[7].replace("o.order_purchase_timestamp", "oi.shipping_limit_date")
        self.assertTrue(self._find("shipping_limit_date"), "发货时间列未被抓出")

    # ---- bug 3：表名回归成 olist_*_dataset 长名 ----
    def test_detects_long_table_name(self) -> None:
        cc.SQL_BY_ID[2] = cc.SQL_BY_ID[2].replace("order_payments", "olist_order_payments_dataset")
        self.assertTrue(self._find("olist_"), "长表名未被抓出")

    # ---- bug 4：表名拼写错误 ----
    def test_detects_unknown_table(self) -> None:
        cc.SQL_BY_ID[1] = cc.SQL_BY_ID[1].replace("FROM order_payments", "FROM order_paymets")
        self.assertTrue(self._find("order_paymets"), "拼错的表名未被抓出")

    # ---- bug 5：JOIN 扇出（模型真实犯过：Q3 金额被放大）----
    def test_warns_on_fanout(self) -> None:
        cc.SQL_BY_ID[3] = (
            "SELECT p.product_category_name AS category, SUM(op.payment_value) AS s "
            "FROM order_items oi "
            "JOIN order_payments op ON oi.order_id = op.order_id "
            "JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name"
        )
        self.assertTrue(self._find("扇出", level="WARN"), "扇出风险未被提示")

    # ---- bug 6：评估指标引用了基线里不存在的核心指标列 ----
    def test_detects_core_col_missing_in_baseline(self) -> None:
        evaluate.CORE_COLS["1"] = ["total_orders", "gmv", "aov", "not_a_real_column"]
        self.assertTrue(self._find("not_a_real_column"), "核心指标列缺失未被抓出")

    # ---- bug 7：评估指标的题目集合与基线不一致 ----
    def test_detects_core_cols_question_mismatch(self) -> None:
        del evaluate.CORE_COLS["10"]
        self.assertTrue(self._find("题目集合与基线不一致"), "题目集合不一致未被抓出")


if __name__ == "__main__":
    unittest.main(verbosity=2)
