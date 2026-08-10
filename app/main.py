"""CLI 交互入口。"""

import json
import sys
from app.config import Config
from app.logging_config import setup_logging
from app.memory.database import init_db, get_checkpointer
from app.graph.builder import build_graph
from app.graph.state import build_initial_state


def print_banner():
    print("=" * 56)
    print("  学习脉络智能体 (Learning Context Agent)")
    print("  命令: 输入文本生成脉络 | list 列表 | search <关键词>")
    print("        回顾 <主题> 检索 | open <图ID> 查看脉络")
    print("        file:<路径> / url:<网址> | files: / urls: 批量")
    print("        添加节点 <图ID> <文本> | 更新节点 / 删除节点 / 关联节点")
    print("        /search on|off | /format mermaid|markdown|both")
    print("        /help 帮助 | /quit 退出")
    print("=" * 56)


def format_management_result(text: str) -> str:
    try:
        data = json.loads(text)
    except Exception:
        return text
    if isinstance(data, list):
        lines = [
            f"[{item.get('id')}] {item.get('title') or ''} "
            f"({item.get('graph_type') or 'auto'}) "
            f"来源: {item.get('source_type') or '-'} "
            f"更新: {item.get('updated_at') or '-'}"
            for item in data
        ]
        return "\n".join(lines) if lines else "暂无结果"
    if isinstance(data, dict):
        graph = data.get("graph") or {}
        nodes = data.get("nodes") or []
        lines = [
            f"脉络图: {graph.get('title') or ''} [{graph.get('id') or ''}]",
            f"类型: {graph.get('graph_type') or 'auto'} | "
            f"来源: {graph.get('source_type') or '-'}",
            f"描述: {graph.get('description') or '-'}",
        ]
        if graph.get("mermaid_code"):
            lines.append("\n--- Mermaid ---")
            lines.append(graph["mermaid_code"])
        if nodes:
            lines.append("\n--- 节点 ---")
            for node in nodes:
                parent = node.get("parent_id") or "根"
                related = node.get("related_nodes") or []
                rel_text = ", ".join(related) if related else "-"
                lines.append(
                    f"- [{node.get('id')}] {node.get('label')} "
                    f"(父: {parent} | 关联: {rel_text})"
                )
        return "\n".join(lines)
    return text


def run_cli():
    try:
        Config.validate()
    except ValueError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    init_db()
    print("[OK] 数据库初始化完成")
    setup_logging()

    checkpointer = get_checkpointer()
    graph = build_graph(checkpointer=checkpointer)
    print("[OK] Agent 图编译完成（ReAct 模式）\n")

    print_banner()

    thread_id = "default"
    web_search_enabled = False
    output_format = "both"
    config_ctx = {"configurable": {"thread_id": thread_id}}

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
            print("再见！")
            break
        if user_input.lower() in ("/help", "help", "帮助"):
            print_banner()
            continue
        if user_input.lower().startswith("/search "):
            arg = user_input[len("/search "):].strip().lower()
            if arg in ("on", "true", "1"):
                web_search_enabled = True
                print("[联网搜索已开启]")
            elif arg in ("off", "false", "0"):
                web_search_enabled = False
                print("[联网搜索已关闭]")
            else:
                print("用法: /search on | /search off")
            continue
        if user_input.lower().startswith("/format"):
            arg = user_input[len("/format"):].strip().lower()
            if arg in ("mermaid", "markdown", "both", "auto"):
                output_format = arg if arg != "auto" else "both"
                print(f"[输出格式已设置: {output_format}]")
            else:
                print("用法: /format mermaid | markdown | both")
            continue

        initial_state = build_initial_state(
            user_input,
            output_format=output_format,
            web_search_enabled=web_search_enabled,
        )

        result = graph.invoke(initial_state, config_ctx)

        error = result.get("error", "")
        if error:
            print(f"\n[错误] {error}")
            continue

        action = result.get("action", "")

        if action in ("list_graphs", "search_graphs", "get_graph", "manage_graph"):
            print(f"\n{format_management_result(result.get('parsed_content', '无结果'))}")
            continue

        mermaid = result.get("graph_mermaid", "")
        markdown = result.get("graph_markdown", "")
        graph_id = result.get("current_graph_id", "")

        if mermaid:
            print("\n--- Mermaid 脉络图 ---")
            print("```mermaid")
            print(mermaid)
            print("```")

        if markdown:
            print("\n--- Markdown 大纲 ---")
            print(markdown)

        if graph_id:
            print(f"\n[已保存] 脉络图 ID: {graph_id}")

        memory_id = result.get("memory_snapshot_id", "")
        if memory_id:
            print(f"[已记忆] 摘要 ID: {memory_id}")

        # ReAct 最终答复（聊天 / 生成总结 / 知识问答）
        messages = result.get("messages", [])
        if messages:
            last_msg = messages[-1]
            if hasattr(last_msg, "content"):
                content = last_msg.content
                if content:
                    print(f"\n{content}")
            else:
                print(f"\n{last_msg}")


if __name__ == "__main__":
    run_cli()
