"""共享数据库连接工具（读取 config.yaml / .env / 环境变量）。

配置优先级：环境变量 > .env > config.yaml
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml_config() -> dict:
    """读取 config.yaml，返回扁平化的配置字典。失败时返回空字典。"""
    config_path = ROOT / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return {}

    # 扁平化：database.host -> MYSQL_HOST, llm.model -> OPENAI_MODEL 等
    flat: dict[str, str] = {}
    db = cfg.get("database", {})
    if db.get("host"):
        flat["MYSQL_HOST"] = str(db["host"])
    if db.get("port"):
        flat["MYSQL_PORT"] = str(db["port"])
    if db.get("user"):
        flat["MYSQL_USER"] = str(db["user"])
    if db.get("database"):
        flat["MYSQL_DATABASE"] = str(db["database"])

    llm = cfg.get("llm", {})
    if llm.get("model"):
        flat["OPENAI_MODEL"] = str(llm["model"])
    if llm.get("temperature") is not None:
        flat["TEMPERATURE"] = str(llm["temperature"])
    if llm.get("max_retries") is not None:
        flat["MAX_RETRIES"] = str(llm["max_retries"])

    executor = cfg.get("executor", {})
    if executor.get("timeout") is not None:
        flat["SQL_EXECUTOR_TIMEOUT"] = str(executor["timeout"])
    if executor.get("max_rows") is not None:
        flat["SQL_MAX_ROWS"] = str(executor["max_rows"])

    return flat


def load_env() -> None:
    """按优先级加载配置：环境变量 > .env > config.yaml。

    环境变量已有值的不会被覆盖（setdefault 语义）。
    """
    # 1. 先加载 config.yaml 作为底层默认值
    for key, value in _load_yaml_config().items():
        os.environ.setdefault(key, value)

    # 2. 再加载 .env（覆盖 config.yaml 的同名项）
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def get_connection(readonly: bool = False):
    """获取 MySQL 连接。

    readonly=True 时优先使用 MYSQL_READONLY_USER/PASSWORD（只读账号），
    这是"只读数据库连接"安全底线的落地方式——生产上应给该账号只授 SELECT 权限。
    """
    import pymysql

    load_env()
    user = os.getenv("MYSQL_READONLY_USER") if readonly else None
    password = os.getenv("MYSQL_READONLY_PASSWORD") if readonly else None

    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=user or os.getenv("MYSQL_USER", "root"),
        password=password if password is not None else os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "olist_ecommerce"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        read_timeout=30,
    )
