"""Repository 层：知识脉络与记忆快照的 CRUD 操作。"""

import json
import math
import uuid
from datetime import datetime

from app.memory.database import get_connection
from app.memory.embeddings import cosine_similarity, decode_embedding, embed_text, encode_embedding


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
    data["tags"] = _json_list(data.get("tags"))
    return data


def update_graph(graph_id: str, **kwargs) -> bool:
    allowed = {"title", "description", "graph_type", "mermaid_code",
               "markdown_outline", "raw_content", "source_type", "source_name",
               "tags", "parent_graph_id"}
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
                      g.title AS graph_title, n.label AS node_label,
                      n.concept_id
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
    from app.services.fsrs import schedule_review
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT rp.*, n.concept_id
               FROM review_progress rp
               LEFT JOIN graph_nodes n ON n.id = rp.node_id
               WHERE rp.id = ?""",
            (review_id,),
        ).fetchone()
        if not row:
            return False
        now = datetime.now()
        scheduled = schedule_review(
            {
                "repetitions": row["repetitions"],
                "interval_days": row["interval_days"],
                "ease_factor": row["ease_factor"],
                "difficulty": row["difficulty"],
                "stability": row["stability"],
                "last_reviewed_at": row["last_reviewed_at"],
                "lapses": row["lapses"] if "lapses" in row.keys() else 0,
            },
            rating,
            now=now,
        )
        conn.execute(
            """UPDATE review_progress
               SET status = ?, repetitions = ?, interval_days = ?,
                   ease_factor = ?, difficulty = ?, stability = ?,
                   retrievability = ?, due_at = ?, last_reviewed_at = ?,
                   updated_at = ?
               WHERE id = ?""",
            (
                scheduled["status"], scheduled["repetitions"],
                scheduled["interval_days"], scheduled["ease_factor"],
                scheduled["difficulty"], scheduled["stability"],
                scheduled["retrievability"],
                scheduled["due_at"].isoformat(),
                scheduled["last_reviewed_at"].isoformat(),
                now.isoformat(), review_id,
            ),
        )
        if row["concept_id"]:
            conn.execute(
                """INSERT INTO review_history
                   (id, concept_id, review_progress_id, rating,
                    retrievability, stability, difficulty, reviewed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    uuid.uuid4().hex[:12], row["concept_id"], review_id,
                    rating, scheduled["retrievability"],
                    scheduled["stability"], scheduled["difficulty"],
                    now.isoformat(),
                ),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def list_review_history(concept_id: str, limit: int = 100) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM review_history
               WHERE concept_id = ?
               ORDER BY reviewed_at ASC LIMIT ?""",
            (concept_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
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


def create_concept(
    canonical_label: str,
    summary: str = "",
    embedding: list[float] | None = None,
    domain_id: str | None = None,
    concept_id: str | None = None,
) -> str:
    label = (canonical_label or "").strip()
    if not label:
        raise ValueError("concept label cannot be empty")
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM concepts WHERE canonical_label = ?", (label,)
        ).fetchone()
        if existing:
            return existing["id"]
        concept_id = concept_id or uuid.uuid4().hex[:12]
        conn.execute(
            """INSERT INTO concepts
               (id, canonical_label, summary, domain_id, embedding, mention_count)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (
                concept_id, label, summary, domain_id,
                encode_embedding(embedding or []),
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO concept_aliases (id, concept_id, alias) VALUES (?, ?, ?)",
            (uuid.uuid4().hex[:12], concept_id, label),
        )
        conn.commit()
        return concept_id
    finally:
        conn.close()


def find_concept_by_alias(alias: str) -> dict | None:
    alias = (alias or "").strip()
    if not alias:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT c.* FROM concepts c
               LEFT JOIN concept_aliases a ON a.concept_id = c.id
               WHERE c.canonical_label = ? COLLATE NOCASE
                  OR a.alias = ? COLLATE NOCASE
               ORDER BY c.mention_count DESC LIMIT 1""",
            (alias, alias),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_concepts(limit: int = 10000, include_embedding: bool = False) -> list[dict]:
    columns = "*" if include_embedding else (
        "id, canonical_label, summary, domain_id, mention_count, created_at, updated_at"
    )
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT {columns} FROM concepts ORDER BY mention_count DESC, updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search_concepts(query: str, limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT c.id, c.canonical_label, c.summary, c.mention_count,
                      c.created_at
               FROM concepts c
               LEFT JOIN concept_aliases a ON a.concept_id = c.id
               WHERE c.canonical_label LIKE ? OR c.summary LIKE ? OR a.alias LIKE ?
               GROUP BY c.id
               ORDER BY c.mention_count DESC LIMIT ?""",
            (f"%{query}%", f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_concepts_created_since(days: int = 7) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS count FROM concepts
               WHERE created_at >= datetime('now', ?)""",
            (f"-{days} days",),
        ).fetchone()
        return int(row["count"])
    finally:
        conn.close()


def count_concept_links_created_since(days: int = 7) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS count FROM concept_links
               WHERE created_at >= datetime('now', ?)""",
            (f"-{days} days",),
        ).fetchone()
        return int(row["count"])
    finally:
        conn.close()


def count_review_history() -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS count FROM review_history").fetchone()
        return int(row["count"])
    finally:
        conn.close()


def get_concept(concept_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM concepts WHERE id = ?", (concept_id,)
        ).fetchone()
        if not row:
            return None
        concept = dict(row)
        aliases = conn.execute(
            "SELECT alias FROM concept_aliases WHERE concept_id = ? ORDER BY alias",
            (concept_id,),
        ).fetchall()
        concept["aliases"] = [a["alias"] for a in aliases]
        return concept
    finally:
        conn.close()


def update_concept(concept_id: str, **kwargs) -> bool:
    allowed = {"canonical_label", "summary", "domain_id", "embedding", "mention_count"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    if "embedding" in updates and updates["embedding"] is not None:
        updates["embedding"] = encode_embedding(updates["embedding"])
    updates["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE concepts SET {set_clause} WHERE id = ?",
            (*updates.values(), concept_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def add_concept_alias(concept_id: str, alias: str) -> str:
    alias = (alias or "").strip()
    alias_id = uuid.uuid4().hex[:12]
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO concept_aliases (id, concept_id, alias) VALUES (?, ?, ?)",
            (alias_id, concept_id, alias),
        )
        conn.commit()
        return alias_id
    finally:
        conn.close()


def create_concept_link(
    from_concept: str,
    to_concept: str,
    relation_type: str = "related",
    confidence: float = 0.6,
    evidence: str = "",
    source: str = "llm",
    status: str = "pending",
) -> str:
    if from_concept == to_concept:
        return ""
    conn = get_connection()
    try:
        existing = conn.execute(
            """SELECT id FROM concept_links
               WHERE from_concept = ? AND to_concept = ? AND relation_type = ?""",
            (from_concept, to_concept, relation_type),
        ).fetchone()
        if existing:
            return existing["id"]
        link_id = uuid.uuid4().hex[:12]
        conn.execute(
            """INSERT INTO concept_links
               (id, from_concept, to_concept, relation_type, confidence,
                evidence, source, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                link_id, from_concept, to_concept, relation_type,
                float(confidence), evidence, source, status,
            ),
        )
        conn.commit()
        return link_id
    finally:
        conn.close()


def list_concept_links(
    limit: int = 1000,
    status: str | None = None,
    min_confidence: float = 0.0,
) -> list[dict]:
    sql = """
        SELECT cl.*, c1.canonical_label AS from_label,
               c2.canonical_label AS to_label
        FROM concept_links cl
        JOIN concepts c1 ON c1.id = cl.from_concept
        JOIN concepts c2 ON c2.id = cl.to_concept
        WHERE cl.confidence >= ?
    """
    args: list = [min_confidence]
    if status:
        sql += " AND cl.status = ?"
        args.append(status)
    sql += " ORDER BY cl.confidence DESC, cl.created_at DESC LIMIT ?"
    args.append(limit)
    conn = get_connection()
    try:
        rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_concept_link_status(link_id: str, status: str) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE concept_links SET status = ? WHERE id = ?",
            (status, link_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def record_concept_merge(winner_id: str, loser_id: str) -> str:
    merge_id = uuid.uuid4().hex[:12]
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO concept_merges (id, winner_id, loser_id)
               VALUES (?, ?, ?)""",
            (merge_id, winner_id, loser_id),
        )
        conn.commit()
        return merge_id
    finally:
        conn.close()


def delete_concept(concept_id: str) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE graph_nodes SET concept_id = NULL WHERE concept_id = ?",
            (concept_id,),
        )
        conn.execute("DELETE FROM concept_aliases WHERE concept_id = ?", (concept_id,))
        conn.execute(
            "DELETE FROM concept_links WHERE from_concept = ? OR to_concept = ?",
            (concept_id, concept_id),
        )
        conn.execute("DELETE FROM review_history WHERE concept_id = ?", (concept_id,))
        conn.execute("DELETE FROM concepts WHERE id = ?", (concept_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def delete_concept_link(link_id: str) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM concept_links WHERE id = ?", (link_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def create_domain(name: str, color: str = "#4f8ef7") -> str:
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM domains WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            return existing["id"]
        domain_id = uuid.uuid4().hex[:12]
        conn.execute(
            "INSERT INTO domains (id, name, color, concept_count) VALUES (?, ?, ?, 0)",
            (domain_id, name, color),
        )
        conn.commit()
        return domain_id
    finally:
        conn.close()


def list_domains() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM domains ORDER BY concept_count DESC, created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_domain_count(domain_id: str, count: int) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE domains SET concept_count = ? WHERE id = ?",
            (count, domain_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_concept_mastery() -> dict[str, dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT n.concept_id, rp.repetitions, rp.stability,
                      rp.retrievability, rp.last_reviewed_at, rp.updated_at
               FROM review_progress rp
               JOIN graph_nodes n ON n.id = rp.node_id
               WHERE n.concept_id IS NOT NULL
               ORDER BY rp.updated_at DESC""",
        ).fetchall()
        result: dict[str, dict] = {}
        latest: dict[str, dict] = {}
        for row in rows:
            cid = row["concept_id"]
            if cid in latest:
                continue
            latest[cid] = row
        now = datetime.now()
        for cid, row in latest.items():
            stability = float(row["stability"] or 1.0)
            last = row["last_reviewed_at"]
            retrievability = float(row["retrievability"] or 0.0)
            if last:
                try:
                    last_dt = datetime.fromisoformat(str(last))
                    days = max(0.0, (now - last_dt).total_seconds() / 86400.0)
                    retrievability = math.exp(-days / max(stability, 0.1))
                except Exception:
                    pass
            if retrievability >= 0.9:
                level = "strong"
            elif retrievability >= 0.7:
                level = "medium"
            elif retrievability >= 0.5:
                level = "weak"
            else:
                level = "forgotten"
            result[cid] = {
                "review_count": int(row["repetitions"] or 0),
                "repetitions": int(row["repetitions"] or 0),
                "mastery": level,
                "retrievability": round(retrievability, 4),
                "last_reviewed_at": row["last_reviewed_at"],
            }
        return result
    finally:
        conn.close()


def get_concepts_for_graph(graph_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT DISTINCT c.*, g.title AS source_graph_title
               FROM graph_nodes n
               JOIN concepts c ON c.id = n.concept_id
               JOIN knowledge_graphs g ON g.id = n.graph_id
               WHERE n.graph_id = ?""",
            (graph_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_concept_mentions(concept_id: str, limit: int = 100) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT n.id AS node_id, n.label, n.note, n.graph_id,
                      g.title AS graph_title, g.source_name
               FROM graph_nodes n
               JOIN knowledge_graphs g ON g.id = n.graph_id
               WHERE n.concept_id = ?
               ORDER BY n.created_at DESC LIMIT ?""",
            (concept_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_concept_links_for_concept(concept_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT cl.*, c1.canonical_label AS from_label,
                      c2.canonical_label AS to_label
               FROM concept_links cl
               JOIN concepts c1 ON c1.id = cl.from_concept
               JOIN concepts c2 ON c2.id = cl.to_concept
               WHERE cl.from_concept = ? OR cl.to_concept = ?
               ORDER BY cl.confidence DESC""",
            (concept_id, concept_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def merge_concepts(winner_id: str, loser_id: str) -> bool:
    """Merge loser concept into winner and keep an audit record."""
    if winner_id == loser_id:
        return False
    conn = get_connection()
    try:
        loser = conn.execute(
            "SELECT * FROM concepts WHERE id = ?", (loser_id,)
        ).fetchone()
        winner = conn.execute(
            "SELECT * FROM concepts WHERE id = ?", (winner_id,)
        ).fetchone()
        if not loser or not winner:
            return False
        mention_count = int(winner["mention_count"] or 0) + int(
            loser["mention_count"] or 0
        )
        conn.execute(
            "UPDATE graph_nodes SET concept_id = ? WHERE concept_id = ?",
            (winner_id, loser_id),
        )
        conn.execute(
            """UPDATE concept_aliases SET concept_id = ?
               WHERE concept_id = ? AND alias NOT IN (
                   SELECT alias FROM concept_aliases WHERE concept_id = ?
               )""",
            (winner_id, loser_id, winner_id),
        )
        for table in ("concept_links",):
            for column in ("from_concept", "to_concept"):
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE {column} = ?", (loser_id,)
                ).fetchall()
                for row in rows:
                    other = (
                        row["to_concept"] if column == "from_concept"
                        else row["from_concept"]
                    )
                    if other == winner_id:
                        conn.execute(
                            f"DELETE FROM {table} WHERE id = ?", (row["id"],)
                        )
                    else:
                        conn.execute(
                            f"""UPDATE {table} SET {column} = ?
                                WHERE id = ?""",
                            (winner_id, row["id"]),
                        )
        conn.execute(
            """INSERT INTO concept_merges (id, winner_id, loser_id)
               VALUES (?, ?, ?)""",
            (uuid.uuid4().hex[:12], winner_id, loser_id),
        )
        conn.execute("DELETE FROM concepts WHERE id = ?", (loser_id,))
        conn.execute(
            "UPDATE concepts SET mention_count = ? WHERE id = ?",
            (mention_count, winner_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def save_content_chunks(
    graph_id: str,
    chunks: list[dict],
) -> int:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM content_chunks WHERE graph_id = ?", (graph_id,))
        for index, chunk in enumerate(chunks):
            conn.execute(
                """INSERT INTO content_chunks
                   (id, graph_id, chunk_index, text, embedding, char_start, char_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    uuid.uuid4().hex[:12],
                    graph_id,
                    int(chunk.get("chunk_index", index)),
                    chunk.get("text", ""),
                    encode_embedding(chunk.get("embedding") or []),
                    chunk.get("char_start"),
                    chunk.get("char_end"),
                ),
            )
        conn.commit()
        return len(chunks)
    finally:
        conn.close()


def list_content_chunks(graph_id: str, limit: int = 1000) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, graph_id, chunk_index, text, char_start, char_end
               FROM content_chunks
               WHERE graph_id = ?
               ORDER BY chunk_index LIMIT ?""",
            (graph_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search_content_chunks(query: str, limit: int = 5) -> list[dict]:
    vector = embed_text(query)
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT c.*, g.title AS graph_title
               FROM content_chunks c
               JOIN knowledge_graphs g ON g.id = c.graph_id
               ORDER BY c.chunk_index LIMIT 20000"""
        ).fetchall()
    finally:
        conn.close()
    results = []
    lowered = query.lower()
    for row in rows:
        data = dict(row)
        text = data.get("text") or ""
        similarity = cosine_similarity(vector, decode_embedding(data.get("embedding")))
        keyword_boost = 0.35 if lowered and lowered in text.lower() else 0.0
        data["similarity"] = similarity + keyword_boost
        results.append(data)
    results.sort(key=lambda item: item["similarity"], reverse=True)
    return results[:limit]
