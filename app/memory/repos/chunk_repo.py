"""原文分块（content_chunks）数据访问与向量检索。"""

import uuid

from app.memory.database import get_connection
from app.memory.embeddings import (
    cosine_similarity,
    decode_embedding,
    embed_text,
    encode_embedding,
)


def save_content_chunks(graph_id: str, chunks: list[dict]) -> int:
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
