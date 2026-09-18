"""共享数据库连接工具（读取 .env / 环境变量）。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    """极简 .env 读取，避免额外依赖。"""
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
