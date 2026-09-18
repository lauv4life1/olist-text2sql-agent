"""口径自检（Caliber Check）——扫描基线 SQL / prompt 规则 / few-shot / 评估指标
是否与《口径登记表》(03_agent/CALIBER.md) 一致。

为什么需要它：
    本项目的准确率提升主要来自"口径治理"，而口径是散落在五处的
    （① 基线 SQL ② prompt 硬规则 ③ few-shot ④ 评估指标 CORE_COLS ⑤ 第 4 层口径断言 caliber_guard）。
    只要有一处漂了，模型就一定答错，而且很难肉眼发现。

    我们已经真实踩过的坑：
      · prompt 规则写 `DATEDIFF`，而基线 Q8 写 `TIMESTAMPDIFF`
        → 模型被 prompt 主动引向错误算法
      · 基线自身不自洽：同一个"配送天数"在 Q5 用 DATEDIFF、Q8 用 TIMESTAMPDIFF
      · 模型在 Q7 用 `shipping_limit_date`（发货截止日）当月分组
      · 把 `order_payments` JOIN 到 `order_items` 后求和 → 行数扇出、金额放大
      · 第 4 层的守恒量写死在代码里、登记表写在文档里 → 两边会各自漂移
    这些本该由机器扫出来，而不是靠人盯。本脚本就是那台机器。

用法：
    python 03_agent/caliber_check.py           # 文本报告；有 FAIL 时退出码 1（可用于 CI）
    python 03_agent/caliber_check.py --json    # JSON 输出

无需数据库、无需 API Key。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "02_sql"))
sys.path.insert(0, str(ROOT / "03_agent"))

from prompt_builder import FEW_SHOT, SYSTEM_PROMPT  # noqa: E402
from sql_answers import SQL_BY_ID  # noqa: E402

CALIBER_MD = ROOT / "03_agent" / "CALIBER.md"
BASELINE_JSON = ROOT / "02_sql" / "baseline_results.json"

# 本脚本检查的口径条目 —— 每个都必须能在 CALIBER.md 里找到，否则报"未登记"
CHECKED_CALIBERS = [
    "C1", "C2", "C5", "C9", "C10", "C12", "C13", "C14", "C15", "C16",
    "C17", "C18", "C19", "C20", "C21", "C22", "C23",
]

# 明确禁止出现在 SQL 里的函数 / 字段（值 = 对应的口径条目与原因）
BANNED_IN_SQL: dict[str, str] = {
    "datediff": "C5 禁止用 DATEDIFF（配送时长必须用 TIMESTAMPDIFF，满 24 小时算一天）",
    "shipping_limit_date": "C17 禁止用发货相关时间列（'按月'必须用 order_purchase_timestamp）",
    'olist_': "表名必须是短名（orders / order_items / ...），禁止 olist_*_dataset",
}

# 出现这些字段的 SQL 即视为"在算配送时长"，必须使用 TIMESTAMPDIFF
DURATION_MARKERS = ("order_delivered_customer_date",)
REQUIRED_DURATION_FUNC = "timestampdiff"

ALLOWED_TABLES = {
    "orders",
    "order_items",
    "order_payments",
    "customers",
    "products",
    "sellers",
    "order_reviews",
    "product_category_name_translation",
    "geolocation",
}


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)


def _sources() -> list[tuple[str, str]]:
    """返回所有需要自检的 SQL 源：(来源标签, SQL 文本)。"""
    out = [(f"基线 Q{qid}", sql) for qid, sql in sorted(SQL_BY_ID.items())]
    out += [(f"few-shot #{i + 1}", ex["sql"]) for i, ex in enumerate(FEW_SHOT)]
    return out


def _cte_names(sql: str) -> set[str]:
    return {m.lower() for m in re.findall(r"(?:WITH|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", sql, flags=re.I)}


def _table_refs(sql: str) -> list[str]:
    return [m.lower() for m in re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_]\w*)", sql, flags=re.I)]


def run_checks() -> list[dict]:
    results: list[dict] = []

    def add(level: str, caliber: str, where: str, msg: str) -> None:
        results.append({"level": level, "caliber": caliber, "where": where, "msg": msg})

    sources = _sources()

    # ---- 检查 1：禁用项不得出现在任何 SQL 中 ----
    for label, raw in sources:
        sql = _strip_comments(raw).lower()
        for token, reason in BANNED_IN_SQL.items():
            if token in sql:
                add("FAIL", reason.split()[0], label, f"出现禁用项 `{token}` —— {reason}")

    # ---- 检查 2：算配送时长的 SQL 必须用 TIMESTAMPDIFF ----
    for label, raw in sources:
        sql = _strip_comments(raw).lower()
        if any(m in sql for m in DURATION_MARKERS) and REQUIRED_DURATION_FUNC not in sql:
            add(
                "FAIL",
                "C5",
                label,
                "涉及签收时间但未使用 TIMESTAMPDIFF —— 配送时长算法不一致",
            )

    # ---- 检查 3：出现 DATE_FORMAT 的 SQL 必须按 order_purchase_timestamp 分组 ----
    for label, raw in sources:
        sql = _strip_comments(raw)
        if "DATE_FORMAT" in sql.upper():
            fmt_args = re.findall(r"DATE_FORMAT\s*\(\s*([^,]+),", sql, flags=re.I)
            bad = [a.strip() for a in fmt_args if "order_purchase_timestamp" not in a]
            if bad:
                add("FAIL", "C17", label, f"DATE_FORMAT 的时间列不是 order_purchase_timestamp：{bad}")

    # ---- 检查 4：FROM/JOIN 的表名必须短名白名单或 CTE ----
    for label, raw in sources:
        sql = _strip_comments(raw)
        ctes = _cte_names(sql)
        for ref in _table_refs(sql):
            if ref not in ALLOWED_TABLES and ref not in ctes:
                add("FAIL", "表名约定", label, f"引用了未知表名 `{ref}`（不在短名白名单内，也不是 CTE）")

    # ---- 检查 5：扇出风险（order_items 与 order_payments 同层 JOIN 后聚合 payment_value）----
    for label, raw in sources:
        sql = _strip_comments(raw).lower()
        has_pay_agg = re.search(r"sum\s*\(\s*[\w.]*payment_value", sql) is not None
        if "order_items" in sql and "order_payments" in sql and has_pay_agg:
            # 正确写法是先把 order_payments 按 order_id 聚合（出现 GROUP BY order_id）再关联
            safe = re.search(r"group\s+by\s+order_id", sql) is not None
            if not safe:
                add(
                    "WARN",
                    "C20",
                    label,
                    "order_items 与 order_payments 同层出现且聚合 payment_value —— 有行数扇出风险，"
                    "应先把 order_payments 按 order_id 聚合再关联",
                )

    # ---- 检查 6：prompt 规则自身不得把模型引向 DATEDIFF ----
    for i, line in enumerate(SYSTEM_PROMPT.splitlines(), 1):
        if "DATEDIFF" in line and not any(k in line for k in ("禁止", "不要", "不得", "勿")):
            add("FAIL", "C5", f"prompt_builder.py SYSTEM_PROMPT 第 {i} 行", f"该行出现 DATEDIFF 但未声明禁用：{line.strip()[:60]}")
    if "TIMESTAMPDIFF" not in SYSTEM_PROMPT:
        add("FAIL", "C5", "prompt_builder.py SYSTEM_PROMPT", "未声明配送时长必须用 TIMESTAMPDIFF")

    # ---- 检查 7：评估指标 CORE_COLS 与基线结果 / 问题集是否对得上 ----
    try:
        from evaluate import CORE_COLS  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        add("FAIL", "C12", "evaluate.py", f"无法导入 CORE_COLS：{exc}")
        CORE_COLS = {}

    if CORE_COLS:
        baseline_ids = {str(qid) for qid in SQL_BY_ID}
        if set(CORE_COLS) != baseline_ids:
            add(
                "FAIL",
                "C12",
                "evaluate.py CORE_COLS",
                f"题目集合与基线不一致：CORE_COLS 有 {sorted(set(CORE_COLS) - baseline_ids)} 为多余，"
                f"缺少 {sorted(baseline_ids - set(CORE_COLS))}",
            )
        if BASELINE_JSON.exists():
            baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
            for qid, cols in CORE_COLS.items():
                rows = baseline.get(qid, {}).get("rows", [])
                if not rows:
                    add("FAIL", "C12", f"baseline_results.json Q{qid}", "基线结果为空，核心指标无法校验")
                    continue
                present = set(rows[0].keys())
                missing = [c for c in cols if c not in present]
                if missing:
                    add(
                        "FAIL",
                        "C12",
                        f"baseline_results.json Q{qid}",
                        f"核心指标列不存在于基线结果中：{missing}（当前列：{sorted(present)}）",
                    )
        else:
            add("WARN", "C12", "02_sql/baseline_results.json", "文件不存在，跳过核心指标列校验")

    # ---- 检查 8：被检查的口径条目必须在 CALIBER.md 里登记 ----
    md = ""
    if CALIBER_MD.exists():
        md = CALIBER_MD.read_text(encoding="utf-8")
        for cid in CHECKED_CALIBERS:
            if not re.search(rf"\b{cid}\b", md):
                add("FAIL", "登记表", "03_agent/CALIBER.md", f"口径条目 {cid} 未在登记表中登记")
    else:
        add("FAIL", "登记表", "03_agent/CALIBER.md", "口径登记表不存在")

    # ---- 检查 9：caliber_guard 的守恒量必须与登记表同值（文档 ↔ 断言的镜像关系）----
    try:
        import inspect  # noqa: PLC0415

        from caliber_guard import (  # noqa: PLC0415
            HIGH_VALUE_CUSTOMERS,
            QUINTILE_SIZE,
            TOTAL_GMV,
            TOTAL_ITEM_PRICE,
            TOTAL_ORDERS,
            _CHECKS,
        )
    except Exception as exc:  # noqa: BLE001
        add("FAIL", "C14", "03_agent/caliber_guard.py", f"无法导入口径断言常量：{exc}")
    else:
        constants = [
            ("TOTAL_ORDERS", f"{TOTAL_ORDERS}"),
            ("TOTAL_GMV", f"{TOTAL_GMV:.2f}"),
            ("TOTAL_ITEM_PRICE", f"{TOTAL_ITEM_PRICE:.2f}"),
            ("HIGH_VALUE_CUSTOMERS", f"{HIGH_VALUE_CUSTOMERS}"),
            ("QUINTILE_SIZE", f"{QUINTILE_SIZE}"),
        ]
        if md:
            plain = md.replace(",", "")
            for name, lit in constants:
                if lit not in plain:
                    add(
                        "FAIL",
                        "守恒量",
                        "CALIBER.md ↔ caliber_guard.py",
                        f"守恒量 {name} = {lit} 未出现在登记表中 —— 断言与文档已漂移",
                    )
        if QUINTILE_SIZE * 5 != HIGH_VALUE_CUSTOMERS:
            add(
                "FAIL",
                "C14",
                "03_agent/caliber_guard.py",
                f"守恒量自相矛盾：QUINTILE_SIZE×5 = {QUINTILE_SIZE * 5} ≠ HIGH_VALUE_CUSTOMERS = {HIGH_VALUE_CUSTOMERS}",
            )
        if md:
            used: set[str] = set()
            for fn in _CHECKS:
                used |= set(re.findall(r'Violation\(\s*"([A-Z]\d+)"', inspect.getsource(fn)))
            for cid in sorted(used):
                if not re.search(rf"\b{cid}\b", md):
                    add("FAIL", "登记表", "03_agent/caliber_guard.py", f"断言引用了未登记的口径 {cid}")

    return results


def main() -> None:
    results = run_checks()
    fails = [r for r in results if r["level"] == "FAIL"]
    warns = [r for r in results if r["level"] == "WARN"]

    if "--json" in sys.argv:
        print(json.dumps({"results": results, "fail": len(fails), "warn": len(warns)}, ensure_ascii=False, indent=2))
        sys.exit(1 if fails else 0)

    print("=" * 74)
    print("口径自检（Caliber Check）")
    print(f"自检源：基线 SQL {len(SQL_BY_ID)} 条 + few-shot {len(FEW_SHOT)} 条 + prompt 规则 + 评估指标 + 第 4 层断言")
    print("=" * 74)
    if not results:
        print("全部通过 —— 基线 / prompt / few-shot / 评估指标 / 口径断言 五处口径一致。")
    for r in results:
        print(f"[{r['level']}] {r['caliber']:<8} {r['where']}")
        print(f"         {r['msg']}")
    print("-" * 74)
    print(f"结果：FAIL {len(fails)} 项，WARN {len(warns)} 项")
    if fails:
        print("→ 存在口径不一致，请修正后再重跑评估（改口径要走 CALIBER.md 的五步流程）。")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
