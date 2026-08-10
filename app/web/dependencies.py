"""依赖注入：数据库初始化与 LangGraph 图实例。"""

from app.graph.builder import build_graph
from app.memory.database import get_checkpointer, init_db

_graph = None


def ensure_database() -> None:
    init_db()


def get_graph():
    """惰性创建并复用编译后的 LangGraph 图（带 SQLite checkpointer，支持多轮会话）。

    Web 端按 thread_id 维护会话状态；前端未传 thread_id 时由端点生成，
    此时每次调用为独立会话。
    """
    global _graph
    if _graph is None:
        ensure_database()
        _graph = build_graph(checkpointer=get_checkpointer())
    return _graph
