"""脉络图运维 helpers：节点补解析、自动跨脉络链接、自动出题。

从 Web 层迁移而来，供 API 路由与 concept_alignment（迁移脚本）共用，
消除 repository / service → web 的反向依赖。
"""

import re

from app.logging_config import get_logger
from app.graph.mermaid_parser import parse_graph_structure
from app.memory import repository

logger = get_logger("services.graph_management")


def char_overlap(a: str, b: str) -> float:
    if not a or not b:
        return 0
    sa, sb = set(a.lower()), set(b.lower())
    return len(sa & sb) / max(len(sa), len(sb))


def _compact_label(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (value or "").lower())


def _is_confident_match(source: str, target: str) -> bool:
    source_key, target_key = _compact_label(source), _compact_label(target)
    if not source_key or not target_key or min(len(source_key), len(target_key)) < 2:
        return False
    if source_key == target_key:
        return True
    if len(source_key) >= 4 and len(target_key) >= 4 and (source_key in target_key or target_key in source_key):
        return True
    return char_overlap(source_key, target_key) >= 0.82


def hydrate_nodes(graph_id: str) -> int:
    """旧图缺少节点时，从 Mermaid / Markdown 补解析节点落库。"""
    graph = repository.get_graph(graph_id)
    if not graph or repository.get_nodes(graph_id):
        return 0
    nodes = parse_graph_structure(
        graph.get("mermaid_code") or "",
        graph.get("markdown_outline") or "",
    )
    for index, node in enumerate(nodes):
        repository.add_node(
            graph_id,
            label=node["label"],
            parent_id=node["parent_id"],
            related_nodes=node["related_nodes"],
            order_index=node["order_index"],
            created_by="agent",
            node_id=node["id"],
            note=node.get("note") or "",
        )
    if nodes:
        logger.info("hydrated %d nodes for graph %s", len(nodes), graph_id)
    return len(nodes)


def auto_link(graph_id: str, nodes: list[dict]) -> list[dict]:
    """按节点文本相似度自动建立跨脉络链接。"""
    if not nodes:
        return []
    existing = [g for g in repository.list_graphs(limit=100) if g["id"] != graph_id]
    created: list[dict] = []
    existing_links = repository.list_links(graph_id)
    seen = {
        (link["from_node_id"], link["to_graph_id"], link["to_node_id"])
        for link in existing_links
    }
    for graph in existing:
        targets = repository.get_nodes(graph["id"])
        for node in nodes:
            for target in targets:
                if _is_confident_match(node["label"], target["label"]):
                    key = (node["id"], graph["id"], target["id"])
                    if key in seen:
                        continue
                    if len(created) >= 20:
                        return created
                    link_id = repository.create_link(
                        graph_id,
                        node["id"],
                        graph["id"],
                        target["id"],
                        relation_type="related",
                        note=f"候选依据：概念标签高度匹配（{node['label']} ↔ {target['label']}），请在关系详情中确认。",
                    )
                    seen.add(key)
                    created.append({
                        "link_id": link_id,
                        "from_node_id": node["id"],
                        "from_node_label": node["label"],
                        "to_graph_id": graph["id"],
                        "to_graph_title": graph["title"],
                        "to_node_id": target["id"],
                        "to_node_label": target["label"],
                    })
    return created


def generate_quiz(graph_id: str, nodes: list[dict]) -> int:
    """为没有题目的节点生成理解型题目，而不是统一填空。"""
    existing = {q["node_id"] for q in repository.list_quiz(graph_id)}
    count = 0
    for node in nodes:
        if node["id"] in existing:
            continue
        note = (node.get("note") or "").strip()
        related = [item for item in (node.get("related_nodes") or []) if item]
        if related:
            question = f"请解释「{node['label']}」与它关联的知识点之间有什么关系，并给出一个适用条件。"
            question_type = "explain_relation"
        elif node.get("node_type") in {"method", "case"}:
            question = f"在什么情境下会使用「{node['label']}」？请说明判断依据。"
            question_type = "transfer"
        else:
            question = f"请用自己的话解释「{node['label']}」，并说明它解决的核心问题。"
            question_type = "feynman"
        answer = note or f"围绕「{node['label']}」补充材料中的定义、条件和例子。"
        quiz_id = repository.add_quiz_question(
            graph_id,
            node["id"],
            question,
            answer,
            question_type=question_type,
        )
        repository.ensure_review(graph_id, node["id"], quiz_id)
        count += 1
    if count:
        logger.info("generated %d quiz items for graph %s", count, graph_id)
    return count
