"""SQL 生成器的边界与缓存行为测试（不需要 DB、不需要 API Key）。

所有 LLM 调用一律 mock —— 与项目既有测试同一原则：CI 零网络、零成本。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "03_agent"))

import sql_generator  # noqa: E402
from sql_generator import _clean, generate_sql_cached  # noqa: E402


def _mock_client(content: str = "SELECT 1"):
    client = MagicMock()
    resp = MagicMock()
    resp.choices[0].message.content = content
    client.chat.completions.create.return_value = resp
    return client


class TestClean(unittest.TestCase):
    """_clean：剥离 Markdown 围栏与多余分号"""

    def test_plain_sql(self):
        self.assertEqual(_clean("SELECT 1;"), "SELECT 1")

    def test_fenced_sql(self):
        self.assertEqual(_clean("```sql\nSELECT 1;\n```"), "SELECT 1")

    def test_empty_input(self):
        self.assertEqual(_clean(""), "")


class TestGenerateSqlCached(unittest.TestCase):
    """缓存行为：同一参数组合只调一次 LLM"""

    def setUp(self):
        generate_sql_cached.cache_clear()

    def tearDown(self):
        generate_sql_cached.cache_clear()

    def test_cache_hit_avoids_second_llm_call(self):
        client = _mock_client()
        with patch.object(sql_generator, "_client", return_value=client):
            r1 = generate_sql_cached("缓存问题甲", "schema_a")
            r2 = generate_sql_cached("缓存问题甲", "schema_a")
        self.assertEqual(r1, r2)
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_different_question_cache_miss(self):
        client = _mock_client()
        with patch.object(sql_generator, "_client", return_value=client):
            generate_sql_cached("缓存问题乙一", "schema_b")
            generate_sql_cached("缓存问题乙二", "schema_b")
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_error_feedback_participates_in_cache_key(self):
        client = _mock_client()
        with patch.object(sql_generator, "_client", return_value=client):
            generate_sql_cached("缓存问题丙", "schema_c", error_feedback=None)
            generate_sql_cached("缓存问题丙", "schema_c", error_feedback="上次错了")
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_boundary_inputs_do_not_crash(self):
        client = _mock_client()
        with patch.object(sql_generator, "_client", return_value=client):
            r1 = generate_sql_cached("很长" * 500, "schema_d")
            r2 = generate_sql_cached("!@#$%^&*()\"'", "schema_d")
        self.assertIsInstance(r1, str)
        self.assertIsInstance(r2, str)

    def test_llm_error_propagates_and_not_cached(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("boom")
        with patch.object(sql_generator, "_client", return_value=client):
            with self.assertRaises(Exception):
                generate_sql_cached("缓存问题戊", "schema_e")
            # 异常不进缓存：换正常 client 后同参数应能成功
            with patch.object(sql_generator, "_client", return_value=_mock_client()):
                self.assertEqual(generate_sql_cached("缓存问题戊", "schema_e"), "SELECT 1")


if __name__ == "__main__":
    unittest.main()
