"""Text2SQL Agent 编排器：串联整条链路。

提问 → schema_extractor 提取表结构
→ prompt_builder 构建 prompt（schema + 业务规则 + few-shot + 输出格式）
→ sql_generator 调 LLM 生成 SQL（temperature=0）
→ sql_validator 3 层校验（安全 → 语法 → schema，失败回传错误重试）
→ sql_executor 只读执行（**执行期异常也回传重试，不崩**）
→ caliber_guard 第 4 层：结果级口径断言（失败回传**结构化口径反馈**重写）
→ 结果回传 LLM 生成自然语言结论

面试考点：为什么是 4 层而不是 3 层 —— 前三层保证 SQL "能跑"，第 4 层保证结果 "跑得对"。
扇出 / 分母口径错 / 总体过度过滤这类错误，SQL 语法完全合法、EXPLAIN 也过，
只有拿到结果集才能发现；发现后不是笼统说"错了"，而是定位到具体列 + 具体口径回灌给模型。

另一条同样重要的边界：**EXPLAIN 只解析不执行**。所以"语法合法但跑不出来"的错误
（标量子查询返回多行、MAX_EXECUTION_TIME 超时 3024 等）只能在执行期暴露 ——
执行期异常必须回灌重试，否则整个 Agent 会被一个异常打崩（高压测试实测命中过）。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import load_env  # noqa: E402
from schema_extractor import build_schema_context  # noqa: E402
from sql_generator import generate_sql  # noqa: E402
from sql_validator import validate  # noqa: E402
from sql_executor import execute  # noqa: E402
from caliber_guard import check as check_caliber, format_feedback  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAX_RETRIES = 2

# 模型"答不了"时的显式协议：与其让它编一条跑不通的 SQL，不如让它明说。
CANNOT_ANSWER_MARKER = "CANNOT_ANSWER"
_SQL_START = re.compile(r"^\s*\(*\s*(select|with)\b", re.I)
_CANNOT = re.compile(rf"^\s*{CANNOT_ANSWER_MARKER}\s*[:：]?\s*", re.I)
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


def _strip_fence(text: str) -> str:
    """去掉模型偶尔仍会加的 Markdown 代码围栏（硬规则里禁止，但不能指望 100% 遵守）。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = _FENCE.sub("", t).strip()
    return t


def _looks_like_sql(text: str) -> bool:
    return bool(_SQL_START.match(_strip_fence(text)))


def _is_refusal(text: str) -> bool:
    return text.strip().lower().startswith(CANNOT_ANSWER_MARKER.lower())


def _refusal_text(text: str) -> str:
    """把 `CANNOT_ANSWER: 原因` 或一段自然语言说明，整理成给用户看的答案。"""
    return _CANNOT.sub("", _strip_fence(text)).strip() or "现有表结构无法回答该问题。"


def _summarize(question: str, sql: str, result: dict) -> str:
    """把查询结果回传 LLM，生成 2-3 句业务结论。"""
    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        timeout=60,
    )
    preview = json.dumps(result["rows"][:10], ensure_ascii=False, default=str)
    prompt = (
        f"用户问题：{question}\n"
        f"执行的 SQL：{sql}\n"
        f"查询结果（前若干行）：{preview}\n\n"
        "请用中文、2-3 句话给出业务结论，点出关键数字和趋势，不要复述 SQL。"
    )
    kwargs = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "temperature": 0.2,
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}],
    }
    disable = os.getenv("LLM_DISABLE_THINKING", "1") != "0"
    try:
        resp = (
            client.chat.completions.create(**kwargs, extra_body={"thinking": {"type": "disabled"}})
            if disable
            else client.chat.completions.create(**kwargs)
        )
    except Exception:  # noqa: BLE001
        resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content.strip()


def ask(
    question: str,
    include_tables: list[str] | None = None,
    max_retries: int = MAX_RETRIES,
    want_conclusion: bool = True,
    enable_guard: bool = True,
) -> dict:
    """完整跑一遍：返回 {status, sql, result, conclusion, caliber_ok, ...}。

    重试循环里同时消化两类反馈：
    - 静态校验失败 → "SQL 报错在哪一层"（安全 / 语法 / schema）
    - 口径断言失败 → "结果哪一列口径错了"（caliber_guard 的结构化反馈）
    两者共用同一份重试预算，因此模型是"改到对为止"而不是"跑通就交"。
    """
    schema_text = build_schema_context(include_tables)

    sql = None
    verdict = None
    feedback = None
    attempts = 0
    best = None  # 最近一次"静态校验通过"的产物： (sql, result, violations, warnings)
    last_error = None  # 最后一次失败原因，用于全败时如实汇报
    last_layer = None

    for _ in range(max_retries + 1):
        attempts += 1
        sql = _strip_fence(generate_sql(question, schema_text, error_feedback=feedback))

        # 第 0 层：模型没给 SQL（拒答 / 说明性自然语言）。
        # 这类输出**不该被当成"SQL 校验失败"去重试** —— 它没说 SQL 错，它说"答不了"。
        # 明确拒答 → 立即收；只是格式走神 → 给一次纠正机会。
        if not _looks_like_sql(sql):
            if _is_refusal(sql) or attempts > 1:
                return {
                    "question": question,
                    "status": "unanswerable",
                    "attempts": attempts,
                    "sql": None,
                    "answer": _refusal_text(sql),
                    "error": "现有表结构无法回答该问题（模型给出说明而非 SQL）",
                    "layer": "unanswerable",
                    "caliber_ok": None,
                    "caliber_violations": [],
                    "conclusion": None,
                }
            feedback = (
                "你上一次输出的不是 SQL，而是一段自然语言说明。请二选一：\n"
                "① 现有表结构能回答 → 只输出一条 SELECT / WITH 查询，不要任何解释；\n"
                f"② 确实无法回答（表或字段不存在）→ 只输出一行 `{CANNOT_ANSWER_MARKER}: <简短原因>`。"
            )
            last_error, last_layer = "模型未输出 SQL", "unanswerable"
            continue

        verdict = validate(sql, schema_text)
        if not verdict["ok"]:
            feedback = f"SQL：\n{sql}\n错误：{verdict['error']}（校验层级：{verdict['layer']}）"
            last_error, last_layer = verdict["error"], verdict["layer"]
            continue
        # 第 3.5 层：执行反馈。EXPLAIN 只做解析/优化，**不真正执行**，
        # 所以"语法合法但跑不出来"的错误（标量子查询返回多行、超时 3024 等）
        # 只能在这里暴露。必须回灌重试，不能让异常穿透把整个 Agent 打崩。
        try:
            result = execute(sql)
        except Exception as exc:  # noqa: BLE001
            feedback = f"SQL：\n{sql}\n执行失败：{exc}（校验层级：execution）"
            last_error, last_layer = str(exc), "execution"
            continue
        violations = check_caliber(question, sql, result) if enable_guard else []
        best = (sql, result, violations, verdict["warnings"])
        if not violations:
            break
        feedback = format_feedback(sql, violations)
        last_error = "; ".join(str(v) for v in violations)
        last_layer = "caliber"

    if best is None:  # 一次都没通过静态校验 + 执行
        return {
            "question": question,
            "status": "failed",
            "attempts": attempts,
            "sql": sql,
            "error": last_error or (verdict["error"] if verdict else "未生成 SQL"),
            "layer": last_layer,
            "caliber_ok": False,
            "caliber_violations": [],
        }

    sql, result, violations, warnings = best
    conclusion = None
    if want_conclusion:
        try:
            conclusion = _summarize(question, sql, result)
        except Exception as exc:  # noqa: BLE001
            conclusion = f"（结论生成失败：{exc}）"

    return {
        "question": question,
        "status": "ok",
        "attempts": attempts,
        "sql": sql,
        "warnings": warnings,
        "row_count": result["row_count"],
        "caliber_ok": not violations,
        "caliber_violations": [str(v) for v in violations],
        "conclusion": conclusion,
        "result": result,
    }


def _load_questions() -> list[dict]:
    import importlib.util

    path = ROOT / "01_data" / "questions.py"
    spec = importlib.util.spec_from_file_location("questions", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.QUESTIONS


if __name__ == "__main__":
    load_env()
    if len(sys.argv) > 1:
        out = ask(" ".join(sys.argv[1:]))
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print("未传问题，跑通 10 个业务问题（需已配置 .env 中的数据库与 API Key）\n")
        for q in _load_questions():
            print(f"Q{q['id']} {q['title']}")
            try:
                out = ask(q["question"])
                tag = "OK " if out["status"] == "ok" else "ERR"
                print(f"  [{tag}] {out.get('sql','')[:110]}")
                if out.get("conclusion"):
                    print(f"  结论：{out['conclusion']}")
            except Exception as exc:  # noqa: BLE001
                print(f"  [ERR] {exc}")
            print()
