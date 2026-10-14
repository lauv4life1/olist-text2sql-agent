"""履约漏斗演示（教学用）。

用法：python 02_sql/run_funnel.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "03_agent"))
from db import get_connection  # noqa: E402

FUNNEL_SQL = (ROOT / "02_sql" / "funnel.sql").read_text(encoding="utf-8")


def main() -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(FUNNEL_SQL)
    row = cur.fetchone()
    conn.close()

    steps = [
        ("下单", row["step1_placed"], None),
        ("支付", row["step2_paid"], row["paid_rate_pct"]),
        ("发货", row["step3_shipped"], row["ship_rate_pct"]),
        ("送达", row["step4_delivered"], row["deliver_rate_pct"]),
        ("好评", row["step5_positive_review"], row["positive_rate_pct"]),
    ]

    print("=" * 62)
    print("Olist 履约漏斗（下单 → 支付 → 发货 → 送达 → 好评）")
    print("=" * 62)
    max_w = 40
    for i, (name, cnt, rate) in enumerate(steps):
        base = steps[0][1]
        bar = "█" * max(1, int(cnt / base * max_w))
        rate_txt = f"（上一步转化 {rate}%）" if rate is not None else "（100%，起点）"
        print(f"  {name}  {cnt:>7}  {bar} {rate_txt}")

    # 自动定位流失最严重的环节
    losses = [(steps[i][0] + "→" + steps[i + 1][0], 100 - steps[i + 1][2])
              for i in range(len(steps) - 1) if steps[i + 1][2] is not None]
    worst = max(losses, key=lambda x: x[1])
    print(f"\n  ▶ 解读：流失最严重的环节是【{worst[0]}】，流失 {worst[1]:.2f}%。")
    print("    漏斗思维：优化资源应该优先投在流失最大的环节，而不是平均用力。")


if __name__ == "__main__":
    main()
