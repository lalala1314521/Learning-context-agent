"""知识结构的唯一规范化入口。

生成器、旧图兼容和前端视图都使用这层约束，避免把布局坐标或模型输出
直接当成事实保存。它不改变旧表结构，只把可确定的 ID、层级和关系规则
统一下来，并为证据字段保留兼容的 note 回退。
"""

from __future__ import annotations

from typing import Any


RELATION_TYPES = {"contains", "depends", "cause", "contrast", "extends", "example", "supports", "depends_on", "contrasts", "example_of", "causes", "related"}
RELATION_ALIASES = {
    "包含": "contains", "包括": "contains", "supports": "supports",
    "依赖": "depends", "dependency": "depends", "depends_on": "depends",
    "导致": "cause", "引起": "cause", "causes": "cause",
    "对比": "contrast", "区别": "contrast", "contrasts": "contrast",
    "扩展": "extends", "extends": "extends", "例子": "example", "example_of": "example",
}
NODE_TYPES = {"concept", "method", "case", "formula", "conclusion", "question", "source"}


def normalize_node_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """清洗模型节点；丢弃空节点，去掉无效自环和不存在的引用。"""
    cleaned: list[dict[str, Any]] = []
    def safe_order(value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback
    raw_ids: set[str] = set()
    for index, raw in enumerate(payloads):
        label = str(raw.get("label") or "").strip()
        if not label:
            continue
        raw_id = str(raw.get("id") or f"node-{index + 1}").strip()
        if raw_id in raw_ids:
            raw_id = f"{raw_id}-{index + 1}"
        raw_ids.add(raw_id)
        cleaned.append({
            "id": raw_id,
            "label": label[:200],
            "note": str(raw.get("note") or "").strip()[:4000],
            "node_type": str(raw.get("node_type") or "concept").strip().lower()
            if str(raw.get("node_type") or "concept").strip().lower() in NODE_TYPES else "concept",
            "parent_id": str(raw.get("parent_id") or "").strip() or None,
            "related_nodes": [str(value).strip() for value in (raw.get("related_nodes") or []) if str(value).strip()],
            "order_index": safe_order(raw.get("order_index"), index),
            "evidence": str(raw.get("evidence") or "").strip()[:2000],
            "relation_type": str(raw.get("relation_type") or "related").strip().lower(),
            "relation_status": str(raw.get("relation_status") or raw.get("status") or "pending").strip().lower(),
        })
    valid_ids = {node["id"] for node in cleaned}
    for node in cleaned:
        if node["parent_id"] not in valid_ids or node["parent_id"] == node["id"]:
            node["parent_id"] = None
        node["related_nodes"] = [
            value for value in dict.fromkeys(node["related_nodes"])
            if value in valid_ids and value != node["id"]
        ]
        node["relation_type"] = RELATION_ALIASES.get(node["relation_type"], node["relation_type"])
        if node["relation_type"] not in RELATION_TYPES:
            node["relation_type"] = "related"
        if node["evidence"] and node["evidence"] not in node["note"]:
            node["note"] = f"{node['note']}\n\n依据：{node['evidence']}".strip()
    return cleaned


def canonical_graph_view(graph: dict, nodes: list[dict], links: list[dict] | None = None) -> dict:
    """将旧库行转换为前端稳定的结构版本。"""
    node_ids = {node.get("id") for node in nodes}
    edges = []
    for node in nodes:
        parent_id = node.get("parent_id")
        if parent_id in node_ids:
            edges.append({
                "id": f"hierarchy:{parent_id}:{node['id']}",
                "from": parent_id,
                "to": node["id"],
                "relation_type": node.get("relation_type") if node.get("relation_type") not in {"related", "cause", "contrast", "example"} else "contains",
                "status": node.get("relation_status") or "pending",
                "evidence": node.get("evidence") or "",
            })
        for related_id in node.get("related_nodes") or []:
            if related_id in node_ids and related_id != node["id"]:
                edge_id = f"related:{min(node['id'], related_id)}:{max(node['id'], related_id)}"
                if not any(edge["id"] == edge_id for edge in edges):
                    edges.append({
                        "id": edge_id,
                        "from": node["id"],
                        "to": related_id,
                        "relation_type": node.get("relation_type") or "related",
                        "status": node.get("relation_status") or "pending",
                        "evidence": node.get("evidence") or "",
                    })
    for link in links or []:
        edges.append({
            "id": link.get("id"),
            "from": link.get("from_node_id"),
            "to": link.get("to_node_id"),
            "relation_type": link.get("relation_type") or "related",
            "status": link.get("status") or "pending",
            "evidence": link.get("note") or "",
            "cross_graph": True,
        })
    return {
        "version": "knowledge-structure/v1",
        "graph": graph,
        "nodes": nodes,
        "edges": edges,
        "view": {"selected_node_id": None, "layout": "semantic-hierarchy"},
    }
