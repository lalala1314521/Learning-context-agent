"""SQLite 数据库连接管理与初始化。"""

import sqlite3
from pathlib import Path
from app.config import config
from app.memory.models import DDL_STATEMENTS


def _load_vector_extension(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec when available; returns whether it was enabled."""
    try:
        import sqlite_vec
    except ImportError:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return True
    except Exception:
        return False


def get_connection() -> sqlite3.Connection:
    Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _load_vector_extension(conn)
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        for stmt in DDL_STATEMENTS:
            conn.execute(stmt)
        _ensure_column(conn, "graph_nodes", "node_type", "TEXT DEFAULT 'concept'")
        _ensure_column(conn, "graph_nodes", "concept_id", "TEXT")
        _ensure_column(conn, "knowledge_graphs", "parent_graph_id", "TEXT")
        _ensure_column(conn, "quiz_questions", "concept_id", "TEXT")
        _ensure_column(conn, "review_progress", "difficulty", "REAL DEFAULT 5.0")
        _ensure_column(conn, "review_progress", "stability", "REAL DEFAULT 1.0")
        _ensure_column(conn, "review_progress", "retrievability", "REAL DEFAULT 1.0")
        _ensure_column(conn, "knowledge_graphs", "structure_version", "TEXT DEFAULT 'knowledge-structure/v1'")
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
