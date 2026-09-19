"""ReAct 循环节点：LLM 自主决策 → 工具执行 → 观察，LangGraph 原生回边。

混合架构：
- ReAct 循环（agent ↔ tools）处理自由文本的交互决策；
- 循环结束后按需进入确定性后处理管线（align_concepts → persist_graph_memory）。
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.config import config
from app.graph.state import AgentState
from app.logging_config import get_logger
from app.memory.repository import get_graph
from app.prompts.system import SYSTEM_PROMPT
from app.services.llm import _extract_json_object, get_llm, invoke_safe, invoke_structured
from app.tools.knowledge_graph import ALL_TOOLS

logger = get_logger("graph.agent")

# 循环内保留在上下文中的最近消息数（更早的历史在 prepare 阶段压缩为摘要）
TRIM_KEEP = 12
# 会创建脉络图并落库的工具：其观察结果用于填充 current_graph_id 等状态字段
_GRAPH_CREATING_TOOLS = {"tool_generate_graph", "tool_create_graph"}

_CONVERSATION_SUMMARY_PROMPT = (
    "请把下面的多轮学习对话压缩成一段中文摘要（200 字以内），"
    "保留用户关心的主题、已生成的脉络、已确认的偏好。只输出 JSON："
    '{{"summary": "..."}}。\n\n对话内容：\n{messages}'
)


def _condense_history(history: list, llm=None) -> str:
    """把旧轮次消息压缩为摘要；LLM 不可用时截断降级。"""
    if not history:
        return ""
    lines = []
    for msg in history:
        content = getattr(msg, "content", "") or ""
        if isinstance(content, str) and content.strip():
            lines.append(content[:300])
    text = "\n".join(lines)
    if config.DEEPSEEK_API_KEY:
        data = invoke_structured(
            _CONVERSATION_SUMMARY_PROMPT.format(messages=text[:6000]),
            llm=llm,
            retries=0,
        )
        if data and data.get("summary"):
            return f"（早期对话摘要）{str(data['summary']).strip()}"
    # 降级：保留开头与结尾的关键信息
    head = text[:800]
    return f"（早期对话内容截断）{head}"


def prepare_conversation_node(state: AgentState) -> dict:
    """图入口：把当前 user_input 以 HumanMessage 入 messages（仅一次）。

    历史消息超过阈值时，把 TRIM_KEEP 之外的旧轮次压缩为 conversation_context。
    """
    updates: dict = {"thought": ""}
    user_input = state.get("user_input")
    if user_input:
        updates["messages"] = [HumanMessage(content=user_input)]
    past = list(state.get("messages") or [])
    if len(past) > TRIM_KEEP:
        old, summary = past[:-TRIM_KEEP], None
        try:
            summary = _condense_history(old)
        except Exception as exc:
            logger.warning("对话摘要生成失败: %s", exc)
        if summary:
            updates["conversation_context"] = summary
    return updates


def agent_node(state: AgentState) -> dict:
    """ReAct 思考节点：LLM 结合工具描述决定下一步行动。"""
    # 循环上限守卫：超过最大工具调用次数则强制结束
    if len(state.get("intermediate_steps") or []) >= config.REACT_MAX_ITERATIONS:
        stop_msg = AIMessage(
            content="已达最大工具调用次数，请简化请求后重试，或直接问我其他问题。"
        )
        return {"messages": [stop_msg], "thought": stop_msg.content}

    user_input = state.get("user_input") or ""

    # 用户开启联网搜索：首个决策确定性触发 tool_web_search，保证搜索一定发生。
    # 无论 router 判为生成还是问答，只要勾选即触发（文件/URL 走确定性 web_search_node）。
    if (state.get("web_search_enabled")
            and not state.get("intermediate_steps")
            and state.get("action") in ("generate_graph", "chat")):
        logger.info("web search forced by toggle")
        return {
            "messages": [AIMessage(content="", tool_calls=[{
                "name": "tool_web_search",
                "args": {"query": user_input[:200]},
                "id": "auto-web-search",
                "type": "tool_call",
            }])],
            "thought": "用户已开启联网搜索，先补充与主题相关的背景信息。",
        }

    # 大内容确定性快捷路径：无需 LLM 决策，直接进入生成管线，
    # 避免把超大正文塞进 Agent 上下文造成超限（已在必要时先完成联网搜索）。
    if (not state.get("current_graph_id")
            and len(user_input) > config.SINGLE_LLM_CHUNK_LIMIT
            and state.get("action") != "chat"):
        logger.info(
            "large content shortcut: bypass agent decision (~%d chars)",
            len(user_input),
        )
        return {
            "messages": [AIMessage(content="", tool_calls=[{
                "name": "tool_generate_graph",
                "args": {
                    "content": user_input,
                    "output_format": state.get("output_format", "both"),
                },
                "id": "auto-large-content",
                "type": "tool_call",
            }])],
            "thought": "内容较长，直接调用生成工具。",
        }

    system = SYSTEM_PROMPT
    if state.get("web_search_enabled"):
        system += (
            "\n\n## 联网搜索要求\n用户已开启联网搜索，联网结果已提供。"
            "请结合搜索到的背景信息作答或生成脉络图。"
        )
    ctx = state.get("conversation_context") or ""
    if ctx:
        system = f"{system}\n\n## 历史对话摘要（更早的轮次）\n{ctx}"

    messages = [SystemMessage(content=system)]
    tail = list(state.get("messages") or [])[-TRIM_KEEP:]
    messages.extend(tail)

    llm = get_llm()
    try:
        bound = llm.bind_tools(ALL_TOOLS)
        response = invoke_safe(bound, messages, context="react_agent")
    except Exception as exc:
        logger.exception("Agent LLM 调用失败: %s", exc)
        response = AIMessage(content=f"（抱歉，调用模型失败：{exc}）")

    thought = response.content if hasattr(response, "content") else str(response)
    return {"messages": [response], "thought": thought}


def _extract_graph_updates(observation: str, tool_name: str) -> dict:
    """从生成类工具的观察结果中提取状态字段。"""
    try:
        if tool_name == "tool_generate_graph":
            data = _extract_json_object(observation)
            if not data or not data.get("graph_id"):
                return {}
            return {
                "current_graph_id": str(data["graph_id"]),
                "graph_mermaid": str(data.get("graph_mermaid") or ""),
                "graph_markdown": str(data.get("graph_markdown") or ""),
                "long_text_report": data.get("long_text_report") or {},
                "long_text_tier": str(data.get("long_text_tier") or ""),
                "long_text_chapter_graph_ids": list(
                    data.get("long_text_chapter_graph_ids") or []
                ),
            }
        if tool_name == "tool_create_graph":
            graph_id = (observation or "").strip()
            if not graph_id or len(graph_id) != 12:
                return {}
            graph = get_graph(graph_id)
            if not graph:
                return {}
            return {
                "current_graph_id": graph_id,
                "graph_mermaid": graph.get("mermaid_code") or "",
                "graph_markdown": graph.get("markdown_outline") or "",
            }
    except Exception as exc:
        logger.warning("解析脉络图工具结果失败: %s", exc)
    return {}


def tools_node(state: AgentState) -> dict:
    """ReAct 行动节点：执行最后一条 AIMessage 中的全部工具调用并收集观察。"""
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or not getattr(last, "tool_calls", None):
        return {}

    tool_map = {t.name: t for t in ALL_TOOLS}
    outputs: list[ToolMessage] = []
    steps: list[dict] = []
    graph_updates: dict = {}
    updates: dict = {}
    supplementary = state.get("supplementary_info") or ""

    for tc in last.tool_calls:
        name = tc.get("name") or tc["name"]
        args = dict(tc.get("args") or {})
        fn = tool_map.get(name)
        if fn is None:
            observation = f"未知工具: {name}"
            logger.warning("Agent 调用了未知工具 %s", name)
        else:
            if name == "tool_generate_graph":
                args.setdefault("learning_goal", state.get("learning_goal") or "理解主线")
                args.setdefault("generation_depth", state.get("generation_depth") or "standard")
            # 生成脉络时把已搜集的联网结果并入生成内容，避免搜索结果被丢弃
            if name == "tool_generate_graph" and supplementary:
                content = str(args.get("content") or "")
                args["content"] = f"{content}\n\n## 联网搜索结果\n{supplementary}"
            try:
                observation = str(fn.invoke(args))
            except Exception as exc:
                logger.exception("工具 %s 执行失败: %s", name, exc)
                observation = f"工具执行失败: {exc}"
        outputs.append(ToolMessage(content=observation, tool_call_id=tc["id"]))
        steps.append({
            "tool": name,
            "tool_input": args,
            "observation": observation[:2000],
        })
        if name == "tool_web_search":
            supplementary = observation
            updates["supplementary_info"] = supplementary
        if name in _GRAPH_CREATING_TOOLS:
            graph_updates.update(_extract_graph_updates(observation, name))

    logger.info(
        "tools_node executed %d tool(s), graph_updates=%s",
        len(outputs), bool(graph_updates),
    )
    return {
        "messages": outputs,
        "intermediate_steps": steps,
        **graph_updates,
        **updates,
    }


def should_continue(state: AgentState) -> str:
    """ReAct 循环条件：有 tool_calls 继续走 tools；否则有图则对齐，无则结束。"""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tools"
    if state.get("current_graph_id"):
        return "align_concepts"
    return "end"
