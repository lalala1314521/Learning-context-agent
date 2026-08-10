"""Agent 轨迹事件构建：把 graph.stream 的节点状态更新转换为可实时展示的事件。

事件类型：
- thought：Agent 的思考 / 中间答复
- action：Agent 决定调用某个工具（工具名 + 入参）
- tool：工具执行结果（观察）
- post：确定性后处理节点（对齐 / 记忆 / 保存等）
"""

import json

from app.services.llm import estimate_tokens


def _trim(text: str, limit: int = 400) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def build_trace_events(node_name: str, update: dict) -> list[dict]:
    """根据节点名与状态更新生成轨迹事件列表。"""
    events: list[dict] = []

    if node_name == "agent":
        messages = update.get("messages") or []
        for msg in messages:
            if type(msg).__name__ != "AIMessage":
                continue
            content = (getattr(msg, "content", "") or "").strip()
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                for tc in tool_calls:
                    args = tc.get("args") or {}
                    events.append({
                        "type": "action",
                        "text": f"调用工具：{tc.get('name')}",
                        "detail": _trim(json.dumps(args, ensure_ascii=False), 400),
                        "tokens": estimate_tokens(json.dumps(args, ensure_ascii=False)),
                    })
            elif content:
                events.append({
                    "type": "thought",
                    "text": _trim(content, 600),
                    "detail": "",
                    "tokens": estimate_tokens(content),
                })
        thought = update.get("thought") or ""
        if thought and not events:
            events.append({
                "type": "thought",
                "text": _trim(thought, 600),
                "detail": "",
                "tokens": estimate_tokens(thought),
            })

    elif node_name == "tools":
        for step in update.get("intermediate_steps") or []:
            observation = str(step.get("observation") or "")
            events.append({
                "type": "tool",
                "text": f"工具执行：{step.get('tool')}",
                "detail": _trim(f"输入: {json.dumps(step.get('tool_input', {}), ensure_ascii=False)}\n结果: {observation}", 500),
                "tokens": estimate_tokens(observation),
            })

    elif node_name == "parse_content":
        events.append({"type": "post", "text": "内容解析完成", "detail": "", "tokens": 0})
    elif node_name == "web_search":
        info = update.get("supplementary_info") or ""
        events.append({
            "type": "post",
            "text": "联网搜索补充上下文",
            "detail": _trim(info, 200),
            "tokens": 0,
        })
    elif node_name == "generate_graph":
        events.append({"type": "post", "text": "脉络图内容生成中", "detail": "", "tokens": 0})
    elif node_name == "save_graph":
        gid = update.get("current_graph_id") or ""
        if gid:
            events.append({
                "type": "post",
                "text": f"脉络图已保存：{gid}",
                "detail": "",
                "tokens": 0,
            })
    elif node_name == "align_concepts":
        report = update.get("concept_report") or {}
        n = report.get("aligned_mentions") or 0
        events.append({
            "type": "post",
            "text": f"概念对齐：{n} 个提及已归位全局概念层",
            "detail": "",
            "tokens": 0,
        })
    elif node_name == "persist_graph_memory":
        events.append({"type": "post", "text": "记忆持久化：写入长期摘要", "detail": "", "tokens": 0})

    return events
