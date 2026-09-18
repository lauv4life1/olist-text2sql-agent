"""3 层 SQL 校验：安全 → 语法 → schema 匹配。

设计决策（面试考点）：防止 LLM 幻觉生成错误/危险 SQL。
校验失败返回错误信息，Agent 会把它回传给 LLM 触发自我修正重试。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_connection  # noqa: E402

# 第 1 层：危险关键字黑名单
_FORBIDDEN = {
    "insert", "update", "delete", "drop", "alter", "truncate", "create",
    "replace", "grant", "revoke", "rename", "call", "execute", "handler",
    "load_file", "outfile", "dumpfile", "information_schema",
    "performance_schema", "mysql",
    # 显式锁子句：只读会话里不该出现。注意 "for update" 之所以会被拦，
    # 纯粹是因为它含有 update 这个单词（巧合），"lock in share mode" / "for share"
    # 则完全不含黑名单词 —— 必须显式登记，不能靠巧合。
    "lock in share mode", "for share", "get_lock", "release_lock",
    # 空转函数：会被 MAX_EXECUTION_TIME 掐断（SLEEP 中断时返回 1），
    # 但没必要给模型留这个口子
    "sleep", "benchmark",
}

# sql 关键字/函数白名单（做 schema 匹配时用于排除误报）
_SQL_WORDS = {
    "select", "from", "join", "inner", "left", "right", "full", "outer", "on",
    "where", "group", "by", "having", "order", "asc", "desc", "limit", "offset",
    "as", "and", "or", "not", "in", "is", "null", "between", "like", "case",
    "when", "then", "else", "end", "distinct", "count", "sum", "avg", "min",
    "max", "round", "date_format", "datediff", "timestampdiff", "day", "month",
    "year", "lag", "lead", "row_number", "rank", "dense_rank", "ntile",
    "over", "partition", "with", "union", "all", "cast", "convert", "coalesce",
    "ifnull", "nullif", "floor", "ceil", "abs", "concat", "substr", "extract",
    "interval", "current_date", "now", "true", "false", "using", "exists",
}


def _strip_literals(sql: str) -> str:
    """去掉字符串字面量和注释，避免误判。"""
    sql = re.sub(r"'([^']|'')*'", " ", sql)
    sql = re.sub(r'"([^"]|"")*"', " ", sql)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return sql


def _check_safety(sql: str) -> str | None:
    """第 1 层：安全。"""
    body = _strip_literals(sql).strip().rstrip(";").strip()
    if ";" in body:
        return "检测到多条语句（分号），禁止执行"
    low = body.lower()
    if not low.startswith(("select", "with")):
        return "只允许 SELECT / WITH 查询"
    for kw in _FORBIDDEN:
        if re.search(rf"\b{re.escape(kw)}\b", low):
            return f"包含被禁止的关键字：{kw}"
    return None


def _check_syntax(sql: str) -> str | None:
    """第 2 层：语法（用 EXPLAIN 让 MySQL 解析，不真正取数）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("EXPLAIN " + sql)
            cur.fetchall()
        return None
    except Exception as exc:  # noqa: BLE001
        return f"语法/解析错误：{exc}"
    finally:
        conn.close()


def _known_objects(schema_text: str) -> tuple[set[str], set[str]]:
    """从 schema 文本解析已知表名与列名。"""
    tables: set[str] = set()
    columns: set[str] = set()
    for line in schema_text.splitlines():
        m = re.match(r"^\s*(\w+)\s*\((.*)\)\s*$", line)
        if not m:
            continue
        tables.add(m.group(1).lower())
        for col in m.group(2).split(","):
            col = col.strip().split()
            if col:
                columns.add(col[0].lower())
    return tables, columns


def _check_schema(sql: str, schema_text: str) -> tuple[str | None, list[str]]:
    """第 3 层：schema 匹配。未知表 → 阻断；未知标识符 → 警告。"""
    tables, columns = _known_objects(schema_text)
    if not tables:
        return None, []

    clean = _strip_literals(sql)
    # CTE 名（WITH x AS (...), y AS (...)）不是真实表，需从未知表判断中排除
    cte_names = {
        m.lower()
        for m in re.findall(r"(?:\bwith\b|,)\s*([a-zA-Z_]\w*)\s+as\s*\(", clean, flags=re.I)
    }
    refs = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][\w]*)", clean, flags=re.I)
    unknown_tables = [t for t in refs if t.lower() not in tables and t.lower() not in cte_names]
    if unknown_tables:
        return f"引用了不存在的表：{', '.join(sorted(set(unknown_tables)))}", []

    aliases = set(re.findall(r"\bas\s+([a-zA-Z_][\w]*)", clean, flags=re.I))
    aliases |= set(re.findall(r"\)\s+([a-zA-Z_][\w]*)", clean))
    # 表别名（FROM/JOIN tbl alias，无 AS 关键字）
    aliases |= set(re.findall(r"\b(?:from|join)\s+[a-zA-Z_]\w*\s+([a-zA-Z_]\w*)", clean, flags=re.I))
    warnings: list[str] = []
    for tok in set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", clean)):
        low = tok.lower()
        if low in _SQL_WORDS or low in tables or low in columns or low in aliases or low in cte_names:
            continue
        if re.match(r"^[a-zA-Z_]$", tok):  # 单字母多为表别名
            continue
        warnings.append(tok)
    return None, warnings


def validate(sql: str, schema_text: str) -> dict:
    """返回 {ok, layer, error, warnings}。"""
    err = _check_safety(sql)
    if err:
        return {"ok": False, "layer": "safety", "error": err, "warnings": []}
    err = _check_syntax(sql)
    if err:
        return {"ok": False, "layer": "syntax", "error": err, "warnings": []}
    err, warnings = _check_schema(sql, schema_text)
    if err:
        return {"ok": False, "layer": "schema", "error": err, "warnings": warnings}
    return {"ok": True, "layer": None, "error": None, "warnings": warnings}
