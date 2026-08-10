"""Repository 层：知识脉络与记忆快照的 CRUD 操作。"""

import json
import uuid
from datetime import datetime

from app.memory.database import get_connection


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def create_graph(
    title: str,
    description: str = "",
    graph_type: str = "auto",
    mermaid_code: str = "",
    markdown_outline: str = "",
    raw_content: str = "",
    source_type: str = "",
    source_name: str = "",
    tags: list[str] | None = None,
) -> str:
    graph_id = uuid.uuid4().hex[:12]
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO knowledge_graphs (id, title, description, graph_type,
               mermaid_code, markdown_outline, raw_content, source_type, source_name, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (graph_id, title, description, graph_type,
             mermaid_code, markdown_outline, raw_content, source_type, source_name,
             json.dumps(tags or [], ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    return graph_id


def get_graph(graph_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM knowledge_graphs WHERE id = ?", (graph_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    data = dict(row)
    data["tags"] = _json_list(data.get("tags"))
    return data


def update_graph(graph_id: str, **kwargs) -> bool:
    allowed = {"title", "description", "graph_type", "mermaid_code",
               "markdown_outline", "raw_content", "source_type", "source_name", "tags"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    updates["updated_at"] = datetime.now().isoformat()
    if "tags" in updates and isinstance(updates["tags"], list):
        updates["tags"] = json.dumps(updates["tags"], ensure_ascii=False)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE knowledge_graphs SET {set_clause} WHERE id = ?",
            (*updates.values(), graph_id),
        )
        conn.commit()
    finally:
        conn.close()
    return True


def search_graphs(query: str = "", limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        if query:
            rows = conn.execute(
                """SELECT * FROM knowledge_graphs
                   WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?
                      OR markdown_outline LIKE ? OR mermaid_code LIKE ?
                      OR raw_content LIKE ?
                   ORDER BY updated_at DESC LIMIT ?""",
                (
                    f"%{query}%", f"%{query}%", f"%{query}%",
                    f"%{query}%", f"%{query}%", f"%{query}%", limit,
                ),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_graphs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    finally:
        conn.close()
    results = []
    for r in rows:
        data = dict(r)
        data["tags"] = _json_list(data.get("tags"))
        results.append(data)
    return results


def search_nodes(query: str, limit: int = 30) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT n.*, g.title AS graph_title
               FROM graph_nodes n
               JOIN knowledge_graphs g ON g.id = n.graph_id
               WHERE n.label LIKE ? OR n.note LIKE ?
               ORDER BY n.created_at DESC LIMIT ?""",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    finally:
        conn.close()
    results = []
    for r in rows:
        data = dict(r)
        data["related_nodes"] = _json_list(data.get("related_nodes"))
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
        data["key_points"] = _json_list(data.get("key_points"))
        results.append(data)
    return results


def list_graphs(limit: int = 50) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, title, description, graph_type, source_type,
               source_name, tags, created_at, updated_at
               FROM knowledge_graphs ORDER BY updated_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    results = []
    for r in rows:
        data = dict(r)
        data["tags"] = _json_list(data.get("tags"))
        results.append(data)
    return results


def delete_graph(graph_id: str) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM knowledge_graphs WHERE id = ?", (graph_id,))
        conn.commit()
    finally:
        conn.close()
    return True


def add_node(
    graph_id: str, label: str,
    parent_id: str | None = None, note: str = "",
    related_nodes: list[str] | None = None,
    order_index: int = 0, created_by: str = "agent",
    node_id: str | None = None,
    node_type: str = "concept",
) -> str:
    node_id = node_id or uuid.uuid4().hex[:12]
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO graph_nodes (id, graph_id, parent_id, label, note,
               node_type, related_nodes, order_index, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (node_id, graph_id, parent_id, label, note, node_type,
             json.dumps(related_nodes or [], ensure_ascii=False),
             order_index, created_by),
        )
        conn.commit()
    finally:
        conn.close()
    return node_id


def get_nodes(graph_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM graph_nodes WHERE graph_id = ? ORDER BY order_index",
            (graph_id,),
        ).fetchall()
    finally:
        conn.close()
    results = []
    for r in rows:
        data = dict(r)
        data["related_nodes"] = _json_list(data.get("related_nodes"))
        results.append(data)
    return results


def get_outline(graph_id: str) -> list[dict]:
    """构建节点大纲树（id / label / note / children / related_nodes）。"""
    nodes = get_nodes(graph_id)
    by_id = {node["id"]: node for node in nodes}
    roots: list[dict] = []

    def build(node: dict) -> dict:
        children = [
            build(child)
            for child in nodes
            if child.get("parent_id") == node["id"]
        ]
        return {
            "id": node["id"],
            "label": node["label"],
            "note": node.get("note") or "",
            "related_nodes": node.get("related_nodes") or [],
            "children": children,
        }

    for node in nodes:
        parent = node.get("parent_id")
        if not parent or parent not in by_id:
            roots.append(build(node))
    return roots


def update_node(node_id: str, **kwargs) -> bool:
    allowed = {"label", "note", "node_type", "related_nodes", "order_index"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    if "related_nodes" in updates and isinstance(updates["related_nodes"], list):
        updates["related_nodes"] = json.dumps(updates["related_nodes"], ensure_ascii=False)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE graph_nodes SET {set_clause} WHERE id = ?",
            (*updates.values(), node_id),
        )
        conn.commit()
    finally:
        conn.close()
    return True


def delete_node(node_id: str) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))
        conn.commit()
    finally:
        conn.close()
    return True


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
        data["key_points"] = _json_list(data.get("key_points"))
        results.append(data)
    return results


def create_link(
    from_graph_id: str,
    from_node_id: str,
    to_graph_id: str,
    to_node_id: str,
    relation_type: str = "related",
    note: str = "",
) -> str:
    link_id = uuid.uuid4().hex[:12]
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO graph_links
               (id, from_graph_id, from_node_id, to_graph_id, to_node_id,
                relation_type, note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (link_id, from_graph_id, from_node_id, to_graph_id, to_node_id,
             relation_type, note),
        )
        conn.commit()
    finally:
        conn.close()
    return link_id


def list_links(graph_id: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        if graph_id:
            rows = conn.execute(
                """SELECT * FROM graph_links
                   WHERE from_graph_id = ? OR to_graph_id = ?
                   ORDER BY created_at DESC""",
                (graph_id, graph_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM graph_links ORDER BY created_at DESC"
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def delete_link(link_id: str) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM graph_links WHERE id = ?", (link_id,))
        conn.commit()
    finally:
        conn.close()
    return True


def add_quiz_question(
    graph_id: str,
    node_id: str,
    question: str,
    answer: str,
    question_type: str = "short_answer",
    difficulty: int = 1,
) -> str:
    quiz_id = uuid.uuid4().hex[:12]
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO quiz_questions
               (id, graph_id, node_id, question, answer, question_type, difficulty)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (quiz_id, graph_id, node_id, question, answer, question_type, difficulty),
        )
        conn.commit()
    finally:
        conn.close()
    return quiz_id


def list_quiz(graph_id: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        if graph_id:
            rows = conn.execute(
                "SELECT * FROM quiz_questions WHERE graph_id = ? ORDER BY created_at DESC",
                (graph_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM quiz_questions ORDER BY created_at DESC"
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def ensure_review(graph_id: str, node_id: str, quiz_id: str) -> str:
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT id FROM review_progress
               WHERE graph_id = ? AND node_id = ? AND quiz_id = ?""",
            (graph_id, node_id, quiz_id),
        ).fetchone()
        if row:
            return row["id"]
        review_id = uuid.uuid4().hex[:12]
        conn.execute(
            """INSERT INTO review_progress
               (id, graph_id, node_id, quiz_id, status, due_at)
               VALUES (?, ?, ?, ?, 'new', ?)""",
            (review_id, graph_id, node_id, quiz_id, datetime.now().isoformat()),
        )
        conn.commit()
        return review_id
    finally:
        conn.close()


def get_due_review(limit: int = 20) -> list[dict]:
    now = datetime.now().isoformat()
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT rp.*, q.question, q.answer, q.question_type,
                      g.title AS graph_title, n.label AS node_label
               FROM review_progress rp
               JOIN quiz_questions q ON q.id = rp.quiz_id
               LEFT JOIN knowledge_graphs g ON g.id = rp.graph_id
               LEFT JOIN graph_nodes n ON n.id = rp.node_id
               WHERE rp.due_at IS NULL OR rp.due_at <= ?
               ORDER BY rp.due_at ASC LIMIT ?""",
            (now, limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def submit_review(review_id: str, rating: int) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM review_progress WHERE id = ?", (review_id,)
        ).fetchone()
        if not row:
            return False
        repetitions = row["repetitions"]
        interval = row["interval_days"]
        ease = row["ease_factor"]
        now = datetime.now()
        if rating <= 0:
            repetitions = 0
            interval = 1
            ease = max(1.3, ease - 0.2)
            status = "learning"
        else:
            repetitions += 1
            if repetitions == 1:
                interval = 1
            elif repetitions == 2:
                interval = 3
            else:
                interval = max(1, round(interval * ease))
            ease = max(1.3, ease + (0.1 if rating >= 2 else 0))
            status = "mastered" if repetitions >= 5 else "review"
        due = now.replace(day=now.day + interval)
        conn.execute(
            """UPDATE review_progress
               SET status = ?, repetitions = ?, interval_days = ?,
                   ease_factor = ?, due_at = ?, last_reviewed_at = ?,
                   updated_at = ?
               WHERE id = ?""",
            (status, repetitions, interval, ease, due.isoformat(),
             now.isoformat(), now.isoformat(), review_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_review_stats(graph_id: str | None = None) -> dict:
    conn = get_connection()
    try:
        where = "WHERE graph_id = ?" if graph_id else ""
        args = (graph_id,) if graph_id else ()
        rows = conn.execute(
            f"""SELECT status, COUNT(*) AS count FROM review_progress
                {where} GROUP BY status""",
            args,
        ).fetchall()
        stats = {r["status"]: r["count"] for r in rows}
        due = conn.execute(
            f"""SELECT COUNT(*) AS count FROM review_progress
                {where + (' AND' if where else 'WHERE')} (due_at IS NULL OR due_at <= ?)""",
            args + (datetime.now().isoformat(),),
        ).fetchone()
        return {
            "new": stats.get("new", 0),
            "learning": stats.get("learning", 0),
            "review": stats.get("review", 0),
            "mastered": stats.get("mastered", 0),
            "due": due["count"],
            "total": sum(stats.values()),
        }
    finally:
        conn.close()
