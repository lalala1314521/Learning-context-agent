"""脉络图生成 + 落库 service：解析 → 分层生成 → 校验 → 保存。

确定性生成管线的唯一入口：
- 显式命令路径（parse_file / parse_url）经 nodes.generate_graph_node + save_graph_node 调用；
- ReAct 路径经 tools.react_tools.tool_generate_graph 组合调用。
"""

import json
import re
import uuid

from app.config import config
from app.logging_config import get_logger
from app.graph.mermaid_parser import parse_graph_structure
from app.memory.repository import (
    add_node as repo_add_node,
    create_graph as repo_create_graph,
    save_content_chunks,
)
from app.memory.embeddings import embed_texts
from app.prompts.graph_gen import GRAPH_GEN_PROMPT
from app.services.chunking import chunk_content, classify_content
from app.services.llm import estimate_tokens, get_llm, invoke_safe, invoke_structured
from app.services.longtext import (
    create_book_subgraphs,
    map_reduce,
    prepare_book_payload,
)
from app.services.mermaid import repair_instruction, validate_mermaid

logger = get_logger("services.graph_generation")

_MERMAID_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_MARKDOWN_RE = re.compile(r"【Markdown大纲】:\s*\n(.*?)(?=【|\Z)", re.DOTALL)
# 【节点数据】多种格式：代码块包裹 / 单行数组 / 带冒号变体
_NODE_PAYLOADS_FENCED_RE = re.compile(
    r"【节点数据】\s*[:：]?\s*\n?```(?:json)?\s*\n(\[.*?\])\s*```", re.DOTALL
)
_NODE_PAYLOADS_INLINE_RE = re.compile(
    r"【节点数据】\s*[:：]?\s*\n?(\[[^\n]*?\])", re.DOTALL
)


def _find_json_array(text: str) -> str | None:
    """按括号配平找到文本中第一个 JSON 数组子串（跳过字符串内的括号）。"""
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _extract_node_payloads(text: str) -> str:
    """鲁棒地提取节点数据 JSON 数组，兼容 LLM 输出格式漂移。"""
    candidates: list[str] = []
    for pattern in (_NODE_PAYLOADS_FENCED_RE, _NODE_PAYLOADS_INLINE_RE):
        m = pattern.search(text)
        if m:
            candidates.append(m.group(1))
    anchor = re.search(r"【节点数据】", text)
    if anchor:
        arr = _find_json_array(text[anchor.end():])
        if arr:
            candidates.append(arr)
    arr = _find_json_array(text)
    if arr:
        candidates.append(arr)
    for candidate in candidates:
        try:
            payloads = json.loads(candidate)
            if (isinstance(payloads, list) and payloads
                    and isinstance(payloads[0], dict) and "label" in payloads[0]):
                return json.dumps(payloads, ensure_ascii=False)
        except Exception:
            continue
    return ""


def _extract_graph_output(text: str) -> dict:
    """从 LLM 生成文本中提取 mermaid / markdown / 节点数据。"""
    mermaid = ""
    markdown = ""
    mermaid_match = _MERMAID_RE.search(text)
    if mermaid_match:
        mermaid = mermaid_match.group(1).strip()
    md_match = _MARKDOWN_RE.search(text)
    if md_match:
        markdown = md_match.group(1).strip()
    elif not mermaid:
        markdown = text.strip()
    return {
        "graph_mermaid": mermaid,
        "graph_markdown": markdown,
        "node_payloads": _extract_node_payloads(text),
    }


def _invoke_text(llm, prompt: str) -> str:
    from langchain_core.messages import HumanMessage

    if llm is None:
        return ""
    try:
        response = invoke_safe(llm, [HumanMessage(content=prompt)], context="graph_gen")
        return response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        logger.exception("单次生成 LLM 调用失败: %s", exc)
        return ""


def _generate_single_shot(content: str, output_format: str, llm) -> dict:
    """S 级内容：单次 LLM 调用生成，带 Mermaid 校验 + 1 次重试 + 节点详情兜底。"""
    prompt = GRAPH_GEN_PROMPT.replace("{content}", content[: config.MAX_CONTENT_LENGTH])
    last_reason = ""
    output: dict = {}
    for _attempt in range(2):
        text = _invoke_text(
            llm, prompt + (repair_instruction(last_reason) if last_reason else "")
        )
        output = _extract_graph_output(text)
        mermaid = output["graph_mermaid"]
        if not mermaid:
            break  # 无 Mermaid 时按 markdown 处理，不重试
        ok, reason = validate_mermaid(mermaid)
        if ok:
            break
        logger.warning("Mermaid 校验失败，重试: %s", reason)
        last_reason = reason
        output["graph_mermaid"] = ""
    # 节点详情兜底：主生成未产出【节点数据】时，用一次轻量调用补全
    if output.get("graph_mermaid") and not output.get("node_payloads"):
        enriched = _enrich_node_payloads(output["graph_mermaid"], content, llm)
        if enriched:
            output["node_payloads"] = enriched
            logger.info("节点详情兜底补全 %d 节点", len(json.loads(enriched)))
    if output_format == "mermaid":
        output["graph_markdown"] = ""
    elif output_format == "markdown":
        output["graph_mermaid"] = ""
    return output


def _enrich_node_payloads(mermaid: str, content: str, llm) -> str:
    """从 Mermaid + 源内容用一次 LLM 调用补全节点详情 JSON 数组。"""
    if llm is None or not mermaid:
        return ""
    prompt = (
        "下面是已生成的 Mermaid 脉络图与源内容。请为图中的每个节点补充详情，"
        "输出 JSON 对象 {{\"nodes\": [...]}}，nodes 为数组，每项字段："
        "id(与 Mermaid 一致或自增), label(节点文本), "
        "note(1-2 句具体解释/关键句/例子，不能为空), "
        "node_type(concept/method/case/formula/conclusion), "
        "parent_id(本图内父节点 id 或空串), related_nodes(本图内关联 id 列表)。"
        "只输出 JSON。\n\nMermaid:\n{mermaid}\n\n源内容:\n{content}"
    )
    data = invoke_structured(
        prompt.format(mermaid=mermaid[:4000], content=content[:6000]),
        llm=llm,
        retries=1,
    )
    if not isinstance(data, dict):
        return ""
    nodes = data.get("nodes")
    if isinstance(nodes, list) and nodes:
        return json.dumps(nodes, ensure_ascii=False)
    return ""


def _detect_graph_type(mermaid: str) -> str:
    if not mermaid:
        return "markdown"
    lower = mermaid.lower()
    if "flowchart" in lower:
        return "mermaid_flow"
    if "mindmap" in lower:
        return "mermaid_mindmap"
    return "mermaid_tree"


def generate_graph_fields(
    content: str,
    output_format: str = "both",
    supplementary_info: str = "",
    selected_chapters: list[int] | None = None,
    llm=None,
) -> dict:
    """生成脉络图内容（不落库），返回 graph_mermaid / graph_markdown / node_payloads
    及 long_text 相关字段。出错时返回 {"error": ...}。"""
    content = (content or "").strip()
    if not content:
        return {"error": "没有可解析的内容"}
    if supplementary_info:
        content = f"{content}\n\n## 联网搜索补充信息\n{supplementary_info}"

    logger.info("generate_graph_fields ~%dtok", estimate_tokens(content))
    current = llm if llm is not None else (get_llm() if config.DEEPSEEK_API_KEY else None)
    fmt = "both" if output_format in ("auto", "both") else output_format
    tier = classify_content(content)

    result: dict = {}
    if tier == "M":
        mr = map_reduce(content, llm=current)
        mermaid, markdown = mr["mermaid"], mr["markdown"]
        if fmt == "mermaid":
            markdown = ""
        elif fmt == "markdown":
            mermaid = ""
        result.update({
            "graph_mermaid": mermaid,
            "graph_markdown": markdown,
            "node_payloads": json.dumps(mr.get("node_payloads", []), ensure_ascii=False),
            "long_text_report": mr["report"],
            "long_text_tier": tier,
            "long_text_chunks": mr.get("chunks", []),
            "chapter_payloads": [],
        })
    elif tier == "L":
        book = prepare_book_payload(
            content, llm=current, selected_indices=selected_chapters or None
        )
        mermaid, markdown = book["mermaid"], book["markdown"]
        if fmt == "mermaid":
            markdown = ""
        elif fmt == "markdown":
            mermaid = ""
        result.update({
            "graph_mermaid": mermaid,
            "graph_markdown": markdown,
            "node_payloads": "",
            "long_text_report": book["report"],
            "long_text_tier": tier,
            "long_text_chunks": [],
            "chapter_payloads": book.get("chapter_payloads", []),
        })
    else:
        output = _generate_single_shot(content, fmt, current)
        result.update(output)
        result.update({
            "long_text_report": {"tier": "S"},
            "long_text_tier": "S",
            "long_text_chunks": [],
            "chapter_payloads": [],
        })
    # 统一 Mermaid 校验（S 级已带重试；此处为 M/L 级与降级路径补记日志）
    mermaid = result.get("graph_mermaid") or ""
    if mermaid:
        valid, reason = validate_mermaid(mermaid)
        if not valid:
            logger.warning("Mermaid 校验未通过（保留原样入库）: %s", reason)
    if not result.get("graph_mermaid") and not result.get("graph_markdown"):
        return {"error": "LLM 未生成有效的脉络图内容"}
    return result


def save_generated_graph(
    *,
    content: str,
    input_type: str,
    source_name: str,
    graph_mermaid: str,
    graph_markdown: str,
    node_payloads: str,
    long_text_tier: str,
    long_text_chunks: list[dict],
    chapter_payloads: list[dict],
) -> dict:
    """把已生成的内容落库（脉络图 + 节点 + 分块 + 书章节子图）。

    Returns:
        {"current_graph_id": ..., "long_text_chapter_graph_ids": [...], "error": ...}
    """
    mermaid = graph_mermaid or ""
    markdown = graph_markdown or ""
    if not mermaid and not markdown:
        return {"current_graph_id": "", "long_text_chapter_graph_ids": [], "error": "没有可保存的脉络内容"}

    content = content or ""
    graph_type = _detect_graph_type(mermaid)
    title = source_name or content[:50].replace("\n", " ").strip()
    graph_id = repo_create_graph(
        title=title,
        description=f"由 Agent 自动生成的脉络图 - {input_type}",
        graph_type=graph_type,
        mermaid_code=mermaid,
        markdown_outline=markdown,
        raw_content=content,
        source_type=input_type,
        source_name=source_name,
    )
    logger.info("graph saved id=%s type=%s", graph_id, graph_type)

    chunks = list(long_text_chunks)
    if not chunks and long_text_tier != "L":
        chunk_items = chunk_content(content or "")
        vectors = embed_texts([c["text"] for c in chunk_items])
        for chunk, vector in zip(chunk_items, vectors):
            chunk["embedding"] = vector
        chunks = chunk_items
    try:
        if chunks:
            save_content_chunks(graph_id, chunks)
    except Exception as exc:
        logger.exception("保存内容分块失败: %s", exc)

    payloads: list[dict] = []
    try:
        raw_payloads = node_payloads or ""
        if raw_payloads:
            parsed = json.loads(raw_payloads)
            if isinstance(parsed, list):
                payloads = parsed
    except Exception as exc:
        logger.warning("解析节点数据失败: %s", exc)
        payloads = []

    try:
        if payloads:
            # LLM 节点 id 常为短串（A/B/C），而 graph_nodes.id 是全局主键，
            # 直接复用会导致跨图 UNIQUE 冲突。这里统一分配全局唯一 id，
            # 并把 parent_id / related_nodes 从 LLM 短 id 重映射到新 id。
            id_map: dict[str, str] = {}
            assigned: list[str] = []
            for node in payloads:
                raw_id = str(node.get("id") or "").strip()
                new_id = uuid.uuid4().hex[:12]
                assigned.append(new_id)
                if raw_id:
                    id_map[raw_id] = new_id
            for index, node in enumerate(payloads):
                parent = str(node.get("parent_id") or "").strip()
                related = [str(x).strip() for x in (node.get("related_nodes") or [])]
                repo_add_node(
                    graph_id,
                    label=str(node.get("label") or "").strip(),
                    note=str(node.get("note") or "").strip(),
                    node_type=str(node.get("node_type") or "concept"),
                    parent_id=id_map.get(parent) if parent else None,
                    related_nodes=[x for x in (id_map.get(r) for r in related) if x],
                    order_index=int(node.get("order_index") or index),
                    created_by="agent",
                    node_id=assigned[index],
                )
        else:
            for node in parse_graph_structure(mermaid, markdown):
                repo_add_node(
                    graph_id,
                    label=node["label"],
                    parent_id=node["parent_id"],
                    related_nodes=node["related_nodes"],
                    order_index=node["order_index"],
                    created_by="agent",
                    node_id=node["id"],
                )
    except Exception as exc:
        logger.exception("保存节点失败: %s", exc)

    chapter_ids: list[str] = []
    if long_text_tier == "L":
        try:
            subgraphs = create_book_subgraphs(graph_id, chapter_payloads or [])
            chapter_ids = [item["graph_id"] for item in subgraphs]
        except Exception as exc:
            logger.exception("章节子图生成失败: %s", exc)
            return {
                "current_graph_id": graph_id,
                "long_text_chapter_graph_ids": [],
                "error": f"章节子图生成失败: {exc}",
            }
    return {
        "current_graph_id": graph_id,
        "long_text_chapter_graph_ids": chapter_ids,
    }


def generate_and_save_graph(
    content: str,
    output_format: str = "both",
    supplementary_info: str = "",
    source_name: str = "",
    input_type: str = "text",
    selected_chapters: list[int] | None = None,
    llm=None,
) -> dict:
    """生成并保存脉络图（ReAct tool_generate_graph 使用），返回完整结果字段。"""
    fields = generate_graph_fields(
        content,
        output_format=output_format,
        supplementary_info=supplementary_info,
        selected_chapters=selected_chapters,
        llm=llm,
    )
    if fields.get("error"):
        return fields
    saved = save_generated_graph(
        content=content,
        input_type=input_type,
        source_name=source_name,
        graph_mermaid=fields.get("graph_mermaid") or "",
        graph_markdown=fields.get("graph_markdown") or "",
        node_payloads=fields.get("node_payloads") or "",
        long_text_tier=fields.get("long_text_tier") or "",
        long_text_chunks=fields.get("long_text_chunks") or [],
        chapter_payloads=fields.get("chapter_payloads") or [],
    )
    fields.update(saved)
    fields["long_text_chapter_graph_ids"] = saved.get("long_text_chapter_graph_ids") or []
    return fields
