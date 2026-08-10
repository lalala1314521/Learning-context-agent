"""依赖注入：数据库初始化与 LangGraph 图实例。"""

from app.graph.builder import build_graph
from app.memory.database import init_db

_graph = None


def ensure_database() -> None:
    init_db()


def get_graph():
    """惰性创建并复用编译后的 LangGraph 图。"""
    global _graph
    if _graph is None:
        ensure_database()
        _graph = build_graph()
    return _graph
