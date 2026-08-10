"""LangGraph 图组装与编译：ReAct 混合架构。

- ReAct 循环：agent ↔ tools（LangGraph 原生回边，LLM bind_tools 自主决策）；
- 确定性管线：parse → generate → save → align → persist（文件/URL 显式命令路径）；
- 显式管理命令：list / search / get / manage 直达专用节点。
"""

from langgraph.graph import END, StateGraph

from app.graph.state import AgentState
from app.graph.agent import (
    agent_node,
    prepare_conversation_node,
    should_continue,
    tools_node,
)
from app.graph.nodes import (
    align_concepts_node,
    generate_graph_node,
    get_graph_node,
    list_graphs_node,
    manage_graph_node,
    parse_content_node,
    persist_graph_memory_node,
    router_node,
    save_graph_node,
    search_graphs_node,
    web_search_node,
)

_ACTIONS_TO_REACT = {"chat", "generate_graph"}


def _route_after_router(state: AgentState) -> str:
    action = state.get("action", "chat")
    route_map = {
        "parse_file": "parse_content",
        "parse_url": "parse_content",
        "list_graphs": "list_graphs",
        "search_graphs": "search_graphs",
        "get_graph": "get_graph",
        "manage_graph": "manage_graph",
    }
    if action in _ACTIONS_TO_REACT:
        return "prepare_conversation"
    return route_map.get(action, "prepare_conversation")


def _route_after_parse(state: AgentState) -> str:
    if state.get("error"):
        return END
    if state.get("web_search_enabled", False):
        return "web_search"
    return "generate_graph"


def _route_after_generate(state: AgentState) -> str:
    if state.get("graph_mermaid") or state.get("graph_markdown"):
        return "save_graph"
    return END


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)

    # ReAct 循环
    builder.add_node("prepare_conversation", prepare_conversation_node)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)

    # 确定性命令 / 管线
    builder.add_node("router", router_node)
    builder.add_node("parse_content", parse_content_node)
    builder.add_node("web_search", web_search_node)
    builder.add_node("generate_graph", generate_graph_node)
    builder.add_node("save_graph", save_graph_node)
    builder.add_node("align_concepts", align_concepts_node)
    builder.add_node("persist_graph_memory", persist_graph_memory_node)
    builder.add_node("list_graphs", list_graphs_node)
    builder.add_node("search_graphs", search_graphs_node)
    builder.add_node("get_graph", get_graph_node)
    builder.add_node("manage_graph", manage_graph_node)

    builder.set_entry_point("router")

    builder.add_conditional_edges("router", _route_after_router, {
        "parse_content": "parse_content",
        "list_graphs": "list_graphs",
        "search_graphs": "search_graphs",
        "get_graph": "get_graph",
        "manage_graph": "manage_graph",
        "prepare_conversation": "prepare_conversation",
    })
    builder.add_conditional_edges("parse_content", _route_after_parse, {
        "web_search": "web_search",
        "generate_graph": "generate_graph",
        END: END,
    })
    builder.add_edge("web_search", "generate_graph")
    builder.add_conditional_edges("generate_graph", _route_after_generate, {
        "save_graph": "save_graph",
        END: END,
    })
    builder.add_edge("save_graph", "align_concepts")
    builder.add_edge("align_concepts", "persist_graph_memory")
    builder.add_edge("persist_graph_memory", END)

    # ReAct 循环：agent → tools → agent，回边
    builder.add_edge("prepare_conversation", "agent")
    builder.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        "align_concepts": "align_concepts",
        "end": END,
    })
    builder.add_edge("tools", "agent")

    # 显式命令节点直达 END
    for node in ("list_graphs", "search_graphs", "get_graph", "manage_graph"):
        builder.add_edge(node, END)

    if checkpointer:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()
