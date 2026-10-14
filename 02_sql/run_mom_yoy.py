"""环比/同比分析演示（教学用）。

用法：python 02_sql/run_mom_yoy.py

输出两部分：
  1. 月度 GMV + 环比/同比 明细表
  2. 自动业务解读（找出波动最大的月份）—— 分析师的产出不是表格，是结论
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "03_agent"))
from db import get_connection  # noqa: E402


def _read_sql(index: int) -> str:
    """读取 mom_yoy.sql 里的第 index 条语句（0=环比，1=同比）。"""
    text = (ROOT / "02_sql" / "mom_yoy.sql").read_text(encoding="utf-8")
    stmts = [s.strip() for s in text.split(";") if "SELECT" in s]
    return stmts[index]


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("  （无数据）")
        return
    headers = list(rows[0].keys())
    print("  " + " | ".join(f"{h:>16}" for h in headers))
    print("  " + "-" * (19 * len(headers)))
    for r in rows:
        print("  " + " | ".join(f"{str(r[h]):>16}" for h in headers))


def main() -> None:
    conn = get_connection()
    cur = conn.cursor()

    print("=" * 70)
    print("查询1：月度 GMV + 环比（MoM）")
    print("=" * 70)
    mom_rows = []
    cur.execute(_read_sql(0))
    mom_rows = cur.fetchall()
    _print_table(mom_rows)

    # ---- 自动业务解读：环比波动最大的月份 ----
    # 教学注：数据集首尾是不完整月（采集中途开始/结束），极小基数会让环比%失真，
    # 解读前必须剔除 —— 分析师的基本功：先清洗，再下结论。
    import statistics
    valid = [r for r in mom_rows if r.get("mom_pct") is not None]
    if len(valid) > 4:
        med = statistics.median(float(r["gmv"]) for r in valid)
        valid = valid[1:-1]
        valid = [r for r in valid
                 if float(r["gmv"]) >= 300000 and float(r["last_month_gmv"] or 0) >= 300000]
    if valid:
        up = max(valid, key=lambda r: r["mom_pct"])
        down = min(valid, key=lambda r: r["mom_pct"])
        print(f"\n  ▶ 解读：环比增长最快的是 {up['month']}（+{up['mom_pct']}%），"
              f"下滑最猛的是 {down['month']}（{down['mom_pct']}%），"
              f"应优先排查下滑月份的运营活动与流量来源。")

    print()
    print("=" * 70)
    print("查询2：月度 GMV + 同比（YoY）")
    print("=" * 70)
    cur.execute(_read_sql(1))
    yoy_rows = cur.fetchall()
    _print_table(yoy_rows)

    # 同比解读：两年都必须是"成熟月"（GMV>=30万），否则是爬坡期对比，无业务意义
    valid_y = [r for r in yoy_rows
               if r.get("yoy_pct") is not None
               and float(r["gmv"]) >= 300000 and float(r["gmv_last_year"]) >= 300000]
    if valid_y:
        worst = min(valid_y, key=lambda r: r["yoy_pct"])
        best = max(valid_y, key=lambda r: r["yoy_pct"])
        print(f"\n  ▶ 解读：同比表现最好的月份是 {best['month']}（+{best['yoy_pct']}%），"
              f"最差是 {worst['month']}（{worst['yoy_pct']}%）。"
              f"同比为负说明剔除季节因素后仍在退步，需定位到品类/地域下钻原因。")

    conn.close()


if __name__ == "__main__":
    main()
