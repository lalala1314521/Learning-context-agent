"""知识库问答 service：混合 RAG（关键词 LIKE + 向量检索）+ 覆盖率不足时联网兜底。

Web /ask 端点与 ReAct tool_ask_knowledge 共用。
"""

import re

from app.config import config
from app.logging_config import get_logger
from app.memory import repository
from app.services.llm import estimate_tokens, get_llm, invoke_safe

logger = get_logger("services.knowledge")

_QUESTION_NOISE = re.compile(
    r"(什么是|怎么|如何|为什么|吗|呢|请|解释|介绍|有哪些|什么|介绍一下|"
    r"的区别|的用途|的原理|好不好|行不行)",
)

_ASK_SYSTEM = (
    "你是学习脉络智能体的知识问答助手，综合「已收录知识」与「联网搜索结果」回答问题。\n"
    "回答要求：\n"
    "1. 优先使用「已收录知识」回答，并明确标注来源类型（已收录 / 联网搜索）。\n"
    "2. 知识库覆盖不足时，请综合联网搜索到的内容推理，引用时给出资料来源标题或链接。\n"
    "3. 如果联网与知识库都未覆盖该问题，直接说明，不要编造。\n"
    "4. 最后给出 2-3 个值得继续学习的相关方向。\n"
)

# 覆盖率低于该字符数时触发联网兜底
_KB_COVERAGE_THRESHOLD = 300


def knowledge_query(question: str) -> str:
    """去除疑问词噪声，保留可用于检索的关键词。"""
    cleaned = _QUESTION_NOISE.sub(" ", question)
    cleaned = re.sub(r"[^\w]+", "", cleaned, flags=re.UNICODE).strip()
    return cleaned or question


def build_knowledge_context(query: str) -> tuple[str, list[dict]]:
    """从知识库检索（脉络 / 节点 / 记忆摘要 / 原文分块），返回上下文与来源清单。"""
    query = knowledge_query(query)
    sources: list[dict] = []
    parts: list[str] = []
    for graph in repository.search_graphs(query, limit=5):
        raw = (graph.get("raw_content") or "")[:600]
        sources.append({"type": "graph", "id": graph["id"], "graph_id": graph["id"], "title": graph["title"], "snippet": raw[:240]})
        if raw.strip():
            parts.append(f"[脉络 {graph['title']}]\n{raw}")
    for node in repository.search_nodes(query, limit=10):
        sources.append({
            "type": "node",
            "id": node["id"],
            "graph_id": node["graph_id"],
            "graph_title": node.get("graph_title") or "",
            "title": node.get("graph_title") or node["label"],
            "label": node["label"],
            "snippet": (node.get("note") or "")[:240],
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
            "title": chunk.get("graph_title") or chunk["graph_id"],
            "snippet": (chunk.get("text") or "")[:240],
        })
        snippet = (chunk.get("text") or "")[:600]
        if snippet.strip():
            parts.append(
                f"[原文分块 · {chunk.get('graph_title') or chunk['graph_id']} "
                f"#{chunk.get('chunk_index')}]\n{snippet}"
            )
    return "\n\n".join(parts)[:8000], sources


def _web_retrieval(query: str, fetch_top: int = 1) -> tuple[list[str], list[dict]]:
    """联网检索（Tavily），并尽力抓取前几条权威来源的正文。"""
    from app.tools.web_search import search_web

    results = search_web(query)
    if not results or results[0].get("title") == "搜索失败":
        return [], []
    parts: list[str] = []
    sources: list[dict] = []
    for r in results[: config.TAVILY_MAX_RESULTS]:
        sources.append({
            "type": "web",
            "title": r.get("title", ""),
            "url": r.get("url", ""),
        })
        snippet = (r.get("content") or "")[:300]
        if snippet.strip():
            parts.append(f"[联网 · {r.get('title', '')}]({r.get('url', '')})\n{snippet}")

    # 尽力抓取最权威的前几条页面正文，丰富上下文
    fetched = 0
    for r in results:
        if fetched >= fetch_top:
            break
        url = r.get("url", "")
        if not url:
            continue
        try:
            from app.tools.web_fetcher import fetch_url
            page = fetch_url(url)
        except Exception as exc:
            logger.warning("联网抓取失败 %s: %s", url, exc)
            continue
        if page.get("error") or not page.get("content"):
            continue
        text = page["content"][:4000]
        title = page.get("title") or r.get("title", "")
        parts.insert(0, f"[网页正文 · {title}]({url})\n{text}")
        fetched += 1
    return parts, sources


def answer_question(
    question: str,
    use_database: bool = True,
    web_fallback: bool = True,
    on_event=None,
) -> dict:
    """混合 RAG 问答：知识库检索 → 覆盖率不足时联网兜底 → LLM 综合回答。

    on_event：可选回调，接收 {"type","text","detail","tokens"} 轨迹事件，
    供前端实时展示 Agent 思考链（与图谱生成轨迹同构）。

    Returns:
        {"answer": str, "sources": list[dict], "has_sources": bool,
         "web_fallback_used": bool, "coverage": int}
    """
    def emit(event: dict) -> None:
        if on_event:
            on_event(event)

    sources: list[dict] = []
    parts: list[str] = []
    kb_context = ""
    emit({"type": "thought", "text": "正在检索知识库（脉络/节点/记忆/原文分块）…", "detail": "", "tokens": 0})
    if use_database:
        kb_context, kb_sources = build_knowledge_context(question)
        sources.extend(kb_sources)
        if kb_context.strip():
            parts.append(f"## 已收录知识\n{kb_context}")
    source_labels = [
        s.get("title") or s.get("label") or s.get("summary") or s.get("id")
        for s in sources[:8]
    ]
    emit({
        "type": "tool",
        "text": f"知识库检索完成：{len(sources)} 个来源命中",
        "detail": "\n".join(f"- {label}" for label in source_labels) or "（未命中）",
        "tokens": estimate_tokens(kb_context),
    })

    coverage = sum(len(p) for p in parts)
    web_used = False
    if web_fallback and coverage < _KB_COVERAGE_THRESHOLD and config.TAVILY_API_KEY:
        query = knowledge_query(question)
        emit({
            "type": "action",
            "text": "知识库覆盖不足，自动联网搜索补充",
            "detail": f"搜索关键词：{query}",
            "tokens": 0,
        })
        web_parts, web_sources = _web_retrieval(query)
        if web_sources:
            web_used = True
            sources.extend(web_sources)
            if web_parts:
                parts.append(f"## 联网搜索结果\n{chr(10).join(web_parts)}")
            emit({
                "type": "tool",
                "text": f"联网搜索返回 {len(web_sources)} 条来源",
                "detail": "\n".join(f"- {s.get('title') or s.get('url')}" for s in web_sources[:5]),
                "tokens": estimate_tokens(" ".join(web_parts)),
            })
            logger.info("知识问答联网兜底触发，覆盖率 %d chars", coverage)

    emit({"type": "thought", "text": "综合已有知识与检索结果，组织回答…", "detail": "", "tokens": 0})
    context = "\n\n".join(parts)[:14000]
    answer = ask_llm(question, context)
    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "has_sources": bool(sources),
        "web_fallback_used": web_used,
        "coverage": coverage,
    }


def local_answer(question: str, context: str) -> str:
    """DeepSeek 不可用时的本地降级回答。"""
    if not context.strip():
        return (
            "知识库未直接覆盖该问题，且当前无法联网或调用模型。"
            "建议补充相关材料，或换一个更接近已有脉络的关键词检索。"
        )
    return (
        "已收录知识（本地检索结果）：\n\n"
        f"{context[:1600]}\n\n"
        "（当前 DeepSeek 暂不可用，以上为知识库原文片段；"
        "可稍后重试获得更完整的回答。）"
    )


def ask_llm(question: str, context: str) -> str:
    """基于检索上下文（知识库 + 联网）回答问题。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    if not config.DEEPSEEK_API_KEY:
        return local_answer(question, context)
    user = f"## 用户问题\n{question}\n\n## 检索结果\n{context or '（未检索到相关内容）'}"
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
