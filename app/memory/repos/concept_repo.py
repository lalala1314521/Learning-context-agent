"""概念本体 / 别名 / 提及 数据访问（链接/领域/合并见 concept_link_repo）。"""

import uuid
from datetime import datetime

from app.memory.database import get_connection
from app.memory.embeddings import encode_embedding


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
