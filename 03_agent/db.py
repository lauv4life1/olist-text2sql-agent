"""共享数据库连接工具：连接池 + 只读用户 + config.yaml 支持。

配置优先级：环境变量 > .env > config.yaml
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 连接池（惰性初始化）
# ---------------------------------------------------------------------------
_pool = None
_pool_readonly = None


def _load_yaml_config() -> dict:
    """读取 config.yaml，扁平化为环境变量键值对。失败时返回空字典。"""
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
    for key, env_key in [
        ("host", "MYSQL_HOST"), ("port", "MYSQL_PORT"),
        ("user", "MYSQL_USER"), ("database", "MYSQL_DATABASE"),
        ("readonly_user", "MYSQL_READONLY_USER"),
        ("readonly_password", "MYSQL_READONLY_PASSWORD"),
    ]:
        if db.get(key):
            flat[env_key] = str(db[key])

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

    pool = cfg.get("pool", {})
    if pool.get("size") is not None:
        flat["MYSQL_POOL_SIZE"] = str(pool["size"])

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


def _get_pool(readonly: bool = False):
    """获取或创建连接池（需要 DBUtils）。"""
    global _pool, _pool_readonly

    load_env()

    if readonly and _pool_readonly is not None:
        return _pool_readonly
    if not readonly and _pool is not None:
        return _pool

    import pymysql
    from dbutils.pooled_db import PooledDB

    pool_size = int(os.getenv("MYSQL_POOL_SIZE", "5"))
    user = os.getenv("MYSQL_READONLY_USER") if readonly else None
    password = os.getenv("MYSQL_READONLY_PASSWORD") if readonly else None

    pool = PooledDB(
        creator=pymysql,
        maxconnections=pool_size,
        mincached=1,
        maxcached=pool_size,
        blocking=True,
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=user or os.getenv("MYSQL_USER", "root"),
        password=password if password is not None else os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "olist_ecommerce"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        read_timeout=30,
    )

    if readonly:
        _pool_readonly = pool
    else:
        _pool = pool

    return pool


def get_connection(readonly: bool = False):
    """获取数据库连接（优先从连接池，无 DBUtils 时回退普通连接）。

    readonly=True 时使用只读账号（MYSQL_READONLY_USER），
    落地"只读数据库连接"安全底线。
    """
    try:
        pool = _get_pool(readonly)
        return pool.connection()
    except ImportError:
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
