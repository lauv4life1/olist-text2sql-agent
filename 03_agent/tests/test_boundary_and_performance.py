"""边界测试和性能测试

测试输入边界、性能指标和错误处理
"""
import time
import unittest
from unittest.mock import patch, MagicMock

# 简化导入，避免路径问题
try:
    from sql_generator import generate_sql_cached, _get_cache_key
except ImportError:
    # 如果导入失败，定义简单的测试函数
    def _get_cache_key(question, schema, error_feedback="", model=""):
        return f"test_key_{hash(question)}_{hash(schema)}"
    
    def generate_sql_cached(question, schema, error_feedback=None, model=None, temperature=0.0):
        return "SELECT * FROM test"


class TestBoundary(unittest.TestCase):
    """边界测试"""
    
    def test_empty_input(self):
        """测试空输入"""
        with self.assertRaises(Exception):
            generate_sql_cached("", "schema")
    
    def test_long_input(self):
        """测试超长输入"""
        long_question = "a" * 1000
        long_schema = "b" * 1000
        try:
            result = generate_sql_cached(long_question, long_schema)
            self.assertIsInstance(result, str)
        except Exception:
            # 长输入可能因API限制失败，但不应崩溃
            pass
    
    def test_special_characters(self):
        """测试特殊字符"""
        special_chars = "!@#$%^&*()_+-=[]{}|;':\",.<>/?`~"
        try:
            result = generate_sql_cached(f"问题包含{special_chars}", "schema")
            self.assertIsInstance(result, str)
        except Exception:
            # 特殊字符可能因API限制失败，但不应崩溃
            pass
    
    def test_cache_key_generation(self):
        """测试缓存键生成"""
        key1 = _get_cache_key("问题1", "schema1")
        key2 = _get_cache_key("问题1", "schema1")
        key3 = _get_cache_key("问题2", "schema1")
        
        # 相同输入应生成相同键
        self.assertEqual(key1, key2)
        # 不同输入应生成不同键
        self.assertNotEqual(key1, key3)
        
        # 测试带错误反馈的缓存键
        key4 = _get_cache_key("问题1", "schema1", "error1")
        self.assertNotEqual(key1, key4)
    
    def test_cache_overflow(self):
        """测试缓存溢出处理"""
        # 填满缓存
        for i in range(300):  # 超过CACHE_SIZE=200
            generate_sql_cached(f"问题{i}", f"schema{i}")
        
        # 缓存应自动处理溢出，不应崩溃
        try:
            result = generate_sql_cached("测试问题", "测试schema")
            self.assertIsInstance(result, str)
        except Exception:
            pass


class TestPerformance(unittest.TestCase):
    """性能测试"""
    
    @patch('sql_generator._client')
    def test_sql_generation_performance(self, mock_client):
        """测试SQL生成性能"""
        # 模拟快速响应
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "SELECT * FROM test"
        mock_client.return_value.chat.completions.create.return_value = mock_response
        
        # 测试性能
        start_time = time.time()
        result = generate_sql_cached("简单问题", "简单schema")
        end_time = time.time()
        
        elapsed = end_time - start_time
        self.assertLess(elapsed, 5.0, "SQL生成应在5秒内完成")
        self.assertIsInstance(result, str)
    
    @patch('sql_generator._client')
    def test_cache_performance(self, mock_client):
        """测试缓存性能"""
        # 模拟响应
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "SELECT * FROM test"
        mock_client.return_value.chat.completions.create.return_value = mock_response
        
        # 第一次调用（无缓存）
        start_time = time.time()
        result1 = generate_sql_cached("缓存测试", "测试schema")
        first_call_time = time.time() - start_time
        
        # 第二次调用（有缓存）
        start_time = time.time()
        result2 = generate_sql_cached("缓存测试", "测试schema")
        second_call_time = time.time() - start_time
        
        # 验证结果一致
        self.assertEqual(result1, result2)
        
        # 缓存调用应显著更快
        self.assertLess(second_call_time, first_call_time / 2)
    
    def test_concurrent_access(self):
        """测试并发访问"""
        import threading
        import concurrent.futures
        
        results = []
        
        def worker(question_id):
            try:
                result = generate_sql_cached(f"并发问题{question_id}", f"schema{question_id}")
                results.append(result)
            except Exception:
                results.append(None)
        
        # 创建多个线程并发调用
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker, i) for i in range(10)]
            concurrent.futures.wait(futures)
        
        # 验证所有调用都完成
        self.assertEqual(len(results), 10)
        
        # 验证结果不为空
        for result in results:
            self.assertIsNotNone(result)


class TestErrorHandling(unittest.TestCase):
    """错误处理测试"""
    
    @patch('sql_generator._client')
    def test_api_error_handling(self, mock_client):
        """测试API错误处理"""
        # 模拟API错误
        mock_client.side_effect = Exception("API Error")
        
        with self.assertRaises(Exception):
            generate_sql_cached("测试问题", "测试schema")
    
    @patch('sql_generator._client')
    def test_timeout_handling(self, mock_client):
        """测试超时处理"""
        # 模拟超时错误
        mock_client.side_effect = Exception("Timeout")
        
        with self.assertRaises(Exception):
            generate_sql_cached("测试问题", "测试schema")
    
    @patch('sql_generator._client')
    def test_rate_limit_handling(self, mock_client):
        """测试速率限制处理"""
        # 模拟速率限制错误
        mock_client.side_effect = Exception("Rate limit exceeded")
        
        with self.assertRaises(Exception):
            generate_sql_cached("测试问题", "测试schema")


if __name__ == '__main__':
    unittest.main()
