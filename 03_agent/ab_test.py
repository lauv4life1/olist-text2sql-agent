"""A/B 测试统计模块（零依赖纯数学实现，不需要数据库）。

【概念课】A/B 测试 = 把用户随机分两组，一组旧版(A)一组新版(B)，
比较两组的转化率差异是"真的"还是"运气"。

【核心思想】就算两组其实没差别，纯靠运气也可能出现差异
（就像抛10次硬币出7次正面，不能说明硬币有问题）。
统计检验回答的问题是：如果两组真没差别，出现这么大差异的概率(p值)有多大？
  p < 0.05  → 运气很难解释 → 差异显著，新版真的更好
  p >= 0.05 → 很可能是运气 → 不能下结论

【面试三句话】
  1. A/B 测试的核心是随机分组，保证两组除改动外其他都一样；
  2. 看差异是否统计显著(p<0.05)，而不是看绝对数字大小；
  3. 样本量太小结论不可靠，实验前要先算需要多少样本。
"""
from __future__ import annotations

from math import erf, sqrt

# 常用临界值：alpha=0.05 双尾 / power=0.8
_Z_ALPHA_95 = 1.959964
_Z_POWER_80 = 0.841621


def _norm_cdf(x: float) -> float:
    """标准正态分布累积分布函数。"""
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def conversion_ztest(
    conversions_a: int,
    total_a: int,
    conversions_b: int,
    total_b: int,
    alpha: float = 0.05,
) -> dict:
    """两比例 z 检验：A/B 两组转化率差异是否统计显著。

    参数：各组转化数与总人数。返回含 p 值与结论的字典。
    """
    if total_a <= 0 or total_b <= 0:
        raise ValueError("样本量必须为正数")
    if not (0 <= conversions_a <= total_a and 0 <= conversions_b <= total_b):
        raise ValueError("转化数不能超过样本量")

    p_a = conversions_a / total_a
    p_b = conversions_b / total_b
    p_pool = (conversions_a + conversions_b) / (total_a + total_b)
    se = sqrt(p_pool * (1 - p_pool) * (1 / total_a + 1 / total_b))

    if se == 0:  # 两组转化率都为0或都为1，无法检验
        return {
            "rate_a": p_a, "rate_b": p_b, "lift_pct": 0.0,
            "z": 0.0, "p_value": 1.0, "significant": False,
            "conclusion": "两组转化率相同，无需检验",
        }

    z = (p_b - p_a) / se
    p_value = 2 * (1 - _norm_cdf(abs(z)))
    significant = p_value < alpha
    lift = (p_b / p_a - 1) * 100 if p_a else 0.0
    conclusion = (
        f"B组转化率 {p_b:.2%} vs A组 {p_a:.2%}（提升 {lift:+.1f}%），"
        f"p={p_value:.4f} {'<' if significant else '>='} {alpha}，"
        + ("差异显著，可认为新版有效" if significant else "差异不显著，可能是运气，建议扩大样本或继续实验")
    )
    return {
        "rate_a": round(p_a, 6),
        "rate_b": round(p_b, 6),
        "lift_pct": round(lift, 2),
        "z": round(z, 4),
        "p_value": round(p_value, 6),
        "significant": significant,
        "conclusion": conclusion,
    }


def required_sample_size(
    baseline_rate: float,
    mde: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> int:
    """实验前估算：每组需要多少样本才能检出 mde 的提升。

    baseline_rate 基线转化率（如0.10），mde 想检出的绝对提升（如0.02）。
    """
    if not 0 < baseline_rate < 1:
        raise ValueError("基线转化率必须在(0,1)之间")
    if mde <= 0:
        raise ValueError("mde 必须为正数")
    p1, p2 = baseline_rate, baseline_rate + mde
    if p2 >= 1:
        raise ValueError("基线+mde 不能超过1")
    p_bar = (p1 + p2) / 2
    n = (
        (_Z_ALPHA_95 * sqrt(2 * p_bar * (1 - p_bar))
         + _Z_POWER_80 * sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    ) / (mde ** 2)
    return int(n) + 1
