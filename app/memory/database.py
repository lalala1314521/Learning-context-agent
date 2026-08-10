"""SQLite 数据库连接管理与初始化。"""

import sqlite3
from pathlib import Path
from app.config import config
from app.memory.models import DDL_STATEMENTS


def get_connection() -> sqlite3.Connection:
    Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        for stmt in DDL_STATEMENTS:
            conn.execute(stmt)
        _ensure_column(conn, "graph_nodes", "node_type", "TEXT DEFAULT 'concept'")
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def get_checkpointer():
    from langgraph.checkpoint.sqlite import SqliteSaver
    return SqliteSaver(get_connection())
