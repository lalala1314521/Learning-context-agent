"""长期记忆快照（memory_snapshots）数据访问。"""

import json
import uuid

from app.memory.database import get_connection
from app.memory.repos.base import json_list


def save_memory_snapshot(
    graph_id: str, summary: str, key_points: list[str] | None = None,
) -> str:
    snap_id = uuid.uuid4().hex[:12]
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO memory_snapshots (id, graph_id, summary, key_points) VALUES (?, ?, ?, ?)",
            (snap_id, graph_id, summary, json.dumps(key_points or [], ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    return snap_id


def get_memory_snapshots(graph_id: str | None = None, limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        if graph_id:
            rows = conn.execute(
                "SELECT * FROM memory_snapshots WHERE graph_id = ? ORDER BY created_at DESC LIMIT ?",
                (graph_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memory_snapshots ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    finally:
        conn.close()
    results = []
    for r in rows:
        data = dict(r)
        data["key_points"] = json_list(data.get("key_points"))
        results.append(data)
    return results


def search_memories(query: str, limit: int = 10) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM memory_snapshots
               WHERE summary LIKE ? OR key_points LIKE ?
               ORDER BY created_at DESC LIMIT ?""",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    finally:
        conn.close()
    results = []
    for r in rows:
        data = dict(r)
        data["key_points"] = json_list(data.get("key_points"))
        results.append(data)
    return results
