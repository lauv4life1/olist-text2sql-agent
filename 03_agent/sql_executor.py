"""只读 SQL 执行引擎：超时 30s、最多返回 1000 行。

安全底线（三重）：
  1. 语句必须以 SELECT / WITH 开头（拒绝写操作）
  2. **语句体内不允许出现分号**（拒绝堆叠多语句 —— 不能只依赖驱动是否开启
     CLIENT_MULTI_STATEMENTS，那是别人的默认值，不是我们的保证）
  3. 走只读连接（readonly=True）+ MAX_EXECUTION_TIME + 行数上限

执行期失败（**EXPLAIN 通不了它们**：EXPLAIN 只做解析/优化，不真正执行）
统一抛 SqlExecutionError，便于上层回灌重试而不是直接崩：
  - 标量子查询返回多行、运行期类型/溢出、MAX_EXECUTION_TIME 超时(3024) 等
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_connection  # noqa: E402

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_ROWS = 1000


class SqlExecutionError(RuntimeError):
    """SQL 通过了静态校验但在执行期失败（语法合法 ≠ 能跑出结果）。"""


def execute(sql: str, max_rows: int = DEFAULT_MAX_ROWS, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """执行一条只读 SQL，返回 {columns, rows, row_count, truncated}。"""
    sql = sql.strip().rstrip(";").strip()
    if not sql.lower().startswith(("select", "with")):
        raise ValueError("只允许执行 SELECT / WITH 查询")
    # 防御性：即使绕过了 sql_validator，这里也独立拦一次多语句。
    # 不依赖 PyMySQL 默认关闭 CLIENT_MULTI_STATEMENTS —— 显式比默认可靠。
    if ";" in sql:
        raise ValueError("只允许执行单条语句（检测到分号）")

    conn = get_connection(readonly=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET SESSION MAX_EXECUTION_TIME={timeout * 1000}")
            try:
                cur.execute(sql)
                rows = cur.fetchmany(max_rows + 1)  # 多取 1 行判断是否被截断
            except Exception as exc:  # noqa: BLE001
                # 语法合法但跑不出来：包成统一异常，让 agent 能回灌重试
                raise SqlExecutionError(str(exc)) from exc
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]
            columns = list(rows[0].keys()) if rows else [d[0] for d in (cur.description or [])]
        return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}
    finally:
        conn.close()
