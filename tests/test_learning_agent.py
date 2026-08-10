"""Learning Context Agent 冒烟测试（不依赖网络 / LLM）。"""

import os
import pathlib
import tempfile
import unittest
from unittest import mock

from app.config import config
from app.graph.builder import build_graph
from app.graph.mermaid_parser import parse_graph_structure
from app.graph.state import build_initial_state
from app.memory.database import init_db
from app.memory import repository
from langchain_core.messages import AIMessage


class TempDbTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._original_path = config.DATABASE_PATH
        config.DATABASE_PATH = self.db_path
        init_db()

    def tearDown(self):
        config.DATABASE_PATH = self._original_path
        try:
            os.remove(self.db_path)
        except OSError:
            pass


class ParserTestCase(unittest.TestCase):
    def test_flowchart_parse(self):
        flow = """graph TD
A[机器学习] --> B[监督学习]
A --> C[无监督学习]
B --> D[分类]
B --- E[回归]
"""
        nodes = parse_graph_structure(flow, "")
        by_label = {n["label"]: n for n in nodes}
        self.assertEqual(len(nodes), 5)
        self.assertEqual(by_label["分类"]["parent_id"], by_label["监督学习"]["id"])
        self.assertIn(by_label["回归"]["id"], by_label["监督学习"]["related_nodes"])
        self.assertIn(by_label["监督学习"]["id"], by_label["回归"]["related_nodes"])

    def test_mindmap_parse(self):
        mindmap = """mindmap
  root[深度学习]
    监督
      分类
    无监督
      聚类
"""
        nodes = parse_graph_structure(mindmap, "")
        by_label = {n["label"]: n for n in nodes}
        self.assertEqual(len(nodes), 5)
        self.assertEqual(by_label["分类"]["parent_id"], by_label["监督"]["id"])
        self.assertEqual(by_label["聚类"]["parent_id"], by_label["无监督"]["id"])

    def test_markdown_parse(self):
        md = """# 机器学习
- 监督学习
  - 分类
## 无监督学习
- 聚类
"""
        nodes = parse_graph_structure("", md)
        by_label = {n["label"]: n for n in nodes}
        self.assertEqual(len(nodes), 5)
        self.assertEqual(by_label["分类"]["parent_id"], by_label["监督学习"]["id"])
        self.assertEqual(by_label["聚类"]["parent_id"], by_label["无监督学习"]["id"])


class RepositoryTestCase(TempDbTestCase):
    def test_crud_and_search(self):
        graph_id = repository.create_graph(
            title="机器学习", graph_type="mermaid_tree",
            markdown_outline="# 机器学习\n- 监督学习",
            raw_content="监督学习与无监督学习",
        )
        node_a = repository.add_node(graph_id, "监督学习", node_id="n1")
        node_b = repository.add_node(
            graph_id, "分类", parent_id=node_a,
            related_nodes=["n1"], node_id="n2",
        )
        self.assertEqual(node_a, "n1")
        self.assertEqual(node_b, "n2")

        nodes = repository.get_nodes(graph_id)
        self.assertEqual(len(nodes), 2)
        by_id = {n["id"]: n for n in nodes}
        self.assertEqual(by_id["n2"]["related_nodes"], ["n1"])

        hits = repository.search_graphs("无监督学习")
        self.assertEqual(hits[0]["id"], graph_id)

        self.assertTrue(repository.update_node("n2", label="新分类"))
        self.assertEqual(repository.get_nodes(graph_id)[1]["label"], "新分类")

        self.assertTrue(repository.delete_node("n2"))
        self.assertEqual(len(repository.get_nodes(graph_id)), 1)


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """按序返回固定文本的生成 LLM（用于确定性生成 / 结构化输出）。"""

    def __init__(self, contents):
        self._contents = list(contents)

    def invoke(self, messages):
        return _FakeResponse(self._contents.pop(0))


class _FakeReActLLM:
    """ReAct 循环用 LLM：bind_tools 返回自身；invoke 按序返回 AIMessage。"""

    def __init__(self, steps):
        self._steps = list(steps)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return self._steps.pop(0)


def _tool_call_message(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "name": name,
        "args": args,
        "id": call_id,
        "type": "tool_call",
    }])


class GraphFlowTestCase(TempDbTestCase):
    """ReAct 自由文本生成流程：agent 调用 tool_generate_graph → 工具桥接确定性管线。"""

    def test_structured_node_payloads(self):
        generate_output = """【Mermaid】:
```mermaid
graph TD
A[机器学习] --> B[监督学习]
```
【Markdown大纲】:
# 机器学习
- 监督学习
【节点数据】:
```json
[
  {"id": "A", "label": "机器学习", "note": "从数据中学习规律的学科", "node_type": "concept", "parent_id": "", "related_nodes": []},
  {"id": "B", "label": "监督学习", "note": "使用带标签数据训练", "node_type": "method", "parent_id": "A", "related_nodes": []}
]
```
"""
        fake_agent = _FakeReActLLM([
            _tool_call_message("tool_generate_graph", {
                "content": "机器学习", "output_format": "both",
            }),
            AIMessage(content="已生成脉络图。"),
        ])
        fake_gen = _FakeLLM([
            generate_output,
            '{"summary": "机器学习摘要", "key_points": ["监督学习"]}',
        ])
        graph = build_graph()
        with mock.patch("app.graph.agent.get_llm", return_value=fake_agent), \
                mock.patch("app.services.llm.get_llm", return_value=fake_gen), \
                mock.patch("app.services.graph_generation.get_llm", return_value=fake_gen), \
                mock.patch("app.graph.nodes._llm_intent", return_value=""):
            result = graph.invoke(
                build_initial_state("机器学习"),
                {"configurable": {"thread_id": "payload-test"}},
            )
        self.assertFalse(result.get("error"))
        nodes = repository.get_nodes(result["current_graph_id"])
        by_label = {n["label"]: n for n in nodes}
        self.assertEqual(by_label["机器学习"]["note"], "从数据中学习规律的学科")
        self.assertEqual(by_label["机器学习"]["node_type"], "concept")
        self.assertEqual(by_label["监督学习"]["note"], "使用带标签数据训练")
        self.assertEqual(by_label["监督学习"]["node_type"], "method")
        self.assertEqual(
            by_label["监督学习"]["parent_id"],
            by_label["机器学习"]["id"],
        )
        # ReAct 轨迹已记录
        self.assertTrue(result["intermediate_steps"])
        self.assertEqual(result["intermediate_steps"][0]["tool"], "tool_generate_graph")

    def test_generate_save_nodes_and_memory(self):
        generate_output = """【图表类型】: graph TD
【Mermaid】:
```mermaid
graph TD
A[机器学习] --> B[监督学习]
A --> C[无监督学习]
B --- D[关联概念]
```
【Markdown大纲】:
# 机器学习
- 监督学习
  - 关联概念
【节点数据】:
```json
[
  {"id": "A", "label": "机器学习", "note": "让计算机从数据中学习的学科", "node_type": "concept", "parent_id": "", "related_nodes": []},
  {"id": "B", "label": "监督学习", "note": "使用带标签数据训练", "node_type": "method", "parent_id": "A", "related_nodes": []},
  {"id": "C", "label": "无监督学习", "note": "使用无标签数据发现结构", "node_type": "method", "parent_id": "A", "related_nodes": []},
  {"id": "D", "label": "关联概念", "note": "与监督学习相关的概念", "node_type": "concept", "parent_id": "B", "related_nodes": ["B"]}
]
```
"""
        fake_agent = _FakeReActLLM([
            _tool_call_message("tool_generate_graph", {
                "content": "请生成机器学习脉络", "output_format": "both",
            }),
            AIMessage(content="脉络图已保存。"),
        ])
        fake_gen = _FakeLLM([
            generate_output,
            '{"summary": "机器学习脉络摘要", "key_points": ["监督学习", "无监督学习"]}',
        ])
        graph = build_graph()
        with mock.patch("app.graph.agent.get_llm", return_value=fake_agent), \
                mock.patch("app.services.llm.get_llm", return_value=fake_gen), \
                mock.patch("app.services.graph_generation.get_llm", return_value=fake_gen), \
                mock.patch("app.graph.nodes._llm_intent", return_value=""):
            result = graph.invoke(
                build_initial_state("请生成机器学习脉络"),
                {"configurable": {"thread_id": "flow-test"}},
            )

        self.assertFalse(result.get("error"))
        graph_id = result["current_graph_id"]
        self.assertTrue(graph_id)
        self.assertTrue(result["memory_snapshot_id"])
        nodes = repository.get_nodes(graph_id)
        by_label = {n["label"]: n for n in nodes}
        self.assertEqual(len(nodes), 4)
        self.assertEqual(by_label["关联概念"]["related_nodes"], [by_label["监督学习"]["id"]])

        stored = repository.get_graph(graph_id)
        self.assertTrue(stored["mermaid_code"].lower().startswith("graph td"))

    def test_node_id_collision_between_graphs(self):
        """LLM 节点短 id（A/B）跨图冲突时，仍应正确保存节点并重映射引用。"""
        from app.services.graph_generation import save_generated_graph

        payloads = ('[{"id": "A", "label": "机器学习", "note": "note1", '
                    '"node_type": "concept", "parent_id": "", "related_nodes": []}, '
                    '{"id": "B", "label": "监督学习", "note": "note2", '
                    '"node_type": "method", "parent_id": "A", "related_nodes": ["A"]}]')
        # 先造一张已占用 id=A / B 的旧图
        g0 = repository.create_graph(title="旧图", graph_type="markdown")
        repository.add_node(g0, "旧机器学习", node_id="A")
        repository.add_node(g0, "旧监督学习", node_id="B")

        result = save_generated_graph(
            content="内容",
            input_type="text",
            source_name="",
            graph_mermaid="graph TD\nA[机器学习] --> B[监督学习]",
            graph_markdown="# 机器学习\n- 监督学习",
            node_payloads=payloads,
            long_text_tier="S",
            long_text_chunks=[],
            chapter_payloads=[],
        )
        self.assertFalse(result.get("error"))
        nodes = repository.get_nodes(result["current_graph_id"])
        self.assertEqual(len(nodes), 2)
        by_label = {n["label"]: n for n in nodes}
        self.assertNotIn(by_label["机器学习"]["id"], ("A", "B"))  # 已重映射唯一 id
        self.assertEqual(by_label["监督学习"]["parent_id"], by_label["机器学习"]["id"])
        self.assertEqual(
            by_label["监督学习"]["related_nodes"],
            [by_label["机器学习"]["id"]],
        )
        self.assertEqual(by_label["机器学习"]["note"], "note1")

    def test_manage_and_open_flow(self):
        graph_id = repository.create_graph(title="测试脉络", graph_type="markdown")
        graph = build_graph()
        result = graph.invoke(
            build_initial_state(f"添加节点 {graph_id} 新知识点"),
            {"configurable": {"thread_id": "manage-test"}},
        )
        self.assertEqual(result["action"], "manage_graph")
        self.assertIn("已添加节点", result["parsed_content"])

        nodes = repository.get_nodes(graph_id)
        self.assertEqual(len(nodes), 1)
        node_id = nodes[0]["id"]

        result = graph.invoke(
            build_initial_state(f"更新节点 {node_id} 修改后的知识点"),
            {"configurable": {"thread_id": "manage-test"}},
        )
        self.assertIn("更新成功", result["parsed_content"])

        result = graph.invoke(
            build_initial_state(f"打开 {graph_id}"),
            {"configurable": {"thread_id": "open-test"}},
        )
        self.assertEqual(result["action"], "get_graph")
        self.assertIn("修改后的知识点", result["parsed_content"])

    def test_output_format_filter(self):
        generate_output = """【图表类型】: mindmap
【Mermaid】:
```mermaid
mindmap
  root[深度学习]
    监督学习
```
【Markdown大纲】:
# 深度学习
- 监督学习
【节点数据】:
```json
[
  {"id": "root", "label": "深度学习", "note": "深度神经网络学习的统称", "node_type": "concept", "parent_id": "", "related_nodes": []},
  {"id": "A", "label": "监督学习", "note": "依赖标注数据的范式", "node_type": "method", "parent_id": "root", "related_nodes": []}
]
```
"""
        fake_agent = _FakeReActLLM([
            _tool_call_message("tool_generate_graph", {
                "content": "只要 Mermaid", "output_format": "mermaid",
            }),
            AIMessage(content="已生成 Mermaid 脉络图。"),
        ])
        fake_gen = _FakeLLM([
            generate_output,
            '{"summary": "深度学习摘要", "key_points": ["监督学习"]}',
        ])
        graph = build_graph()
        with mock.patch("app.graph.agent.get_llm", return_value=fake_agent), \
                mock.patch("app.services.llm.get_llm", return_value=fake_gen), \
                mock.patch("app.services.graph_generation.get_llm", return_value=fake_gen), \
                mock.patch("app.graph.nodes._llm_intent", return_value=""):
            result = graph.invoke(
                build_initial_state("只要 Mermaid", output_format="mermaid"),
                {"configurable": {"thread_id": "format-test"}},
            )
        self.assertTrue(result["graph_mermaid"])
        self.assertEqual(result["graph_markdown"], "")
        stored = repository.get_graph(result["current_graph_id"])
        self.assertFalse(stored["markdown_outline"])

    def test_batch_files_flow(self):
        fd1, path1 = tempfile.mkstemp(suffix=".txt")
        os.close(fd1)
        fd2, path2 = tempfile.mkstemp(suffix=".txt")
        os.close(fd2)
        pathlib.Path(path1).write_text("监督学习内容", encoding="utf-8")
        pathlib.Path(path2).write_text("无监督学习内容", encoding="utf-8")
        self.addCleanup(os.remove, path1)
        self.addCleanup(os.remove, path2)

        fake_gen = _FakeLLM([
            "【Mermaid】:\n```mermaid\ngraph TD\nA[内容]\n```\n【Markdown大纲】:\n# 内容\n- 要点\n【节点数据】:\n```json\n[{\"id\": \"A\", \"label\": \"内容\", \"note\": \"批量文件的核心内容\", \"node_type\": \"concept\", \"parent_id\": \"\", \"related_nodes\": []}]\n```\n",
            '{"summary": "批量文件摘要", "key_points": ["监督学习"]}',
        ])
        graph = build_graph()
        with mock.patch("app.services.llm.get_llm", return_value=fake_gen), \
                mock.patch("app.services.graph_generation.get_llm", return_value=fake_gen):
            result = graph.invoke(
                build_initial_state(f"files:{path1};{path2}"),
                {"configurable": {"thread_id": "batch-test"}},
            )
        self.assertFalse(result.get("error"))
        self.assertEqual(result["parsed_content"].count("### 文件:"), 2)
        stored = repository.get_graph(result["current_graph_id"])
        self.assertIn("监督学习内容", stored["raw_content"])
        self.assertIn("无监督学习内容", stored["raw_content"])

    def test_review_search_flow(self):
        repository.create_graph(
            title="线性代数", graph_type="markdown",
            markdown_outline="# 线性代数\n- 矩阵",
        )
        graph = build_graph()
        result = graph.invoke(
            build_initial_state("回顾 线性代数"),
            {"configurable": {"thread_id": "review-test"}},
        )
        self.assertEqual(result["action"], "search_graphs")
        self.assertIn("线性代数", result["parsed_content"])


if __name__ == "__main__":
    unittest.main()
