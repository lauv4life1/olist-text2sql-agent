"""可视化层回归测试（选图规则 + 中文标签）。

覆盖两个**真实踩过的坑**，避免以后再犯：

1. **重复 x 的柱状图会被 Plotly 累加**：Q6「评分最高的产品 + 卖家」有 20 行
   （产品榜 10 + 卖家榜 10），若拿只有 2 个取值的 `entity_type` 当 x 轴，
   Plotly 会把同名分组的 10 个评分**加起来**，4.9 分被画成 49 分。
   → 选图规则必须挑"能唯一标识每一行"的分类列；挑不出来就退回表格。
2. **分层表的各档人数是均分的**：Q10 用 `NTILE(5)` 分层，5 档人数全是 19,219，
   拿"客户数"当 y 会画出一排等高柱子，毫无信息量。
   → 分层形状应在剩余指标里挑**区分度最大**的（变异系数），例如"人均消费"。

只依赖标准库 + pandas（`labels.py` 的表格翻译需要），不连数据库、不打 LLM。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "04_visualization"))

from chart_selector import classify  # noqa: E402
from labels import display_frame, display_rows, zh_column, zh_value  # noqa: E402


def _res(cols: list[str], rows: list[list]) -> dict:
    return {"columns": cols, "rows": [dict(zip(cols, r)) for r in rows]}


# Q6 的真实形状：两个榜单 × 10 个对象
_Q6 = _res(
    ["entity_type", "entity_id", "avg_score", "review_count"],
    [["product", f"p{i:030d}", 4.9 - i * 0.03, 20 + i] for i in range(10)]
    + [["seller", f"s{i:030d}", 4.4 - i * 0.04, 30 + i] for i in range(10)],
)

# Q5 的真实形状：各州三指标
_Q5 = _res(
    ["state", "orders", "gmv", "avg_delivery_days"],
    [["SP", 41745, 5998226.96, 8.3], ["RJ", 12852, 2113946.0, 14.8],
     ["MG", 11636, 1855000.0, 11.5]],
)

# Q10 的真实形状：NTILE(5) 分层，各档人数完全相同
_Q10 = _res(
    ["quintile", "customers", "avg_spend", "avg_orders"],
    [[1, 19219, 447.89, 1.10], [2, 19219, 201.35, 1.05],
     [3, 19219, 108.82, 1.02], [4, 19219, 74.10, 1.01],
     [5, 19219, 45.06, 1.00]],
)


class TestClassify(unittest.TestCase):
    def test_single_row_is_indicator(self):
        self.assertEqual(classify(_res(["a"], [[1]]))["type"], "indicator")

    def test_empty_result(self):
        self.assertEqual(classify({"columns": [], "rows": []})["type"], "empty")

    def test_bar_picks_unique_categorical_col(self):
        """Q6：两个分类列（entity_type 只有 2 个取值）时必须选 entity_id，否则会被累加。"""
        spec = classify(_Q6)
        self.assertEqual(spec["type"], "bar")
        self.assertEqual(spec["x"], "entity_id")
        self.assertEqual(spec["y"], "avg_score")

    def test_bar_falls_back_to_table_when_x_not_unique(self):
        """所有分类列都重复时 → 退回表格，宁可不画也不画一张会骗人的图。"""
        res = _res(["kind", "name", "v"], [["a", "x", 1], ["a", "x", 2], ["b", "y", 3]])
        self.assertEqual(classify(res)["type"], "table")

    def test_quintile_uses_most_discriminative_metric(self):
        """Q10：分层表不能拿"人数"当 y（各档均分），要挑区分度最大的指标。"""
        spec = classify(_Q10)
        self.assertEqual(spec["type"], "bar")
        self.assertEqual(spec["x"], "quintile")
        self.assertEqual(spec["y"], "avg_spend")

    def test_state_distribution_keeps_first_metric(self):
        """Q5：普通分类维度仍取第一个数值列（订单量），不被新规则带偏。"""
        spec = classify(_Q5)
        self.assertEqual((spec["type"], spec["x"], spec["y"]),
                         ("bar", "state", "orders"))

    def test_time_series_with_category_becomes_multi_line(self):
        res = _res(["month", "seller_id", "sales"],
                   [["2017-01", "a", 1], ["2017-01", "b", 2], ["2017-02", "a", 3]])
        spec = classify(res)
        self.assertEqual(spec["type"], "line")
        self.assertEqual((spec["x"], spec["y"], spec["series"]),
                         ("month", "sales", "seller_id"))


class TestLabels(unittest.TestCase):
    def test_column_exact_lookup(self):
        self.assertEqual(zh_column("order_purchase_timestamp"), "下单时间")
        self.assertEqual(zh_column("shipping_limit_date"), "发货截止时间")

    def test_date_like_columns_not_translated_as_order_count(self):
        """年份规则曾把 `order_purchase_timestamp` 按 "order" 命中译成"订单量"。"""
        for col in ("order_delivered_customer_date", "created_at", "some_custom_timestamp"):
            self.assertNotIn("订单量", zh_column(col), f"{col} 被误译")
        self.assertEqual(zh_column("created_at"), "时间")
        self.assertEqual(zh_column("some_custom_timestamp"), "时间")

    def test_column_unknown_falls_back_to_original(self):
        self.assertEqual(zh_column("totally_unknown_col"), "totally_unknown_col")

    def test_state_code_to_chinese(self):
        self.assertEqual(zh_value("state", "SP"), "圣保罗")
        self.assertEqual(zh_value("state", "RJ"), "里约热内卢")

    def test_category_english_to_chinese(self):
        self.assertEqual(zh_value("category", "health_beauty"), "美妆个护")

    def test_unknown_value_kept(self):
        """宁可不翻译，也不要译错。"""
        self.assertEqual(zh_value("category", "brand_new_category"), "brand_new_category")

    def test_rows_translated_without_column_collision(self):
        """两列翻成同名时必须退回原名，避免 DataFrame 出现重复列。"""
        cols, rows = display_rows(
            [{"a": 1, "sales": 2, "category_sales": 3}], ["a", "sales", "category_sales"]
        )
        self.assertEqual(len(set(cols)), len(cols), f"列名重复：{cols}")
        self.assertEqual(len(rows[0]), 3)

    def test_display_frame_columns_are_chinese(self):
        df = display_frame(_Q5)
        self.assertIn("州", df.columns)
        self.assertIn("订单量", df.columns)
        self.assertEqual(len(df), 3)


class TestRenderTheme(unittest.TestCase):
    """渲染层：主题默认值不能覆盖各分支算好的自适应参数。"""

    @classmethod
    def setUpClass(cls):
        try:
            import plotly  # noqa: F401
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("未安装 plotly，跳过渲染层测试")
        from chart_renderer import render
        cls.render = staticmethod(render)

    def test_adaptive_left_margin_survives_theme(self):
        """横向条形图的左边距按标签宽度算，主题默认值**不能**把它覆盖回 72。

        `_apply_theme` 曾无条件设置 margin，导致所有自适应边距是死代码，
        Q10「第 1 档（高消费）」这类中文标签被裁掉左半边。
        """
        fig = self.render(_Q10)
        self.assertIsNotNone(fig)
        self.assertGreaterEqual(fig.layout.margin.l, 120,
                                "左边距被主题默认值覆盖了")

    def test_hash_labels_get_room(self):
        """Q6：32 位 id 截断成 17 字后仍要留够边距。"""
        fig = self.render(_Q6)
        self.assertIsNotNone(fig)
        self.assertGreaterEqual(fig.layout.margin.l, 120)

    def test_q6_plots_one_bar_per_row(self):
        """Q6 有 20 行 → 20 根柱子，绝不能因重复 x 被聚合成 2 根。"""
        fig = self.render(_Q6)
        self.assertEqual(len(fig.data[0].x), 20)

    def test_two_metrics_go_on_secondary_axis(self):
        """时间序列带两个指标时，第二条走右轴而不是被丢掉。"""
        res = _res(["month", "orders", "avg_days"],
                   [["2017-01", 10, 5.0], ["2017-02", 20, 6.0], ["2017-03", 30, 7.0]])
        fig = self.render(res)
        self.assertEqual(len(fig.data), 2)
        self.assertEqual(getattr(fig.data[1], "yaxis", None), "y2")


if __name__ == "__main__":
    unittest.main()
