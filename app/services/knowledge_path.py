"""Shortest path and narrative explanation between two concepts."""

from collections import deque

from app.memory import repository
from app.services.llm import get_llm


def find_shortest_path(
    start_id: str,
    end_id: str,
    max_depth: int = 8,
) -> list[dict]:
    if start_id == end_id:
        start = repository.get_concept(start_id)
        return [start] if start else []
    links = repository.list_concept_links(limit=100000, min_confidence=0.0)
    adjacency: dict[str, set[str]] = {}
    for link in links:
        adjacency.setdefault(link["from_concept"], set()).add(link["to_concept"])
        adjacency.setdefault(link["to_concept"], set()).add(link["from_concept"])
    queue = deque([(start_id, [start_id])])
    visited = {start_id}
    while queue:
        current, path = queue.popleft()
        if len(path) > max_depth:
            continue
        for neighbor in adjacency.get(current, set()):
            if neighbor in visited:
                continue
            next_path = path + [neighbor]
            if neighbor == end_id:
                return [
                    c for c in (repository.get_concept(cid) for cid in next_path)
                    if c
                ]
            visited.add(neighbor)
            queue.append((neighbor, next_path))
    return []


def explain_path(path: list[dict], llm=None) -> str:
    if len(path) < 2:
        return ""
    labels = [c["canonical_label"] for c in path]
    if llm is not None or _has_api_key():
        try:
            current = llm or get_llm()
            from langchain_core.messages import HumanMessage
            prompt = (
                "请用 3-5 句解释下面这条知识链路中的概念如何一步步连接起来，"
                "语气像在讲一个连贯的学习故事。\n链路："
                + " -> ".join(labels)
            )
            response = current.invoke([HumanMessage(content=prompt)])
            text = response.content if hasattr(response, "content") else str(response)
            if text and text.strip():
                return str(text).strip()
        except Exception:
            pass
    return (
        "从「{}」到「{}」，你的知识网络沿 {} 这条链路连通。"
        "这些概念之间由关系边关联，说明它们不是孤立知识点，"
        "复习时可以从链路的一端逐步迁移到另一端。"
    ).format(labels[0], labels[-1], " -> ".join(labels[1:-1] or labels))


def _has_api_key() -> bool:
    from app.config import config
    return bool(config.DEEPSEEK_API_KEY)
