"""测验题目与复习进度（纯数据访问，调度逻辑在 service 层）。"""

import uuid
from datetime import datetime

from app.memory.database import get_connection


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


def get_review(review_id: str) -> dict | None:
    """查询复习记录（含关联概念），供 service 层调度使用。"""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT rp.*, n.concept_id
               FROM review_progress rp
               LEFT JOIN graph_nodes n ON n.id = rp.node_id
               WHERE rp.id = ?""",
            (review_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_review_state(review_id: str, scheduled: dict) -> None:
    """用 FSRS 调度结果更新复习进度（纯数据更新）。"""
    conn = get_connection()
    try:
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
                datetime.now().isoformat(), review_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def add_review_history(
    concept_id: str, review_id: str, rating: int, scheduled: dict
) -> None:
    """写入复习历史（纯数据插入）。"""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO review_history
               (id, concept_id, review_progress_id, rating,
                retrievability, stability, difficulty, reviewed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                uuid.uuid4().hex[:12], concept_id, review_id,
                rating, scheduled["retrievability"],
                scheduled["stability"], scheduled["difficulty"],
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
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
