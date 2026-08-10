"""概念链接 / 领域 / 合并 / 掌握度 数据访问。"""

import math
import uuid
from datetime import datetime

from app.memory.database import get_connection


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


def delete_concept_link(link_id: str) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM concept_links WHERE id = ?", (link_id,))
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
