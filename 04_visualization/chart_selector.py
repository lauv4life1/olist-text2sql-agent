"""根据查询结果的特征自动选择图表类型（Phase 4）。

规则：
- 单行结果            → 指标卡 indicator
- 含时间列 + 数值      → 折线 line（多一个分类列则按分类分线，如 Top5 卖家趋势）
- 含分类列 + 数值      → 柱状 bar
- 两个及以上数值列     → 散点 scatter
- 其余                → 表格 table
"""
from __future__ import annotations

import re
from decimal import Decimal

_NUM = (int, float, Decimal)


def _is_num(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, _NUM):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return True
        except ValueError:
            return False
    return False


def _looks_like_ym(v) -> bool:
    return isinstance(v, str) and bool(re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", v))


def classify(result: dict) -> dict:
    cols = result.get("columns", [])
    rows = result.get("rows", [])
    if not rows:
        return {"type": "empty"}
    if len(rows) == 1:
        return {"type": "indicator", "value_cols": [c for c in cols if _is_num(rows[0].get(c))]}

    num_cols = [c for c in cols if _is_num(rows[0].get(c))]
    cat_cols = [c for c in cols if c not in num_cols]

    time_col = next(
        (
            c
            for c in cols
            if re.search(r"month|date|week|year|月|年|时间", c, re.I)
            or _looks_like_ym(rows[0].get(c))
        ),
        None,
    )

    if time_col and num_cols:
        other_cat = [c for c in cat_cols if c != time_col]
        return {
            "type": "line",
            "x": time_col,
            "y": num_cols[0],
            "series": other_cat[0] if other_cat else None,
        }
    if cat_cols and num_cols:
        # 柱状图的 x 必须**唯一标识每一行**：Plotly 遇到重复 x 会把同名分组累加，
        # 于是"两个榜单 × 10 个对象"的评分会被加成 4.9×10≈49（Q6 踩过）。
        # 先挑取值最分散的分类列；若仍不唯一，说明这个结果没有可画的单一分类轴 → 退回表格。
        x = max(cat_cols, key=lambda c: len({str(r.get(c)) for r in rows}))
        if len({str(r.get(x)) for r in rows}) < len(rows):
            return {"type": "table"}
        return {"type": "bar", "x": x, "y": num_cols[0]}
    # 分位/分档类数值列（如 quintile 1..5）本质是分类维度，应出柱状图而非散点
    label_col = next(
        (
            c
            for c in num_cols
            if re.search(r"quintile|quartile|decile|bucket|tier|level|rank|分位|分档|分层", c, re.I)
        ),
        None,
    )
    if label_col and len(num_cols) >= 2:
        # 分层/分档表里，各档**人数通常是均分的**（NTILE 就是按人数等分），
        # 拿它当 y 会画出一排一样高的柱子，什么都没说。
        # 所以在剩余指标里挑**区分度最大**的那个（变异系数），例如"人均消费"。
        others = [c for c in num_cols if c != label_col]
        y = max(others, key=lambda c: _variation(rows, c))
        return {"type": "bar", "x": label_col, "y": y}
    if len(num_cols) >= 2:
        return {"type": "scatter", "x": num_cols[0], "y": num_cols[1]}
    return {"type": "table"}


def _variation(rows: list[dict], col: str) -> float:
    """变异系数（标准差 / 均值绝对值），用来衡量某个指标在结果内的区分度。

    全等值 → 0；均值接近 0 时退化成极差，避免除零。
    """
    vals = [float(r[col]) for r in rows if _is_num(r.get(col))]
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    sd = var ** 0.5
    if abs(mean) > 1e-9:
        return sd / abs(mean)
    return (max(vals) - min(vals))
