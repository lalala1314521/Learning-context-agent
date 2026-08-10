"""LangGraph 节点实现：路由、内容解析、脉络图生成、记忆总结。"""

import json
import re
from app.config import config
from app.graph.mermaid_parser import parse_graph_structure
from app.graph.state import AgentState
from app.memory.repository import add_node as repo_add_node, save_memory_snapshot
from app.prompts.system import SYSTEM_PROMPT
from app.prompts.graph_gen import GRAPH_GEN_PROMPT, MEMORY_SUMMARY_PROMPT
from app.tools.web_search import search_web
from app.tools.knowledge_graph import (
    tool_create_graph, tool_list_graphs, tool_search_graphs,
    tool_get_graph, tool_add_node, tool_update_node, tool_delete_node,
    tool_delete_graph,
)
from langchain_core.messages import HumanMessage, SystemMessage


def _get_llm(model: str | None = None):
    from langchain_deepseek import ChatDeepSeek
    return ChatDeepSeek(
        model=model or config.DEEPSEEK_CHAT_MODEL,
        api_key=config.DEEPSEEK_API_KEY,
        api_base=config.DEEPSEEK_BASE_URL,
        temperature=0.3,
    )


def _strip_prefix(user_input: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if user_input.lower().startswith(prefix.lower()):
            return user_input[len(prefix):].strip()
    return user_input.strip()


def router_node(state: AgentState) -> dict:
    """入口路由节点：识别用户意图，设置 action。"""
    user_input = state.get("user_input", "").strip()
    if not user_input:
        return {"action": "chat", "input_type": "text"}
    lower = user_input.lower()
    if lower in ("list", "列表", "列出", "/list"):
        return {"action": "list_graphs", "input_type": "manage"}
    if lower.startswith((
        "/node ", "/graph ", "添加节点", "删除节点", "更新节点",
        "修改节点", "关联节点", "删除脉络图",
    )):
        return {"action": "manage_graph", "input_type": "manage"}
    if lower.startswith(("/open ", "打开 ", "查看脉络 ", "get graph ")):
        return {"action": "get_graph", "input_type": "manage"}
    if lower.startswith(("search ", "搜索 ", "查找 ", "/search ",
                         "回顾 ", "复习 ", "检索 ")):
        return {"action": "search_graphs", "input_type": "manage"}
    if lower.startswith(("files:", "批量文件:", "file:", "文件:", "/file ")):
        return {"action": "parse_file", "input_type": "file"}
    if lower.startswith(("urls:", "批量网址:", "url:", "网址:",
                         "http://", "https://", "/url ")):
        return {"action": "parse_url", "input_type": "url"}
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
        content = "\n\n".join(parts)[:config.MAX_CONTENT_LENGTH]
        return {"parsed_content": content, "source_name": source_name}
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
        content = "\n\n".join(parts)[:config.MAX_CONTENT_LENGTH]
        return {"parsed_content": content, "source_name": source_name}
    else:
        return {"parsed_content": user_input[:config.MAX_CONTENT_LENGTH], "source_name": ""}


def web_search_node(state: AgentState) -> dict:
    """联网搜索节点：补充搜索上下文。"""
    if not state.get("web_search_enabled", False):
        return {"supplementary_info": ""}
    content = state.get("parsed_content", "")
    query = content[:200] if content else state.get("user_input", "")
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
    """脉络图生成节点：调用 LLM 生成 Mermaid + Markdown。"""
    content = state.get("parsed_content", "")
    supplementary = state.get("supplementary_info", "")
    if not content:
        return {"graph_mermaid": "", "graph_markdown": "", "error": "没有可解析的内容"}
    if supplementary:
        content = f"{content}\n\n## 联网搜索补充信息\n{supplementary}"
    prompt = GRAPH_GEN_PROMPT.replace("{content}", content)
    llm = _get_llm()
    response = llm.invoke([HumanMessage(content=prompt)])
    text = response.content if hasattr(response, "content") else str(response)
    mermaid = ""
    markdown = ""
    mermaid_match = re.search(r"```mermaid\s*\n(.*?)```", text, re.DOTALL)
    if mermaid_match:
        mermaid = mermaid_match.group(1).strip()
    md_match = re.search(r"【Markdown大纲】:\s*\n(.*?)(?=【|\Z)", text, re.DOTALL)
    if md_match:
        markdown = md_match.group(1).strip()
    elif not mermaid:
        markdown = text
    node_payloads = ""
    json_match = re.search(r"【节点数据】:\s*\n```(?:json)?\s*\n(\[.*?\])\s*```", text, re.DOTALL)
    if json_match:
        try:
            payloads = json.loads(json_match.group(1))
            if isinstance(payloads, list) and payloads:
                node_payloads = json.dumps(payloads, ensure_ascii=False)
        except Exception:
            node_payloads = ""
    output_format = state.get("output_format", "both")
    if output_format == "mermaid":
        markdown = ""
    elif output_format == "markdown":
        mermaid = ""
    return {
        "graph_mermaid": mermaid,
        "graph_markdown": markdown,
        "node_payloads": node_payloads,
    }


def save_graph_node(state: AgentState) -> dict:
    """保存脉络图到数据库。"""
    mermaid = state.get("graph_mermaid", "")
    markdown = state.get("graph_markdown", "")
    content = state.get("parsed_content", "")
    input_type = state.get("input_type", "text")
    source_name = state.get("source_name", "")
    if not mermaid and not markdown:
        return {}
    title_text = source_name or content[:50].replace("\n", " ").strip()
    graph_type = "auto"
    if mermaid:
        if "flowchart" in mermaid.lower():
            graph_type = "mermaid_flow"
        elif "mindmap" in mermaid.lower():
            graph_type = "mermaid_mindmap"
        else:
            graph_type = "mermaid_tree"
    else:
        graph_type = "markdown"
    try:
        graph_id = tool_create_graph.invoke({
            "title": title_text,
            "description": f"由 Agent 自动生成的脉络图 - {input_type}",
            "graph_type": graph_type,
            "mermaid_code": mermaid,
            "markdown_outline": markdown,
            "raw_content": content,
            "source_type": input_type,
            "source_name": source_name,
        })
    except Exception as e:
        return {"error": f"保存脉络图失败: {e}"}
    payloads = []
    try:
        raw_payloads = state.get("node_payloads", "")
        if raw_payloads:
            parsed = json.loads(raw_payloads)
            if isinstance(parsed, list):
                payloads = parsed
    except Exception:
        payloads = []
    try:
        if payloads:
            for index, node in enumerate(payloads):
                repo_add_node(
                    graph_id,
                    label=str(node.get("label") or "").strip(),
                    note=str(node.get("note") or "").strip(),
                    node_type=str(node.get("node_type") or "concept"),
                    parent_id=(node.get("parent_id") or None),
                    related_nodes=node.get("related_nodes") or [],
                    order_index=int(node.get("order_index") or index),
                    created_by="agent",
                    node_id=str(node.get("id") or ""),
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
    except Exception:
        pass
    return {"current_graph_id": graph_id}


def list_graphs_node(state: AgentState) -> dict:
    """列出所有脉络图。"""
    try:
        result = tool_list_graphs.invoke({"limit": 20})
        return {"parsed_content": result}
    except Exception as e:
        return {"error": str(e)}


def search_graphs_node(state: AgentState) -> dict:
    """搜索脉络图。"""
    user_input = state.get("user_input", "")
    query = _strip_prefix(user_input, (
        "search ", "搜索 ", "查找 ", "/search ", "回顾 ", "复习 ", "检索 ",
    ))
    try:
        result = tool_search_graphs.invoke({"query": query})
        return {"parsed_content": result}
    except Exception as e:
        return {"error": str(e)}


def chat_node(state: AgentState) -> dict:
    """闲聊 / 帮助节点。"""
    llm = _get_llm()
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    history = state.get("messages", [])
    if history:
        messages.extend(list(history))
    messages.append(HumanMessage(content=state.get("user_input", "")))
    response = llm.invoke(messages)
    return {"messages": [response]}


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
    except Exception as e:
        return {"parsed_content": "", "error": str(e)}
    return {"parsed_content": "", "error": "未知的管理命令错误"}


def get_graph_node(state: AgentState) -> dict:
    """打开指定脉络图，展示图信息与全部节点。"""
    user_input = state.get("user_input", "").strip()
    graph_id = _strip_prefix(user_input, ("/open ", "打开 ", "查看脉络 ", "get graph "))
    try:
        return {"parsed_content": tool_get_graph.invoke({"graph_id": graph_id})}
    except Exception as e:
        return {"parsed_content": "", "error": str(e)}


def _extract_json_object(text: str) -> dict | None:
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*\n(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None


def summarize_memory_node(state: AgentState) -> dict:
    """把本次生成的脉络总结写入长期记忆 memory_snapshots。"""
    graph_id = state.get("current_graph_id", "")
    if not graph_id:
        return {}
    source = state.get("graph_markdown") or state.get("parsed_content", "")
    if not source:
        return {}
    prompt = MEMORY_SUMMARY_PROMPT.replace("{content}", source[:config.MAX_CONTENT_LENGTH])
    data = None
    try:
        llm = _get_llm()
        response = llm.invoke([HumanMessage(content=prompt)])
        text = response.content if hasattr(response, "content") else str(response)
        data = _extract_json_object(text)
    except Exception:
        pass
    if data and isinstance(data, dict) and data.get("summary"):
        summary = str(data["summary"]).strip()
        key_points = [str(k).strip() for k in data.get("key_points", []) if str(k).strip()]
    else:
        summary = (source.strip().splitlines() or ["脉络图摘要"])[0][:80]
        key_points = []
    snap_id = save_memory_snapshot(graph_id, summary, key_points)
    return {"memory_snapshot_id": snap_id}
