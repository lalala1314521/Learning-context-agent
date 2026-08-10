"""Mermaid / Markdown outline parser for graph nodes."""

import re
import uuid

_NODE_RE = re.compile(
    r"(?P<node>[A-Za-z_][A-Za-z0-9_]*\s*(?:\[\([^\]\n]*\)\]"
    r"|\(\([^()\n]*\)\)|\[[^\]\n]*\]|\{[^}\n]*\}|\([^)\n]*\))?)"
    r"|(?P<edge><-->|<->|==>|-->|\.->|---|~~~|--|->)"
)

_SKIP_PREFIXES = (
    "graph ", "flowchart", "subgraph", "end", "classdef", "style",
    "class ", "linkstyle", "direction ", "%%",
)
_MINDMAP_ROOT = re.compile(r"^\s*mindmap\s*$", re.IGNORECASE)
_MINDMAP_ITEM = re.compile(
    r"^\s*(?P<id>[\w-]*)\s*(?:"
    r"\[(?P<bracket>[^\]]*)\]|\"(?P<quote>[^\"]*)\"|"
    r"\(\((?P<round2>[^()]*)\)\)|\((?P<round>[^()]*)\)"
    r")?\s*(?P<tail>.*)$"
)
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_MD_BULLET = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_MD_NUMBER = re.compile(r"^(\s*)\d+[.、)]\s+(.+)$")


def _new_node_id() -> str:
    return uuid.uuid4().hex[:12]


def _extract_label(node_id: str, shape: str | None) -> str:
    if not shape:
        return node_id.strip()
    shape = shape.strip()
    if shape.startswith("[("):
        label = shape[2:-2]
    elif shape.startswith("(("):
        label = shape[2:-2]
    elif shape.startswith("[[") and shape.endswith("]]"):
        label = shape[2:-2]
    else:
        label = shape[1:-1]
    return label.strip().strip("\"'")


def _parse_flowchart(text: str) -> list[dict]:
    nodes: dict[str, dict] = {}
    id_map: dict[str, str] = {}
    parent_map: dict[str, str] = {}
    related_map: dict[str, set[str]] = {}
    order = 0

    def ensure(node_id: str, label: str) -> None:
        nonlocal order
        if node_id not in nodes:
            generated_id = _new_node_id()
            nodes[node_id] = {
                "id": generated_id,
                "label": label,
                "parent_id": None,
                "related_nodes": [],
                "order_index": order,
            }
            id_map[node_id] = generated_id
            order += 1

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith(_SKIP_PREFIXES):
            continue
        line = re.sub(r"--(?!>)[^>]*-->", "-->", line)
        tokens: list[tuple[str, str, str | None]] = []
        for m in _NODE_RE.finditer(line):
            if m.group("node"):
                node_token = m.group("node").strip()
                id_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(\s*)(.*)", node_token)
                if not id_match:
                    continue
                node_id = id_match.group(1)
                shape = id_match.group(3).strip() or None
                tokens.append(("node", node_id, shape))
            else:
                tokens.append(("edge", m.group("edge"), None))

        for kind, value, shape in tokens:
            if kind == "node":
                ensure(value, _extract_label(value, shape))

        for i, (kind, value, shape) in enumerate(tokens):
            if kind != "edge":
                continue
            prev_node = next(
                (t[1] for t in reversed(tokens[:i]) if t[0] == "node"), None
            )
            next_node = next(
                (t[1] for t in tokens[i + 1:] if t[0] == "node"), None
            )
            if not prev_node or not next_node:
                continue
            prev_gen = id_map[prev_node]
            next_gen = id_map[next_node]
            if value in ("-->", "==>", "->", ".->"):
                if next_node not in parent_map:
                    parent_map[next_node] = prev_gen
                elif parent_map[next_node] != prev_gen:
                    related_map.setdefault(prev_node, set()).add(next_gen)
                    related_map.setdefault(next_node, set()).add(prev_gen)
            else:
                related_map.setdefault(prev_node, set()).add(next_gen)
                related_map.setdefault(next_node, set()).add(prev_gen)

    result = []
    for node_id, node in nodes.items():
        node["parent_id"] = parent_map.get(node_id)
        node["related_nodes"] = sorted(related_map.get(node_id, set()))
        result.append(node)
    return result


def _parse_mindmap(text: str) -> list[dict]:
    nodes: list[dict] = []
    stack: list[tuple[int, str]] = []

    for raw_line in text.splitlines():
        if _MINDMAP_ROOT.match(raw_line):
            continue
        line = raw_line.rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        m = _MINDMAP_ITEM.match(line)
        if not m:
            continue
        node_id = _new_node_id()
        id_part = (m.group("id") or "").strip()
        tail = (m.group("tail") or "").strip()
        label = (
            m.group("bracket") or m.group("quote")
            or m.group("round2") or m.group("round")
            or (f"{id_part} {tail}".strip() if tail else id_part)
        )
        label = (label or "").strip().strip("\"'")
        if not label:
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent_id = stack[-1][1] if stack else None
        nodes.append({
            "id": node_id,
            "label": label,
            "parent_id": parent_id,
            "related_nodes": [],
            "order_index": len(nodes),
        })
        stack.append((indent, node_id))
    return nodes


def _parse_markdown(text: str) -> list[dict]:
    nodes: list[dict] = []
    stack: list[tuple[int, str]] = []
    current_heading_level = 1

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        m = _MD_HEADING.match(line)
        if m:
            level = len(m.group(1))
            current_heading_level = level
            label = m.group(2).strip()
        else:
            m = _MD_BULLET.match(line) or _MD_NUMBER.match(line)
            if not m:
                continue
            indent = len(m.group(1))
            level = current_heading_level + 1 + indent // 2
            label = m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_id = stack[-1][1] if stack else None
        node_id = _new_node_id()
        nodes.append({
            "id": node_id,
            "label": label,
            "parent_id": parent_id,
            "related_nodes": [],
            "order_index": len(nodes),
        })
        stack.append((level, node_id))
    return nodes


def parse_graph_structure(mermaid_code: str = "", markdown_outline: str = "") -> list[dict]:
    """Extract nodes from Mermaid or Markdown, preferring Mermaid."""
    mermaid = (mermaid_code or "").strip()
    if mermaid:
        if re.search(r"^\s*mindmap\b", mermaid, re.IGNORECASE | re.MULTILINE):
            nodes = _parse_mindmap(mermaid)
        else:
            nodes = _parse_flowchart(mermaid)
        if nodes:
            return nodes
    return _parse_markdown(markdown_outline or "")
