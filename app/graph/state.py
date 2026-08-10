"""LangGraph AgentState 定义。"""

from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_input: str
    input_type: str
    parsed_content: str
    source_name: str
    output_format: str
    web_search_enabled: bool
    supplementary_info: str
    current_graph_id: str
    graph_mermaid: str
    graph_markdown: str
    node_payloads: str
    memory_snapshot_id: str
    concept_report: dict
    long_text_report: dict
    long_text_tier: str
    long_text_chunks: list[dict]
    chapter_payloads: list[dict]
    long_text_chapter_graph_ids: list[str]
    selected_chapters: list[int]
    action: str
    error: str
