"""脉络图 CRUD 工具：作为 LangChain Tool 暴露给 Agent 调用。"""

from langchain_core.tools import tool
from app.memory.repository import (
    create_graph, get_graph, update_graph, search_graphs, list_graphs, delete_graph,
    add_node, get_nodes, update_node, delete_node,
)


@tool
def tool_create_graph(title: str, description: str = "", graph_type: str = "auto",
                      mermaid_code: str = "", markdown_outline: str = "",
                      raw_content: str = "", source_type: str = "text",
                      source_name: str = "", tags: list[str] | None = None) -> str:
    """创建新的知识脉络图，返回 graph_id。

    Args:
        title: 脉络图标题
        description: 简短描述
        graph_type: 图类型 (auto / mermaid_flow / mermaid_tree / mermaid_mindmap / markdown)
        mermaid_code: Mermaid 代码
        markdown_outline: Markdown 大纲
        raw_content: 原始输入内容
        source_type: 来源类型 (text / file / url)
        source_name: 来源名称
        tags: 标签列表
    """
    return create_graph(
        title=title, description=description, graph_type=graph_type,
        mermaid_code=mermaid_code, markdown_outline=markdown_outline,
        raw_content=raw_content, source_type=source_type, source_name=source_name,
        tags=tags or [],
    )


@tool
def tool_search_graphs(query: str = "", limit: int = 20) -> str:
    """搜索已有的知识脉络图，返回 JSON 格式的结果列表。"""
    results = search_graphs(query, limit)
    if not results:
        return "未找到匹配的脉络图。"
    return str(results)


@tool
def tool_list_graphs(limit: int = 50) -> str:
    """列出所有知识脉络图。"""
    results = list_graphs(limit)
    if not results:
        return "暂无任何脉络图。"
    return str(results)


@tool
def tool_get_graph(graph_id: str) -> str:
    """获取指定脉络图的完整信息，包括所有节点。"""
    g = get_graph(graph_id)
    if not g:
        return f"脉络图 {graph_id} 不存在。"
    nodes = get_nodes(graph_id)
    return str({"graph": g, "nodes": nodes})


@tool
def tool_add_node(graph_id: str, label: str, parent_id: str = "",
                  note: str = "", order_index: int = 0,
                  related_nodes: list[str] | None = None) -> str:
    """向指定脉络图添加一个节点，返回 node_id。

    Args:
        graph_id: 脉络图 ID
        label: 节点文本
        parent_id: 父节点 ID（空字符串表示根节点）
        note: 备注
        order_index: 排序索引
        related_nodes: 关联节点 ID 列表
    """
    pid = parent_id if parent_id else None
    return add_node(graph_id, label, parent_id=pid, note=note,
                    order_index=order_index, created_by="agent",
                    related_nodes=related_nodes or [])


@tool
def tool_update_node(node_id: str, label: str = "", note: str = "",
                     related_nodes: list[str] | None = None,
                     order_index: int | None = None) -> str:
    """更新指定节点的文本、备注、关联节点或排序。"""
    kwargs = {}
    if label:
        kwargs["label"] = label
    if note:
        kwargs["note"] = note
    if related_nodes is not None:
        kwargs["related_nodes"] = related_nodes
    if order_index is not None:
        kwargs["order_index"] = order_index
    ok = update_node(node_id, **kwargs)
    return "更新成功" if ok else "更新失败"


@tool
def tool_delete_node(node_id: str) -> str:
    """删除指定节点。"""
    delete_node(node_id)
    return f"节点 {node_id} 已删除。"


@tool
def tool_delete_graph(graph_id: str) -> str:
    """删除指定脉络图及其所有节点。"""
    delete_graph(graph_id)
    return f"脉络图 {graph_id} 已删除。"


ALL_TOOLS = [
    tool_create_graph,
    tool_search_graphs,
    tool_list_graphs,
    tool_get_graph,
    tool_add_node,
    tool_update_node,
    tool_delete_node,
    tool_delete_graph,
]
