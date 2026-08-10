"""LangGraph 节点实现：意图路由、内容解析、确定性生成/保存、概念对齐、记忆持久化。

自由文本的生成 / 对话 / 知识问答交给 ReAct 循环（见 app/graph/agent.py）；
显式命令（list / search / open / 管理 / 文件 / 网址）走本模块的确定性节点。
"""

import re

from app.config import config
from app.graph.state import AgentState
from app.logging_config import get_logger
from app.memory.repository import save_memory_snapshot
from app.services.concept_alignment import align_graph_nodes
from app.services.graph_generation import generate_graph_fields, save_generated_graph
from app.services.llm import get_llm, invoke_structured
from app.prompts.graph_gen import MEMORY_SUMMARY_PROMPT
from app.tools.web_search import search_web
from app.tools.knowledge_graph import (
    tool_list_graphs, tool_search_graphs,
    tool_get_graph, tool_add_node, tool_update_node, tool_delete_node,
    tool_delete_graph,
)

logger = get_logger("graph.nodes")

# 显式命令前缀 → action 映射（规则快速路径，优先级高于 LLM 意图）
_RULE_ROUTES: list[tuple[tuple[str, ...], str]] = [
    (("list", "列表", "列出", "/list"), "list_graphs"),
    (("/node ", "/graph ", "添加节点", "删除节点", "更新节点",
      "修改节点", "关联节点", "删除脉络图"), "manage_graph"),
    (("/open ", "打开 ", "查看脉络 ", "get graph "), "get_graph"),
    (("search ", "搜索 ", "查找 ", "/search ", "回顾 ", "复习 ", "检索 "), "search_graphs"),
    (("files:", "批量文件:", "file:", "文件:", "/file "), "parse_file"),
    (("urls:", "批量网址:", "url:", "网址:", "http://", "https://", "/url "), "parse_url"),
]

_INTENT_ACTIONS = {
    "list_graphs", "search_graphs", "get_graph", "manage_graph",
    "parse_file", "parse_url", "generate_graph", "chat",
}

_INTENT_PROMPT = """你是意图分类器。判断用户想做什么，只输出 JSON：{{"action": "<action>"}}
可选 action（只能选一个）：
- list_graphs：列出/查看所有脉络图
- search_graphs：搜索、检索、回顾、复习已有脉络
- get_graph：打开、查看某一张指定的脉络图
- manage_graph：添加/删除/更新节点，或删除脉络图
- parse_file：解析本地文件
- parse_url：抓取并解析一个网页
- generate_graph：把提供的内容整理生成一张新脉络图
- chat：闲聊、求助、或基于知识库的知识问答

用户输入：{user_input}"""


def _strip_prefix(user_input: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if user_input.lower().startswith(prefix.lower()):
            return user_input[len(prefix):].strip()
    return user_input.strip()


def _rule_route(user_input: str) -> tuple[str, str] | None:
    """规则快速路径：返回 (action, input_type) 或 None。"""
    if not user_input:
        return None
    lower = user_input.lower()
    if lower in ("list", "列表", "列出", "/list"):
        return "list_graphs", "manage"
    for prefixes, action in _RULE_ROUTES:
        if lower.startswith(prefixes):
            input_type = "file" if action == "parse_file" else (
                "url" if action == "parse_url" else "manage"
            )
            return action, input_type
    return None


def _llm_intent(user_input: str) -> str:
    """轻量 LLM 意图分类；失败返回空字符串（由调用方降级到默认）。"""
    if not config.DEEPSEEK_API_KEY:
        return ""
    data = invoke_structured(
        _INTENT_PROMPT.format(user_input=user_input[:800]),
        retries=0,
    )
    if not isinstance(data, dict):
        return ""
    action = str(data.get("action") or "").strip()
    return action if action in _INTENT_ACTIONS else ""


def router_node(state: AgentState) -> dict:
    """入口路由节点：规则快速路径优先，其次轻量 LLM 意图分类，默认走 ReAct。"""
    user_input = state.get("user_input", "").strip()
    if not user_input:
        return {"action": "chat", "input_type": "text"}

    rule = _rule_route(user_input)
    if rule:
        return {"action": rule[0], "input_type": rule[1]}

    # 长内容直接判定为生成脉络，避免无意义的分类调用
    if len(user_input) >= 200:
        return {"action": "generate_graph", "input_type": "text"}

    action = _llm_intent(user_input)
    if action in ("list_graphs", "search_graphs", "get_graph", "manage_graph"):
        return {"action": action, "input_type": "manage"}
    if action == "parse_file":
        return {"action": "parse_file", "input_type": "file"}
    if action == "parse_url":
        return {"action": "parse_url", "input_type": "url"}
    if action == "chat":
        return {"action": "chat", "input_type": "text"}
    return {"action": "generate_graph", "input_type": "text"}


def parse_content_node(state: AgentState) -> dict:
    """内容解析节点：处理文件 / URL / 文本。"""
    action = state.get("action", "")
    user_input = state.get("user_input", "")
    if action == "parse_file":
        raw = _strip_prefix(user_input, ("files:", "批量文件:", "file:", "文件:", "/file "))
        file_paths = [p.strip() for p in re.split(r"[;,；，]", raw) if p.strip()]
        from app.tools.doc_parser import parse_document
        parts = []
        source_name = ""
        for file_path in file_paths:
            result = parse_document(file_path)
            if result.get("error"):
                return {"parsed_content": "", "error": result["error"]}
            if len(file_paths) > 1:
                parts.append(f"### 文件: {result.get('title') or file_path}\n{result['content']}")
            else:
                parts.append(result["content"])
            source_name = result.get("title") or file_path
        return {"parsed_content": "\n\n".join(parts), "source_name": source_name}
    elif action == "parse_url":
        raw = _strip_prefix(user_input, ("urls:", "批量网址:", "url:", "网址:", "/url "))
        urls = [u.strip() for u in re.split(r"[;,；，]", raw) if u.strip()]
        from app.tools.web_fetcher import fetch_url
        parts = []
        source_name = ""
        for url in urls:
            result = fetch_url(url)
            if result.get("error"):
                return {"parsed_content": "", "error": result["error"]}
            if len(urls) > 1:
                parts.append(f"### 网址: {url}\n{result['content']}")
            else:
                parts.append(result["content"])
            source_name = result.get("url") or url
        return {"parsed_content": "\n\n".join(parts), "source_name": source_name}
    else:
        return {"parsed_content": user_input, "source_name": ""}


def web_search_node(state: AgentState) -> dict:
    """联网搜索节点（确定性路径用）：为已解析内容补充搜索上下文。"""
    if not state.get("web_search_enabled", False):
        return {"supplementary_info": ""}
    content = state.get("parsed_content", "")
    query = content[:200] if content else state.get("user_input", "")
    if len(content) > 2000:
        try:
            response = invoke_structured(
                "请从下面内容提炼 2-5 个用于联网搜索的中文关键词或短语，"
                '只输出 JSON：{"query": "关键词"}\n\n'
                f"{content[:6000]}",
                llm=get_llm(),
                retries=0,
            )
            if response and response.get("query"):
                query = str(response["query"]).strip()[:200]
        except Exception as exc:
            logger.warning("搜索关键词提炼失败: %s", exc)
    if not query:
        return {"supplementary_info": ""}
    results = search_web(query)
    if not results or results[0].get("title") == "搜索失败":
        return {"supplementary_info": ""}
    info = "\n".join(
        f"- {r['title']}: {r['content'][:300]}" for r in results[:3]
    )
    return {"supplementary_info": info}


def generate_graph_node(state: AgentState) -> dict:
    """确定性生成节点（文件 / URL 路径）：生成脉络图内容（不落库）。"""
    fields = generate_graph_fields(
        state.get("parsed_content", ""),
        output_format=state.get("output_format", "both"),
        supplementary_info=state.get("supplementary_info", ""),
        selected_chapters=state.get("selected_chapters") or None,
    )
    if fields.get("error"):
        return {"graph_mermaid": "", "graph_markdown": "", "error": fields["error"]}
    return fields


def save_graph_node(state: AgentState) -> dict:
    """确定性保存节点（文件 / URL 路径）：把生成内容落库。"""
    mermaid = state.get("graph_mermaid", "")
    markdown = state.get("graph_markdown", "")
    if not mermaid and not markdown:
        return {}
    return save_generated_graph(
        content=state.get("parsed_content", ""),
        input_type=state.get("input_type", "text"),
        source_name=state.get("source_name", ""),
        graph_mermaid=mermaid,
        graph_markdown=markdown,
        node_payloads=state.get("node_payloads", ""),
        long_text_tier=state.get("long_text_tier", ""),
        long_text_chunks=state.get("long_text_chunks") or [],
        chapter_payloads=state.get("chapter_payloads") or [],
    )


def align_concepts_node(state: AgentState) -> dict:
    """把新保存的脉络图节点对齐到全局概念层。"""
    graph_id = state.get("current_graph_id", "")
    if not graph_id:
        return {"concept_report": {}}
    use_llm = bool(
        config.SEMANTIC_ALIGN_ENABLED
        and config.CONCEPT_LLM_DISAMBIGUATION
        and config.DEEPSEEK_API_KEY
    )
    graph_ids = [graph_id] + list(state.get("long_text_chapter_graph_ids") or [])
    merged = {
        "graph_id": graph_id,
        "aligned_mentions": 0,
        "new_concepts": [],
        "reinforced_concepts": [],
        "new_links": [],
        "pending_links": 0,
        "errors": [],
    }
    try:
        for gid in graph_ids:
            result = align_graph_nodes(gid, llm=get_llm() if use_llm else None)
            merged["aligned_mentions"] += result.aligned
            merged["new_concepts"].extend(result.new_concepts)
            merged["reinforced_concepts"].extend(result.reinforced)
            merged["new_links"].extend(result.new_links)
            merged["pending_links"] += result.pending_links
            merged["errors"].extend(result.errors)
        logger.info("align_concepts graph=%s aligned=%d", graph_id, merged["aligned_mentions"])
        return {"concept_report": merged}
    except Exception as exc:
        logger.exception("概念对齐失败: %s", exc)
        return {"concept_report": {**merged, "error": str(exc)}}


def list_graphs_node(state: AgentState) -> dict:
    """列出所有脉络图。"""
    try:
        result = tool_list_graphs.invoke({"limit": 20})
        return {"parsed_content": result}
    except Exception as exc:
        logger.exception("列出脉络图失败: %s", exc)
        return {"error": str(exc)}


def search_graphs_node(state: AgentState) -> dict:
    """搜索脉络图。"""
    query = _strip_prefix(state.get("user_input", ""), (
        "search ", "搜索 ", "查找 ", "/search ", "回顾 ", "复习 ", "检索 ",
    ))
    try:
        result = tool_search_graphs.invoke({"query": query})
        return {"parsed_content": result}
    except Exception as exc:
        logger.exception("搜索脉络图失败: %s", exc)
        return {"error": str(exc)}


_MANAGE_PATTERNS = [
    (
        re.compile(r"^(?:/node\s+)?(?:add|添加节点)\s+(\S+)\s+(.+)$", re.IGNORECASE),
        "add",
    ),
    (
        re.compile(r"^(?:/node\s+)?(?:delete|del|删除节点)\s+(\S+)\s*$", re.IGNORECASE),
        "delete",
    ),
    (
        re.compile(r"^(?:/node\s+)?(?:update|更新节点|修改节点)\s+(\S+)\s+(.+)$", re.IGNORECASE),
        "update",
    ),
    (
        re.compile(r"^(?:/node\s+)?(?:relate|关联节点)\s+(\S+)\s+(.+)$", re.IGNORECASE),
        "relate",
    ),
    (
        re.compile(r"^(?:/graph\s+)?(?:delete|删除脉络图)\s+(\S+)\s*$", re.IGNORECASE),
        "delete_graph",
    ),
]


def _parse_manage_command(user_input: str) -> tuple[str, list[str]] | None:
    for pattern, command in _MANAGE_PATTERNS:
        m = pattern.match(user_input)
        if m:
            return command, list(m.groups())
    return None


def manage_graph_node(state: AgentState) -> dict:
    """用户手动管理脉络节点的节点。"""
    user_input = state.get("user_input", "").strip()
    parsed = _parse_manage_command(user_input)
    if not parsed:
        return {"parsed_content": "", "error": "无法识别的管理命令，输入 /help 查看用法"}
    command, args = parsed
    try:
        if command == "add":
            graph_id, label = args
            node_id = tool_add_node.invoke({"graph_id": graph_id, "label": label})
            return {"parsed_content": f"[OK] 已添加节点 {node_id}: {label}"}
        if command == "delete":
            return {"parsed_content": tool_delete_node.invoke({"node_id": args[0]})}
        if command == "update":
            node_id, label = args
            return {"parsed_content": tool_update_node.invoke(
                {"node_id": node_id, "label": label}
            )}
        if command == "relate":
            node_id, raw_ids = args
            related = [x.strip() for x in re.split(r"[,;；，]", raw_ids) if x.strip()]
            return {"parsed_content": tool_update_node.invoke(
                {"node_id": node_id, "related_nodes": related}
            )}
        if command == "delete_graph":
            return {"parsed_content": tool_delete_graph.invoke({"graph_id": args[0]})}
    except Exception as exc:
        logger.exception("管理命令执行失败: %s", exc)
        return {"parsed_content": "", "error": str(exc)}
    return {"parsed_content": "", "error": "未知的管理命令错误"}


def get_graph_node(state: AgentState) -> dict:
    """打开指定脉络图，展示图信息与全部节点。"""
    graph_id = _strip_prefix(state.get("user_input", ""), ("/open ", "打开 ", "查看脉络 ", "get graph "))
    try:
        return {"parsed_content": tool_get_graph.invoke({"graph_id": graph_id})}
    except Exception as exc:
        logger.exception("打开脉络图失败: %s", exc)
        return {"parsed_content": "", "error": str(exc)}


def persist_graph_memory_node(state: AgentState) -> dict:
    """把本次生成的脉络内容总结写入长期记忆 memory_snapshots（持久化）。"""
    graph_id = state.get("current_graph_id", "")
    if not graph_id:
        return {}
    source = state.get("graph_markdown") or state.get("parsed_content", "")
    if not source:
        return {}
    prompt = MEMORY_SUMMARY_PROMPT.replace(
        "{content}", source[: config.MAX_CONTENT_LENGTH]
    )
    data = None
    try:
        data = invoke_structured(prompt, retries=1)
    except Exception as exc:
        logger.warning("记忆摘要生成失败: %s", exc)
    if data and isinstance(data, dict) and data.get("summary"):
        summary = str(data["summary"]).strip()
        key_points = [str(k).strip() for k in data.get("key_points", []) if str(k).strip()]
    else:
        summary = (source.strip().splitlines() or ["脉络图摘要"])[0][:80]
        key_points = []
    snap_id = save_memory_snapshot(graph_id, summary, key_points)
    logger.info("memory snapshot saved graph=%s snap=%s", graph_id, snap_id)
    return {"memory_snapshot_id": snap_id}
