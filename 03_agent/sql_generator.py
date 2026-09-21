"""调用 LLM 生成 SQL（temperature=0 保证稳定）。

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


def generate_sql(
    question: str,
    schema_text: str,
    error_feedback: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
) -> str:
    client = _client()
    model = model or os.getenv("OPENAI_MODEL", "gpt-4o")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(question, schema_text, error_feedback)},
    ]
    kwargs = {"model": model, "temperature": temperature, "max_tokens": 1024, "messages": messages}
    # 关闭 GLM 深度思考以大幅提速；端点不支持该参数时自动回退
    disable = os.getenv("LLM_DISABLE_THINKING", "1") != "0"
    try:
        resp = (
            client.chat.completions.create(**kwargs, extra_body={"thinking": {"type": "disabled"}})
            if disable
            else client.chat.completions.create(**kwargs)
        )
    except Exception:  # noqa: BLE001
        resp = client.chat.completions.create(**kwargs)
    return _clean(resp.choices[0].message.content)
