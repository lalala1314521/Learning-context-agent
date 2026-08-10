"""LangGraph 图组装与编译。"""

from langgraph.graph import StateGraph, END
from app.graph.state import AgentState
from app.graph.nodes import (
    router_node, parse_content_node, web_search_node,
    generate_graph_node, save_graph_node,
    align_concepts_node,
    list_graphs_node, search_graphs_node, chat_node,
    manage_graph_node, get_graph_node, summarize_memory_node,
)


def _route_after_router(state: AgentState) -> str:
    action = state.get("action", "chat")
    route_map = {
        "parse_file": "parse_content",
        "parse_url": "parse_content",
        "generate_graph": "parse_content",
        "list_graphs": "list_graphs",
        "search_graphs": "search_graphs",
        "get_graph": "get_graph",
        "manage_graph": "manage_graph",
        "chat": "chat",
    }
    return route_map.get(action, "chat")


def _route_after_parse(state: AgentState) -> str:
    if state.get("error"):
        return "chat"
    if state.get("web_search_enabled", False):
        return "web_search"
    return "generate_graph"


def _route_after_generate(state: AgentState) -> str:
    if state.get("graph_mermaid") or state.get("graph_markdown"):
        return "save_graph"
    return "chat"


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node("router", router_node)
    builder.add_node("parse_content", parse_content_node)
    builder.add_node("web_search", web_search_node)
    builder.add_node("generate_graph", generate_graph_node)
    builder.add_node("save_graph", save_graph_node)
    builder.add_node("align_concepts", align_concepts_node)
    builder.add_node("list_graphs", list_graphs_node)
    builder.add_node("search_graphs", search_graphs_node)
    builder.add_node("get_graph", get_graph_node)
    builder.add_node("manage_graph", manage_graph_node)
    builder.add_node("summarize_memory", summarize_memory_node)
    builder.add_node("chat", chat_node)

    builder.set_entry_point("router")

    builder.add_conditional_edges("router", _route_after_router, {
        "parse_content": "parse_content",
        "list_graphs": "list_graphs",
        "search_graphs": "search_graphs",
        "get_graph": "get_graph",
        "manage_graph": "manage_graph",
        "chat": "chat",
    })
    builder.add_conditional_edges("parse_content", _route_after_parse, {
        "web_search": "web_search",
        "generate_graph": "generate_graph",
        "chat": "chat",
    })
    builder.add_edge("web_search", "generate_graph")
    builder.add_conditional_edges("generate_graph", _route_after_generate, {
        "save_graph": "save_graph",
        "chat": "chat",
    })
    builder.add_edge("save_graph", "align_concepts")
    builder.add_edge("align_concepts", "summarize_memory")
    builder.add_edge("summarize_memory", END)
    builder.add_edge("list_graphs", END)
    builder.add_edge("search_graphs", END)
    builder.add_edge("get_graph", END)
    builder.add_edge("manage_graph", END)
    builder.add_edge("chat", END)

    if checkpointer:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()
