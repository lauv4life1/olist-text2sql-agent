"""
import_data.py — 一键导入 Olist CSV 数据到 MySQL

用法：
    python 01_data/import_data.py

功能：
    1. 从 config.yaml / .env 读取配置
    2. 创建数据库（如不存在）
    3. 建表 + 导入 9 张 CSV
    4. 验证行数

首次使用或 Docker 初始化时运行。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pymysql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "03_agent"))
from db import load_env  # noqa: E402

# CSV 文件名 → MySQL 表名
TABLE_MAPPING = {
    "olist_orders_dataset.csv": "orders",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "order_payments",
    "olist_customers_dataset.csv": "customers",
    "olist_products_dataset.csv": "products",
    "olist_sellers_dataset.csv": "sellers",
    "olist_order_reviews_dataset.csv": "order_reviews",
    "product_category_name_translation.csv": "product_category_name_translation",
    "olist_geolocation_dataset.csv": "geolocation",
}

# 可选：跳过不需要的大表（geolocation 100万行，10个问题未用到）
SKIP_TABLES = set(os.getenv("SKIP_TABLES", "").split(",")) - {""}


def _get_csv_dir() -> Path:
    """从 config.yaml 或环境变量获取 CSV 目录。"""
    try:
        import yaml
        config_path = ROOT / "config.yaml"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            csv_dir = cfg.get("data", {}).get("csv_dir", "")
            if csv_dir:
                return Path(csv_dir)
    except Exception:
        pass

    # 回退：项目根目录下的 data/
    for candidate in [ROOT / "data", ROOT / "01_data" / "csv"]:
        if candidate.exists():
            return candidate

    print("错误：找不到 CSV 目录。请在 config.yaml 中设置 data.csv_dir，")
    print("或将 CSV 文件放到 data/ 目录下。")
    sys.exit(1)


def _connect(database: str | None = None):
    load_env()
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=database,
        charset="utf8mb4",
    )


def create_database():
    db_name = os.getenv("MYSQL_DATABASE", "olist_ecommerce")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        print(f"[OK] 数据库 {db_name} 已就绪")
    finally:
        conn.close()


def import_tables(csv_dir: Path):
    db_name = os.getenv("MYSQL_DATABASE", "olist_ecommerce")
    conn = _connect(database=db_name)
    batch_size = int(os.getenv("IMPORT_BATCH_SIZE", "5000"))

    try:
        for csv_file, table_name in TABLE_MAPPING.items():
            if table_name in SKIP_TABLES:
                print(f"[SKIP] {table_name}")
                continue

            csv_path = csv_dir / csv_file
            if not csv_path.exists():
                print(f"[WARN] 文件不存在，跳过: {csv_file}")
                continue

            df = pd.read_csv(csv_path)
            print(f"  导入 {table_name} ({len(df):,} 行)...", end=" ", flush=True)

            _import_with_pymysql(conn, df, table_name, batch_size)
            print("[OK]")

        conn.commit()
    finally:
        conn.close()


def _import_with_pymysql(conn, df: pd.DataFrame, table_name: str, batch_size: int):
    """纯 pymysql 批量插入。"""
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS `{table_name}`")

        cols = []
        for col_name, dtype in df.dtypes.items():
            dtype_str = str(dtype)
            if "int" in dtype_str:
                mysql_type = "BIGINT"
            elif "float" in dtype_str:
                mysql_type = "DOUBLE"
            else:
                mysql_type = "TEXT"
            cols.append(f"`{col_name}` {mysql_type}")

        create_sql = (
            f"CREATE TABLE `{table_name}` ({', '.join(cols)}) "
            "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        cur.execute(create_sql)

        placeholders = ", ".join(["%s"] * len(df.columns))
        insert_sql = f"INSERT INTO `{table_name}` VALUES ({placeholders})"
        rows = df.where(df.notna(), None).values.tolist()

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            cur.executemany(insert_sql, batch)


def verify():
    db_name = os.getenv("MYSQL_DATABASE", "olist_ecommerce")
    conn = _connect(database=db_name)
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = [row[0] for row in cur.fetchall()]
            print(f"\n{'='*50}")
            print("验证导入结果")
            print(f"{'='*50}")
            for table in sorted(tables):
                cur.execute(f"SELECT COUNT(*) FROM `{table}`")
                count = cur.fetchone()[0]
                print(f"  {table}: {count:,} 行")
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 50)
    print("Olist 数据导入")
    print("=" * 50)

    load_env()
    csv_dir = _get_csv_dir()
    print(f"CSV 目录: {csv_dir}\n")

    create_database()
    import_tables(csv_dir)
    verify()

    print(f"\n{'='*50}")
    print("导入完成！")
    print(f"{'='*50}")
