"""ReAct 交互工具集：供 Agent 在循环内自主决策调用的高级工具。

这些工具内部桥接到确定性管线（生成落库 / 文档解析 / 知识问答），
实现"ReAct 决策 + 确定性执行"的混合架构。
"""

import json

from langchain_core.tools import tool

from app.logging_config import get_logger
from app.memory import repository
from app.services.graph_generation import generate_and_save_graph

logger = get_logger("tools.react")


@tool
def tool_generate_graph(content: str, output_format: str = "both") -> str:
    """根据用户提供的文本内容生成一张知识脉络图并保存到知识库，返回脉络图信息。

    这是"把内容整理成脉络图"的主要工具。当用户要求生成/整理/总结一份内容为
    知识脉络时调用它。不要自行拼接 Mermaid 代码调用 tool_create_graph。

    Args:
        content: 用户提供的正文内容（一段文字/粘贴的笔记/已解析的文档内容）
        output_format: 输出格式，both / mermaid / markdown
    """
    result = generate_and_save_graph(content, output_format=output_format)
    if result.get("error"):
        return f"脉络图生成失败: {result['error']}"
    graph_id = result["current_graph_id"]
    node_count = len(repository.get_nodes(graph_id)) if graph_id else 0
    logger.info("tool_generate_graph done graph_id=%s nodes=%d", graph_id, node_count)
    return json.dumps({
        "graph_id": graph_id,
        "node_count": node_count,
        "graph_mermaid": result.get("graph_mermaid") or "",
        "graph_markdown": result.get("graph_markdown") or "",
        "long_text_report": result.get("long_text_report") or {},
        "long_text_tier": result.get("long_text_tier") or "",
        "long_text_chapter_graph_ids": result.get("long_text_chapter_graph_ids") or [],
    }, ensure_ascii=False)


@tool
def tool_web_search(query: str) -> str:
    """联网搜索，返回与查询相关的网页摘要列表。用于补充当前知识的背景信息。

    Args:
        query: 搜索关键词（简洁、聚焦主题）
    """
    from app.tools.web_search import search_web

    results = search_web(query)
    if not results or results[0].get("title") == "搜索失败":
        return "联网搜索失败，请稍后重试或直接基于已有知识回答。"
    lines = []
    for r in results[:5]:
        lines.append(f"- {r['title']}: {r['content'][:200]}")
    return "\n".join(lines) if lines else "未找到相关结果。"


@tool
def tool_parse_file(path: str) -> str:
    """解析本地文档（TXT/MD/PDF/DOCX/IPYNB 等），返回文档标题与正文内容。

    仅在用户明确给出本地文件路径时使用。

    Args:
        path: 本地文件路径
    """
    from app.tools.doc_parser import parse_document

    result = parse_document(path)
    if result.get("error"):
        return f"文件解析失败: {result['error']}"
    content = (result.get("content") or "")[:12000]
    return json.dumps({
        "title": result.get("title") or path,
        "content": content,
        "truncated": len(result.get("content") or "") > 12000,
    }, ensure_ascii=False)


@tool
def tool_parse_url(url: str) -> str:
    """抓取并解析一个网页 URL，返回网页标题与正文内容。

    仅在用户明确给出网址时使用。

    Args:
        url: 完整的 http/https 网址
    """
    from app.tools.web_fetcher import fetch_url

    result = fetch_url(url)
    if result.get("error"):
        return f"网页抓取失败: {result['error']}"
    content = (result.get("content") or "")[:12000]
    return json.dumps({
        "title": result.get("title") or url,
        "content": content,
        "truncated": len(result.get("content") or "") > 12000,
    }, ensure_ascii=False)


@tool
def tool_ask_knowledge(question: str) -> str:
    """基于知识库回答问题；知识库覆盖不足时自动联网检索补充，综合推理后返回回答。

    Args:
        question: 用户的知识性问题
    """
    from app.services.knowledge import answer_question

    result = answer_question(question)
    suffix = ""
    if result["web_fallback_used"]:
        suffix = "\n\n（注：已自动联网搜索补充，请核实具体来源链接。）"
    return f"{result['answer']}{suffix}"
