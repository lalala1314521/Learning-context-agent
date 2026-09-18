"""Shortest path and narrative explanation between two concepts."""

from collections import deque

from app.memory import repository
from app.services.llm import get_llm


def find_shortest_path(
    start_id: str,
    end_id: str,
    max_depth: int = 8,
) -> list[dict]:
    concepts, _ = find_shortest_path_with_edges(start_id, end_id, max_depth=max_depth)
    return concepts


def find_shortest_path_with_edges(
    start_id: str,
    end_id: str,
    max_depth: int = 8,
) -> tuple[list[dict], list[dict]]:
    """返回概念链和实际关系边，过滤 rejected 并尊重有向关系。"""
    if start_id == end_id:
        start = repository.get_concept(start_id)
        return ([start] if start else []), []
    links = [
        link for link in repository.list_concept_links(limit=100000, min_confidence=0.0)
        if link.get("status") != "rejected"
    ]
    symmetric = {"related", "contrast", "same", "同义", "对比", "相关"}
    adjacency: dict[str, list[tuple[str, dict]]] = {}
    for link in links:
        source, target = link["from_concept"], link["to_concept"]
        adjacency.setdefault(source, []).append((target, link))
        if (link.get("relation_type") or "related").lower() in symmetric:
            adjacency.setdefault(target, []).append((source, link))
    queue = deque([(start_id, [start_id])])
    visited = {start_id}
    while queue:
        current, path = queue.popleft()
        if len(path) > max_depth:
            continue
        for neighbor, link in adjacency.get(current, []):
            if neighbor in visited:
                continue
            next_path = path + [neighbor]
            if neighbor == end_id:
                concepts = [c for c in (repository.get_concept(cid) for cid in next_path) if c]
                relations = []
                for left, right in zip(next_path, next_path[1:]):
                    edge = next((item for item in links if item["from_concept"] == left and item["to_concept"] == right), None)
                    if edge is None:
                        edge = next((item for item in links if item["from_concept"] == right and item["to_concept"] == left), None)
                    if edge:
                        relations.append({"id": edge.get("id"), "from_concept": left, "to_concept": right, "relation_type": edge.get("relation_type") or "related", "confidence": edge.get("confidence"), "status": edge.get("status"), "evidence": edge.get("evidence") or ""})
                return concepts, relations
            visited.add(neighbor)
            queue.append((neighbor, next_path))
    return [], []


def explain_path(path: list[dict], relations: list[dict] | None = None, llm=None) -> str:
    if len(path) < 2:
        return ""
    labels = [c["canonical_label"] for c in path]
    relation_summary = "；".join(
        f"{item.get('relation_type') or '相关'}（置信度 {float(item.get('confidence') or 0):.2f}）"
        for item in (relations or [])
    )
    if llm is not None or _has_api_key():
        try:
            current = llm or get_llm()
            from langchain_core.messages import HumanMessage
            prompt = (
                "请用 3-5 句解释下面这条知识链路中的概念如何一步步连接起来，"
                "语气像在讲一个连贯的学习故事。\n链路："
                + " -> ".join(labels)
                + (f"\n关系证据：{relation_summary}" if relation_summary else "")
            )
            response = current.invoke([HumanMessage(content=prompt)])
            text = response.content if hasattr(response, "content") else str(response)
            if text and text.strip():
                return str(text).strip()
        except Exception:
            pass
    return (
        "从「{}」到「{}」，你的知识网络沿 {} 这条链路连通。"
        "这些概念之间由带类型的关系边关联，说明它们不是孤立知识点，"
        "复习时可以从链路的一端逐步迁移到另一端。"
    ).format(labels[0], labels[-1], " -> ".join(labels[1:-1] or labels))


def _has_api_key() -> bool:
    from app.config import config
    return bool(config.DEEPSEEK_API_KEY)
