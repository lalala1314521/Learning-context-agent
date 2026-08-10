"""知识脉络图 / 节点 / 跨脉络链接 的数据访问。"""

import json
import uuid

from app.memory.database import get_connection
from app.memory.repos.base import json_list


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
    parent_graph_id: str | None = None,
) -> str:
    graph_id = uuid.uuid4().hex[:12]
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO knowledge_graphs (id, title, description, graph_type,
               mermaid_code, markdown_outline, raw_content, source_type, source_name,
               tags, parent_graph_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (graph_id, title, description, graph_type,
             mermaid_code, markdown_outline, raw_content, source_type, source_name,
             json.dumps(tags or [], ensure_ascii=False), parent_graph_id),
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
    data["tags"] = json_list(data.get("tags"))
    return data


def update_graph(graph_id: str, **kwargs) -> bool:
    allowed = {"title", "description", "graph_type", "mermaid_code",
               "markdown_outline", "raw_content", "source_type", "source_name",
               "tags", "parent_graph_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    from datetime import datetime
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
        data["tags"] = json_list(data.get("tags"))
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
        data["tags"] = json_list(data.get("tags"))
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
            """SELECT n.*, c.canonical_label AS concept_label,
                      c.mention_count AS concept_mention_count
               FROM graph_nodes n
               LEFT JOIN concepts c ON c.id = n.concept_id
               WHERE n.graph_id = ?
               ORDER BY n.order_index""",
            (graph_id,),
        ).fetchall()
    finally:
        conn.close()
    results = []
    for r in rows:
        data = dict(r)
        data["related_nodes"] = json_list(data.get("related_nodes"))
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
    allowed = {
        "label", "note", "node_type", "related_nodes", "order_index",
        "concept_id",
    }
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
        data["related_nodes"] = json_list(data.get("related_nodes"))
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
