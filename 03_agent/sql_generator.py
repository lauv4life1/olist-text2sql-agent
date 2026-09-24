import time
import hashlib
from functools import lru_cache
"""调用 LLM 生成 SQL（temperature=0 保证稳定）。

n# 缓存配置
CACHE_SIZE = int(os.getenv("CACHE_SIZE", "200"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

def _get_cache_key(question: str, schema_text: str, error_feedback: str = "", model: str = "") -> str:
    """生成缓存键"""
    combined = f"{question}|{schema_text}|{error_feedback}|{model}"
    return hashlib.md5(combined.encode()).hexdigest()

@lru_cache(maxsize=CACHE_SIZE)
兼容任何 OpenAI 协议的服务：改 .env 里的 OPENAI_BASE_URL / OPENAI_MODEL 即可
（DeepSeek、通义千问兼容模式等）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import load_env  # noqa: E402
from prompt_builder import SYSTEM_PROMPT, build_prompt  # noqa: E402


def _client():
    from openai import OpenAI

    load_env()
    return OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        timeout=120,
    )


def _clean(text: str) -> str:
    """剥离 Markdown 代码块围栏与多余分号。"""
    text = (text or "").strip()
    if text.startswith("```"):
        block = text.split("```")
        text = block[1] if len(block) > 1 else text
        if text.lower().startswith("sql"):
            text = text[3:]
    return text.strip().rstrip(";").strip()


def generate_sql_cached(
    question: str,
    schema_text: str,
    error_feedback: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
) -> str:
    """带缓存的SQL生成函数"""
    start_time = time.time()
    load_env()
    
    # 生成缓存键
    cache_key = _get_cache_key(question, schema_text, error_feedback or "", model or os.getenv("OPENAI_MODEL", "gpt-4o"))
    
    # 检查缓存
    try:
        )
    except Exception:  # noqa: BLE001
        resp = client.chat.completions.create(**kwargs)
    return _clean(resp.choices[0].message.content)
