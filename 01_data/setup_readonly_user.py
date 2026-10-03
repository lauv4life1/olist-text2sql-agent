"""
setup_readonly_user.py — 创建 MySQL 只读用户

用法：
    python 01_data/setup_readonly_user.py

运行后在 .env 中配置：
    MYSQL_READONLY_USER=readonly
    MYSQL_READONLY_PASSWORD=你设置的密码
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "03_agent"))
from db import load_env, get_connection  # noqa: E402

READONLY_USER = os.getenv("MYSQL_READONLY_USER", "readonly")
READONLY_PASSWORD = os.getenv("MYSQL_READONLY_PASSWORD", "readonly_pass_2024")
DATABASE = os.getenv("MYSQL_DATABASE", "olist_ecommerce")


def setup():
    load_env()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE USER IF NOT EXISTS '{READONLY_USER}'@'%' "
                f"IDENTIFIED BY '{READONLY_PASSWORD}'"
            )
            cur.execute(
                f"GRANT SELECT ON `{DATABASE}`.* TO '{READONLY_USER}'@'%'"
            )
            cur.execute("FLUSH PRIVILEGES")
        conn.commit()
        print(f"[OK] 只读用户已创建: {READONLY_USER}")
        print(f"[OK] 权限: SELECT ON {DATABASE}.*")
        print(f"\n请在 .env 中添加：")
        print(f"  MYSQL_READONLY_USER={READONLY_USER}")
        print(f"  MYSQL_READONLY_PASSWORD={READONLY_PASSWORD}")
    finally:
        conn.close()


def verify():
    """验证只读用户确实无法写入。"""
    import pymysql

    load_env()
    try:
        conn = pymysql.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=READONLY_USER,
            password=READONLY_PASSWORD,
            database=DATABASE,
            charset="utf8mb4",
        )
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM orders")
            count = cur.fetchone()["cnt"]
            print(f"\n[OK] SELECT 正常: orders 表 {count:,} 行")

            try:
                cur.execute("INSERT INTO orders (order_id) VALUES ('test')")
                print("[FAIL] INSERT 竟然成功了！权限配置有误！")
            except pymysql.err.OperationalError as e:
                print(f"[OK] INSERT 被拒绝（预期行为）: {e}")

        conn.close()
    except Exception as e:
        print(f"[ERROR] 连接失败: {e}")


if __name__ == "__main__":
    setup()
    verify()
