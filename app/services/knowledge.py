"""知识库检索与问答 service：Web /ask 端点与 ReAct tool_ask_knowledge 共用。"""

import re

from app.config import config
from app.logging_config import get_logger
from app.memory import repository
from app.services.llm import get_llm, invoke_safe

logger = get_logger("services.knowledge")

_QUESTION_NOISE = re.compile(
    r"(什么是|怎么|如何|为什么|吗|呢|请|解释|介绍|有哪些|什么|介绍一下|"
    r"的区别|的用途|的原理|好不好|行不行)",
)

_ASK_SYSTEM = (
    "你是学习脉络智能体的知识问答助手。请先检索用户知识库中的内容，再回答问题。\n"
    "回答要求：\n"
    "1. 明确标注「已收录知识」与「知识库未直接覆盖，基于已有知识推理」。\n"
    "2. 如果知识库中没有相关内容，直接说明，不要编造。\n"
    "3. 最后给出 2-3 个值得继续学习的相关方向。\n"
)


def knowledge_query(question: str) -> str:
    """去除疑问词噪声，保留可用于检索的关键词。"""
    cleaned = _QUESTION_NOISE.sub(" ", question)
    cleaned = re.sub(r"[^\w]+", "", cleaned, flags=re.UNICODE).strip()
    return cleaned or question


def build_knowledge_context(query: str) -> tuple[str, list[dict]]:
    """检索知识库（脉络 / 节点 / 记忆摘要 / 原文分块），返回上下文与来源清单。"""
    query = knowledge_query(query)
    sources: list[dict] = []
    parts: list[str] = []
    for graph in repository.search_graphs(query, limit=5):
        sources.append({"type": "graph", "id": graph["id"], "title": graph["title"]})
        raw = (graph.get("raw_content") or "")[:600]
        if raw.strip():
            parts.append(f"[脉络 {graph['title']}]\n{raw}")
    for node in repository.search_nodes(query, limit=10):
        sources.append({
            "type": "node",
            "id": node["id"],
            "graph_id": node["graph_id"],
            "graph_title": node.get("graph_title") or "",
            "label": node["label"],
        })
        note = (node.get("note") or "")[:400]
        if note.strip():
            parts.append(f"[节点 {node['label']}]\n{note}")
    for memory in repository.search_memories(query, limit=5):
        sources.append({
            "type": "memory",
            "id": memory["id"],
            "summary": memory["summary"],
        })
        parts.append(f"[记忆摘要]\n{memory['summary']}")
    for chunk in repository.search_content_chunks(query, limit=5):
        sources.append({
            "type": "chunk",
            "id": chunk["id"],
            "graph_id": chunk["graph_id"],
            "graph_title": chunk.get("graph_title") or "",
            "chunk_index": chunk.get("chunk_index"),
            "text": (chunk.get("text") or "")[:200],
        })
        snippet = (chunk.get("text") or "")[:600]
        if snippet.strip():
            parts.append(
                f"[原文分块 · {chunk.get('graph_title') or chunk['graph_id']} "
                f"#{chunk.get('chunk_index')}]\n{snippet}"
            )
    return "\n\n".join(parts)[:8000], sources


def local_answer(question: str, context: str) -> str:
    """DeepSeek 不可用时的本地降级回答。"""
    if not context.strip():
        return (
            "知识库未直接覆盖该问题。建议先补充相关材料，"
            "或换一个更接近已有脉络的关键词检索。"
        )
    return (
        "已收录知识（本地检索结果）：\n\n"
        f"{context[:1600]}\n\n"
        "（当前 DeepSeek 暂不可用，以上为知识库原文片段；"
        "可稍后重试获得更完整的回答。）"
    )


def ask_llm(question: str, context: str) -> str:
    """基于检索上下文回答问题。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    if not config.DEEPSEEK_API_KEY:
        return local_answer(question, context)
    user = f"## 用户问题\n{question}\n\n## 知识库检索结果\n{context or '（未检索到相关内容）'}"
    try:
        llm = get_llm()
        response = invoke_safe(
            llm,
            [SystemMessage(content=_ASK_SYSTEM), HumanMessage(content=user)],
            context="ask",
        )
        return response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        logger.exception("知识问答 LLM 调用失败: %s", exc)
        return local_answer(question, context)
