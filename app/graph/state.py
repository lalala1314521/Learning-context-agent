"""LangGraph AgentState 定义与初始状态工厂。"""

import operator
from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # ── 对话 / ReAct 轨迹 ──────────────────────────────────────────
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # ReAct 循环轨迹：[{"tool": ..., "tool_input": ..., "observation": ...}]
    intermediate_steps: Annotated[list[dict], operator.add]
    # 对话级摘要（历史超阈值后压缩到此处，供 agent 注入上下文）
    conversation_context: str
    # 最近一次推理文本（LLM 的 Thought）
    thought: str

    # ── 用户输入 ──────────────────────────────────────────────────
    user_input: str
    input_type: str
    parsed_content: str
    source_name: str
    output_format: str
    web_search_enabled: bool
    supplementary_info: str
    learning_goal: str
    generation_depth: str

    # ── 脉络图结果 ────────────────────────────────────────────────
    current_graph_id: str
    graph_mermaid: str
    graph_markdown: str
    node_payloads: str
    memory_snapshot_id: str

    # ── 概念层 / 长文本 ────────────────────────────────────────────
    concept_report: dict
    long_text_report: dict
    long_text_tier: str
    long_text_chunks: list[dict]
    chapter_payloads: list[dict]
    long_text_chapter_graph_ids: list[str]
    selected_chapters: list[int]

    # ── 流程控制 ──────────────────────────────────────────────────
    action: str
    error: str


def build_initial_state(
    user_input: str,
    output_format: str = "both",
    web_search_enabled: bool = False,
    selected_chapters: list[int] | None = None,
    learning_goal: str = "理解主线",
    generation_depth: str = "standard",
    input_type: str = "text",
    **overrides,
) -> dict:
    """统一的初始状态工厂：CLI / Web / 测试共用。

    传入 overrides 可覆盖任意字段（例如 source_name、parsed_content）。
    """
    fmt = "both" if output_format in ("auto", "both") else output_format
    state = {
        "messages": [],
        "intermediate_steps": [],
        "conversation_context": "",
        "thought": "",
        "user_input": (user_input or "").strip(),
        "input_type": input_type,
        "parsed_content": "",
        "source_name": "",
        "output_format": fmt,
        "web_search_enabled": web_search_enabled,
        "supplementary_info": "",
        "learning_goal": learning_goal or "理解主线",
        "generation_depth": generation_depth or "standard",
        "current_graph_id": "",
        "graph_mermaid": "",
        "graph_markdown": "",
        "node_payloads": "",
        "memory_snapshot_id": "",
        "concept_report": {},
        "long_text_report": {},
        "long_text_tier": "",
        "long_text_chunks": [],
        "chapter_payloads": [],
        "long_text_chapter_graph_ids": [],
        "selected_chapters": selected_chapters or [],
        "action": "",
        "error": "",
    }
    state.update(overrides)
    return state
