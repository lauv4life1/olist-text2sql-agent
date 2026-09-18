"""安全 / 执行边界 + 执行期回灌 的回归测试（**不需要 DB、不需要 API Key**）。

来源：`03_agent/stress_test.py` 高压测试实测出的缺口，全部固化为回归用例。

三个真实缺口（2026-09-18 高压测试发现）：
  ① `sql_executor` 只靠"startswith('select')"判只读 —— `SELECT 1; DROP TABLE orders`
     能过自己的检查，全靠 PyMySQL 默认没开 CLIENT_MULTI_STATEMENTS 才没炸。
     → 修：执行器自己也显式拒绝分号（防御性，不依赖别人的默认值）。
  ② `LOCK IN SHARE MODE` / `FOR SHARE` 完全不含黑名单词，能过安全层；
     而 `FOR UPDATE` 被拦纯属它含 "update" 这个单词的巧合。
     → 修：把锁子句 / 空转函数显式登记进黑名单。
  ③ `agent.ask()` 没有包 `execute()` 的异常 —— EXPLAIN 只解析不执行，
     "语法合法但跑不出来"（标量子查询返回多行、超时 3024）会直接穿透把 Agent 打崩。
     → 修：执行期异常按 "第 3.5 层" 的结构化反馈回灌重试。

运行： python -m unittest discover -s 03_agent/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "03_agent"))

from sql_executor import SqlExecutionError, execute  # noqa: E402
from sql_validator import validate  # noqa: E402

# 虚拟 schema：安全层命中后会立刻返回，永远不会解析它 —— 所以不碰 DB
DUMMY_SCHEMA = "orders(order_id, customer_id)\n"

BLOCKED_SQL = [
    # 破坏性语句
    "DELETE FROM orders",
    "DROP TABLE orders",
    "UPDATE orders SET order_status='canceled'",
    "TRUNCATE TABLE order_items",
    "INSERT INTO orders (order_id) VALUES ('x')",
    "ALTER TABLE orders ADD COLUMN hack INT",
    "CREATE TABLE pwn (id INT)",
    "GRANT ALL ON *.* TO 'x'@'%'",
    # 大小写 / 注释 / 换行混淆
    "DeLeTe/**/FROM orders",
    "delete\nfrom orders",
    "-- 无害注释\nDELETE FROM orders",
    "/* block */ dRoP TABLE orders",
    # 多语句 / 堆叠注入
    "SELECT 1; DROP TABLE orders",
    "SELECT order_id FROM orders; DELETE FROM orders",
    # 敏感系统库
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM mysql.user",
    "SELECT * FROM performance_schema.session_variables",
    # 文件读写
    "SELECT LOAD_FILE('/etc/passwd')",
    "SELECT * FROM orders INTO OUTFILE '/tmp/leak.csv'",
    # 锁子句（缺口 ② 的回归）
    "SELECT * FROM orders FOR UPDATE",
    "SELECT * FROM orders LOCK IN SHARE MODE",
    "SELECT * FROM orders FOR SHARE",
    # 空转函数
    "SELECT SLEEP(60)",
    "SELECT BENCHMARK(10000000, MD5('a'))",
]

# 执行器直调必须拒绝（即使绕过了 validator）
EXECUTOR_REJECT = [
    "DELETE FROM orders",
    "DROP TABLE orders",
    "SHOW TABLES",                     # 不是 SELECT/WITH
    "SELECT 1; DROP TABLE orders",     # 缺口 ① 的回归：分号
]


class TestSafetyLayer(unittest.TestCase):
    """第 1 层安全：攻击性 SQL 必须在静态阶段就被挡住。"""

    def test_all_blocked(self):
        for sql in BLOCKED_SQL:
            with self.subTest(sql=sql):
                v = validate(sql, DUMMY_SCHEMA)
                self.assertFalse(v["ok"], f"未拦住：{sql}")
                self.assertEqual(v["layer"], "safety", f"拦错层级：{sql} -> {v['layer']}")
                self.assertIsNotNone(v["error"])


class TestExecutorBoundary(unittest.TestCase):
    """执行器自身的底线：不依赖驱动默认值，显式拒绝写操作与多语句。"""

    def test_rejects_write_and_multi_statement(self):
        for sql in EXECUTOR_REJECT:
            with self.subTest(sql=sql):
                with self.assertRaises(ValueError):
                    execute(sql)

    def test_multi_statement_not_relying_on_driver(self):
        """分号拦截必须是执行器**自己的**判断（ValueError），
        而不是让 MySQL 报 1064（ProgrammingError）。"""
        with self.assertRaises(ValueError):
            execute("SELECT 1; DROP TABLE orders")

    def test_exception_type_exists(self):
        self.assertTrue(issubclass(SqlExecutionError, RuntimeError))


class TestExecutionFeedback(unittest.TestCase):
    """第 3.5 层：执行期异常必须回灌重试，不能把 Agent 打崩。"""

    def setUp(self):
        import agent

        self.agent = agent
        self._orig = {
            k: getattr(agent, k)
            for k in ("build_schema_context", "generate_sql", "validate",
                      "execute", "check_caliber")
        }
        agent.build_schema_context = lambda include=None: DUMMY_SCHEMA
        agent.validate = lambda sql, schema: {
            "ok": True, "layer": None, "error": None, "warnings": []
        }
        agent.check_caliber = lambda q, sql, r: []

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(self.agent, k, v)

    def test_execution_error_is_backfilled_and_recovers(self):
        """第 1 次执行抛错 → 回灌 → 第 2 次成功。"""
        seen: list[str | None] = []
        calls = {"n": 0}

        def fake_generate(q, schema, error_feedback=None):
            seen.append(error_feedback)
            calls["n"] += 1
            return "SELECT (SELECT order_id FROM orders LIMIT 5)" if calls["n"] == 1 else "SELECT 1"

        def fake_execute(sql):
            if "LIMIT 5" in sql:
                raise SqlExecutionError("(1242, 'Subquery returns more than 1 row')")
            return {"columns": ["c"], "rows": [{"c": 1}], "row_count": 1, "truncated": False}

        self.agent.generate_sql = fake_generate
        self.agent.execute = fake_execute

        out = self.agent.ask("随便问问", want_conclusion=False)

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["attempts"], 2, "应在同一份重试预算内救回")
        self.assertTrue(out["caliber_ok"])
        self.assertIn("执行失败", seen[1] or "", "回灌内容必须说明是执行期失败")
        self.assertIn("execution", seen[1] or "", "回灌内容必须标注层级")

    def test_persistent_execution_error_does_not_crash(self):
        """执行一直失败 → 如实返回 failed + layer=execution，绝不抛异常。"""
        self.agent.generate_sql = lambda q, s, error_feedback=None: "SELECT bad"
        self.agent.execute = lambda sql: (_ for _ in ()).throw(
            SqlExecutionError("(3024, 'max statement execution time exceeded')")
        )

        out = self.agent.ask("随便问问", want_conclusion=False)

        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["layer"], "execution")
        self.assertIn("3024", out["error"])
        self.assertFalse(out["caliber_ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
