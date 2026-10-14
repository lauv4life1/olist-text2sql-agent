"""A/B 测试统计模块的单测（纯数学，CI 零依赖）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "03_agent"))

from ab_test import conversion_ztest, required_sample_size  # noqa: E402


class TestConversionZtest(unittest.TestCase):
    def test_small_sample_not_significant(self):
        """10% vs 12% 各1000人：看着有差异，其实 p≈0.15 不显著（教学核心案例）。"""
        r = conversion_ztest(100, 1000, 120, 1000)
        self.assertFalse(r["significant"])
        self.assertGreater(r["p_value"], 0.05)

    def test_large_sample_significant(self):
        """同样 10% vs 12% 但各1万人：样本够大就显著了。"""
        r = conversion_ztest(1000, 10000, 1200, 10000)
        self.assertTrue(r["significant"])
        self.assertLess(r["p_value"], 0.05)

    def test_identical_groups_p_is_one(self):
        r = conversion_ztest(500, 5000, 500, 5000)
        self.assertAlmostEqual(r["p_value"], 1.0, places=4)
        self.assertFalse(r["significant"])

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            conversion_ztest(10, 0, 10, 100)
        with self.assertRaises(ValueError):
            conversion_ztest(200, 100, 10, 100)  # 转化数>样本量


class TestSampleSize(unittest.TestCase):
    def test_typical_case_in_textbook_range(self):
        """基线10%、检出2pp提升 → 每组约3800+，教科书量级。"""
        n = required_sample_size(0.10, 0.02)
        self.assertTrue(3000 < n < 5000, f"样本量异常: {n}")

    def test_smaller_mde_needs_more_samples(self):
        self.assertGreater(required_sample_size(0.10, 0.01),
                           required_sample_size(0.10, 0.02))

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            required_sample_size(1.5, 0.02)
        with self.assertRaises(ValueError):
            required_sample_size(0.10, -0.01)


if __name__ == "__main__":
    unittest.main()
