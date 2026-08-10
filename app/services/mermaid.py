"""Mermaid 代码语法校验：保证生成的图可被解析、可渲染。"""

import re

from app.graph.mermaid_parser import parse_graph_structure

_GRAPH_TYPE_RE = re.compile(
    r"^\s*(?:graph\s+(?:TD|LR|TB|BT|RL)|flowchart\s+(?:TD|LR|TB|BT|RL)|mindmap|journey|sequenceDiagram)",
    re.IGNORECASE,
)


def validate_mermaid(code: str) -> tuple[bool, str]:
    """校验 Mermaid 代码是否具备基本可解析结构。

    Returns:
        (True, "") 通过；或 (False, reason) 失败原因。
    """
    code = (code or "").strip()
    if not code:
        return False, "空代码"
    if not _GRAPH_TYPE_RE.match(code):
        return False, "缺少有效的图类型声明（graph/flowchart/mindmap 等）"
    nodes = parse_graph_structure(code, "")
    if not nodes:
        return False, "无法解析出任何节点"
    return True, ""


def repair_instruction(error: str) -> str:
    """生成针对校验失败的重试修正指令。"""
    return (
        "\n\n## 修正要求\n"
        f"上一次生成的 Mermaid 未通过校验（原因：{error}）。"
        "请重新生成合法的 Mermaid：必须声明 graph TD / flowchart LR / mindmap 等图类型，"
        "确保至少有一个节点，节点 id 与边引用一致，不要输出多余解释。"
    )
