"""脉络图运维 helpers：节点补解析、自动跨脉络链接、自动出题。

从 Web 层迁移而来，供 API 路由与 concept_alignment（迁移脚本）共用，
消除 repository / service → web 的反向依赖。
"""

from app.logging_config import get_logger
from app.graph.mermaid_parser import parse_graph_structure
from app.memory import repository

logger = get_logger("services.graph_management")


def char_overlap(a: str, b: str) -> float:
    if not a or not b:
        return 0
    sa, sb = set(a.lower()), set(b.lower())
    return len(sa & sb) / max(len(sa), len(sb))


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
                if char_overlap(node["label"], target["label"]) >= 0.5:
                    key = (node["id"], graph["id"], target["id"])
                    if key in seen:
                        continue
                    link_id = repository.create_link(
                        graph_id,
                        node["id"],
                        graph["id"],
                        target["id"],
                        relation_type="related",
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
    return created[:20]


def generate_quiz(graph_id: str, nodes: list[dict]) -> int:
    """为没有题目的节点生成基础回忆题与复习进度。"""
    existing = {q["node_id"] for q in repository.list_quiz(graph_id)}
    count = 0
    for node in nodes:
        if node["id"] in existing:
            continue
        answer = node.get("note") or f"请回顾：{node['label']}"
        quiz_id = repository.add_quiz_question(
            graph_id,
            node["id"],
            f"什么是「{node['label']}」？",
            answer,
            question_type="short_answer",
        )
        repository.ensure_review(graph_id, node["id"], quiz_id)
        count += 1
    if count:
        logger.info("generated %d quiz items for graph %s", count, graph_id)
    return count
