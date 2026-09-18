"""Agent 准确率评估：把 Agent 生成的 SQL 结果与 W2 手写基线逐一对比。

采用两层口径，对应口径登记表 P1=B（只要核心指标对，辅助列可多可少）：
- 严格一致：结果取值多重集完全相同（忽略列名/列序，数值保留 2 位）。
- 核心一致：行数一致（粒度相同），且**该题的核心指标列**取值全部出现在 Agent 结果里
  （核心指标一个都不能丢、不能错）；辅助列可有可无、可多可少。
  每题的核心指标列见 CORE_COLS。用来区分"辅助列差异"和"真正算错"。

用法：
    python 03_agent/evaluate.py            # 默认输出 agent_results.json
    python 03_agent/evaluate.py deepseek   # 输出 agent_results_deepseek.json
    也可用环境变量 EVAL_TAG=deepseek 指定标签。
产出：03_agent/agent_results[_<tag>].json + 控制台汇总

四个指标：
- 可执行率：SQL 没被三层静态校验拦下、能跑出结果
- 严格一致率：结果取值多重集与基线完全相同
- 核心一致率：粒度一致 + 核心指标列取值全中（P1=B）
- **口径通过率**：结果级守恒断言（caliber_guard 第 4 层）全部通过
第 4 个指标与第 3 个是互补的：核心一致看"和基线比"，口径通过看"和口径守恒式比"——
所以即使没有基线，口径通过率也能独立给出"结果是否可信"的信号。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "03_agent"))

from db import load_env  # noqa: E402

load_env()
from agent import ask  # noqa: E402


def _fmt(v) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float, Decimal)):
        return f"{float(v):.2f}"
    return str(v)


def _norm(rows) -> list[tuple[str, ...]]:
    out = []
    for r in rows:
        vals = list(r.values()) if isinstance(r, dict) else list(r)
        out.append(tuple(sorted(_fmt(v) for v in vals)))
    return sorted(out)


def _num_set(rows) -> set[str]:
    s: set[str] = set()
    for r in rows:
        vals = r.values() if isinstance(r, dict) else r
        for v in vals:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float, Decimal)):
                s.add(f"{float(v):.2f}")
    return s


def _num_set_cols(rows, cols: list[str]) -> set[str]:
    """只取指定列的数值集合（口径登记表 P1=B：核心指标列）。"""
    s: set[str] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        for c in cols:
            v = r.get(c)
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float, Decimal)):
                s.add(f"{float(v):.2f}")
    return s


# 每题的核心指标列（必须命中；其余列为辅助列，可多可少）
# 对应 03_agent/CALIBER.md 的 P1=B 决策
CORE_COLS: dict[str, list[str]] = {
    "1": ["total_orders", "gmv", "aov"],
    "2": ["monthly_gmv"],
    "3": ["category_sales"],
    "4": ["repurchase_rate"],
    "5": ["orders", "avg_delivery_days"],
    "6": ["avg_score", "review_count"],
    "7": ["monthly_sales"],
    "8": ["delivered_orders", "avg_delivery_days"],
    "9": ["sales", "prev_sales"],
    "10": ["customers", "avg_spend", "avg_orders"],
}


def _load_questions() -> list[dict]:
    spec = importlib.util.spec_from_file_location("questions", ROOT / "01_data" / "questions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.QUESTIONS


def main() -> None:
    tag = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EVAL_TAG", "")).strip()
    out_name = f"agent_results_{tag}.json" if tag else "agent_results.json"

    baseline = json.loads((ROOT / "02_sql" / "baseline_results.json").read_text(encoding="utf-8"))
    questions = _load_questions()

    print("=" * 80)
    print(f"评估模型 : {os.environ.get('OPENAI_MODEL', '(未设置)')}")
    print(f"接口地址 : {os.environ.get('OPENAI_BASE_URL', '(未设置)')}")
    print(f"结果文件 : 03_agent/{out_name}")
    print("=" * 80)

    results: dict[str, dict] = {}
    strict = core = executable = caliber_pass = guard_fired = 0
    total = len(questions)

    print(f"{'题':<4}{'状态':<9}{'尝试':<5}{'行数':<6}{'严格':<5}{'核心':<6}{'口径':<5}说明")
    print("-" * 80)
    for q in questions:
        qid = str(q["id"])
        base_rows = baseline.get(qid, {}).get("rows", [])
        base_core_nums = _num_set_cols(base_rows, CORE_COLS.get(qid, []))
        rec: dict = {"id": q["id"], "title": q["title"], "question": q["question"]}
        try:
            out = ask(q["question"], want_conclusion=False)
        except Exception as exc:  # noqa: BLE001
            out = {"status": "exception", "error": str(exc)}

        rec.update(status=out.get("status"), attempts=out.get("attempts"), sql=out.get("sql"))
        if out.get("status") != "ok":
            rec.update(strict=False, core=False, caliber_ok=False)
            print(f"{qid:<4}{out.get('status',''):<9}{str(out.get('attempts','-')):<5}{'-':<6}{'✗':<5}{'✗':<6}{'-':<5}{(out.get('error') or '')[:30]}")
            results[qid] = rec
            continue

        executable += 1
        agent_rows = out["result"]["rows"]
        agent_nums = _num_set(agent_rows)
        rec["row_count"] = len(agent_rows)

        # 第 4 层口径断言的结果（caliber_guard）：是否通过、触发了哪些违规
        caliber_ok = bool(out.get("caliber_ok", True))
        rec["caliber_ok"] = caliber_ok
        rec["caliber_violations"] = out.get("caliber_violations", [])
        caliber_pass += caliber_ok
        # 触发过口径重试（尝试次数 > 1 且最终通过）= 结构化回灌真的救回来了
        if out.get("attempts", 1) > 1 and caliber_ok:
            guard_fired += 1

        is_strict = _norm(agent_rows) == _norm(base_rows)
        # 核心一致 = 粒度一致（行数相同）且"该题核心指标列"的取值全部出现在 Agent 结果里。
        # 辅助列可多可少（P1=B），但核心指标的数值一个都不能丢、不能错。
        is_core = (
            len(agent_rows) == len(base_rows)
            and bool(base_core_nums)
            and base_core_nums <= agent_nums
        )
        rec.update(strict=is_strict, core=is_core)
        strict += is_strict
        core += is_core
        note = "" if is_strict else f"基线{len(base_rows)}行/Agent{len(agent_rows)}行"
        if not caliber_ok:
            note = (note + " | 口径：" + "；".join(v.split("]")[0] + "]" for v in rec["caliber_violations"]))[:60]
        print(f"{qid:<4}{'ok':<9}{str(out.get('attempts')):<5}{len(agent_rows):<6}{('✓' if is_strict else '✗'):<5}{('✓' if is_core else '✗'):<6}{('✓' if caliber_ok else '✗'):<5}{note}")
        results[qid] = rec

    (ROOT / "03_agent" / out_name).write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    print("-" * 80)
    print(f"可执行率   : {executable}/{total} = {executable / total:.0%}")
    print(f"严格一致率 : {strict}/{total} = {strict / total:.0%}   (取值完全一致)")
    print(f"核心一致率 : {core}/{total} = {core / total:.0%}   (行数一致且无造数)")
    print(f"口径通过率 : {caliber_pass}/{total} = {caliber_pass / total:.0%}   (结果级守恒断言全过)")
    print(f"回灌救回   : {guard_fired} 题   (口径断言曾报错、结构化反馈后模型改对)")


if __name__ == "__main__":
    main()
