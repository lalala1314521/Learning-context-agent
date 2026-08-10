"""WebUI API 冒烟测试（不依赖 LLM 网络）。"""

import os
import tempfile
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app.config import config
from app.memory import repository
from app.memory.database import init_db
from app.web.server import app


class WebApiTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._original_path = config.DATABASE_PATH
        config.DATABASE_PATH = self.db_path
        init_db()
        self.client = TestClient(app)

    def tearDown(self):
        config.DATABASE_PATH = self._original_path
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def test_health(self):
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_index_and_vendor_assets(self):
        index = self.client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertIn("学习脉络智能体", index.text)
        self.assertIn('data-page="galaxy"', index.text)
        galaxy_js = self.client.get("/static/js/components/galaxyPanel.js")
        self.assertEqual(galaxy_js.status_code, 200)
        self.assertIn("showGalaxy", galaxy_js.text)
        vendor = self.client.get("/static/vendor/mermaid.min.js")
        self.assertEqual(vendor.status_code, 200)
        self.assertGreater(len(vendor.content), 100000)

    def test_graphs_list_and_detail(self):
        graph_id = repository.create_graph(
            title="WebUI 测试",
            graph_type="markdown",
            markdown_outline="# 测试\n- 要点",
        )
        response = self.client.get("/api/v1/graphs")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data[0]["title"], "WebUI 测试")
        self.assertNotIn("mermaid_code", data[0])

        detail = self.client.get(f"/api/v1/graphs/{graph_id}")
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()["data"]
        self.assertEqual(payload["graph"]["id"], graph_id)
        self.assertEqual(len(payload["nodes"]), 2)

        missing = self.client.get("/api/v1/graphs/not-exist")
        self.assertEqual(missing.status_code, 404)
        self.assertFalse(missing.json()["ok"])

    def test_parse_text_and_upload(self):
        text_response = self.client.post(
            "/api/v1/graphs/parse",
            data={"text": "hello world"},
        )
        self.assertTrue(text_response.json()["ok"])
        self.assertEqual(text_response.json()["data"]["content"], "hello world")

        upload_response = self.client.post(
            "/api/v1/graphs/parse",
            files={"file": ("sample.txt", b"upload content", "text/plain")},
        )
        self.assertTrue(upload_response.json()["ok"])
        self.assertEqual(upload_response.json()["data"]["content"], "upload content")

    def test_generate_with_mocked_graph(self):
        fake_result = {
            "current_graph_id": "g1",
            "graph_mermaid": "graph TD\nA[x] --> B[y]",
            "graph_markdown": "# x\n- y",
            "memory_snapshot_id": "m1",
            "error": "",
        }
        fake_graph = mock.Mock()
        fake_graph.invoke.return_value = fake_result
        with mock.patch("app.web.routers.graphs.get_graph_runner", return_value=fake_graph):
            response = self.client.post(
                "/api/v1/graphs/generate",
                json={"content": "测试内容", "output_format": "both"},
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["id"], "g1")
        self.assertEqual(data["mermaid"], fake_result["graph_mermaid"])
        self.assertEqual(data["memory_snapshot_id"], "m1")

    def test_async_generation_job(self):
        fake_chunks = [
            {"tools": {
                "current_graph_id": "g2",
                "graph_mermaid": "graph TD\nA[x] --> B[y]",
                "graph_markdown": "# x\n- y",
                "long_text_report": {},
                "long_text_chapter_graph_ids": [],
                "intermediate_steps": [{"tool": "tool_generate_graph", "tool_input": {}, "observation": "ok"}],
            }},
            {"align_concepts": {"concept_report": {}}},
            {"persist_graph_memory": {"memory_snapshot_id": "m2"}},
        ]
        fake_graph = mock.Mock()
        fake_graph.stream.return_value = fake_chunks
        # 后台线程会异步读取 get_graph_runner，因此 mock 需覆盖整个轮询期
        with mock.patch("app.web.routers.graphs.get_graph_runner", return_value=fake_graph):
            started = self.client.post(
                "/api/v1/graphs/generate/async",
                json={"content": "异步内容", "output_format": "both"},
            )
            self.assertEqual(started.status_code, 200)
            job_id = started.json()["data"]["id"]
            data = None
            for _ in range(20):
                job = self.client.get(f"/api/v1/jobs/{job_id}").json()["data"]
                if job["status"] in ("done", "error"):
                    data = job
                    break
                time.sleep(0.05)
        self.assertIsNotNone(data)
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["result"]["id"], "g2")
        self.assertTrue(data["result"]["trace"])

    def test_node_crud_and_memories(self):
        graph_id = repository.create_graph(title="节点测试", graph_type="markdown")
        created = self.client.post(
            "/api/v1/nodes",
            json={"graph_id": graph_id, "label": "新节点"},
        )
        self.assertEqual(created.status_code, 200)
        node_id = created.json()["data"]["id"]

        updated = self.client.patch(
            f"/api/v1/nodes/{node_id}",
            json={"label": "改名节点", "related_nodes": []},
        )
        self.assertTrue(updated.json()["data"]["ok"])

        detail = self.client.get(f"/api/v1/graphs/{graph_id}")
        self.assertEqual(detail.json()["data"]["nodes"][0]["label"], "改名节点")

        repository.save_memory_snapshot(graph_id, "记忆摘要", ["关键点1"])
        memories = self.client.get("/api/v1/memories")
        self.assertEqual(memories.json()["data"][0]["key_points"], ["关键点1"])

        deleted = self.client.delete(f"/api/v1/nodes/{node_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/v1/graphs/{graph_id}").json()["data"]["nodes"],
            [],
        )

    def test_outline_tree(self):
        graph_id = repository.create_graph(title="大纲测试", graph_type="markdown")
        root = repository.add_node(graph_id, "根", created_by="agent")
        child = repository.add_node(graph_id, "子", parent_id=root, created_by="agent")
        response = self.client.get(f"/api/v1/graphs/{graph_id}/outline")
        self.assertEqual(response.status_code, 200)
        tree = response.json()["data"]
        self.assertEqual(tree[0]["label"], "根")
        self.assertEqual(tree[0]["children"][0]["label"], "子")

    def test_links_crud(self):
        graph_a = repository.create_graph(title="图A", graph_type="markdown")
        graph_b = repository.create_graph(title="图B", graph_type="markdown")
        node_a = repository.add_node(graph_a, "监督学习")
        node_b = repository.add_node(graph_b, "监督学习")
        created = self.client.post(
            "/api/v1/links",
            json={
                "from_graph_id": graph_a,
                "from_node_id": node_a,
                "to_graph_id": graph_b,
                "to_node_id": node_b,
                "relation_type": "related",
            },
        )
        self.assertEqual(created.status_code, 200)
        link_id = created.json()["data"]["id"]
        links = self.client.get(f"/api/v1/links?graph_id={graph_a}").json()["data"]
        self.assertEqual(len(links), 1)
        deleted = self.client.delete(f"/api/v1/links/{link_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/v1/links?graph_id={graph_a}").json()["data"],
            [],
        )

    def test_quiz_and_review(self):
        graph_id = repository.create_graph(title="复习测试", graph_type="markdown")
        node_id = repository.add_node(graph_id, "过拟合")
        quiz = self.client.post(
            "/api/v1/quiz",
            json={
                "graph_id": graph_id,
                "node_id": node_id,
                "question": "什么是过拟合？",
                "answer": "模型在训练集上表现好但在新数据上差",
            },
        )
        self.assertEqual(quiz.status_code, 200)
        quiz_id = quiz.json()["data"]["id"]

        queue = self.client.get("/api/v1/review").json()["data"]
        self.assertEqual(queue["items"][0]["quiz_id"], quiz_id)
        review_id = queue["items"][0]["id"]

        submitted = self.client.post(f"/api/v1/review/{review_id}", json={"rating": 2})
        self.assertEqual(submitted.status_code, 200)
        stats = self.client.get("/api/v1/review").json()["data"]["stats"]
        self.assertGreaterEqual(stats["total"], 1)

    def test_hydrate_old_graph_nodes(self):
        graph_id = repository.create_graph(
            title="旧图",
            graph_type="mermaid_tree",
            mermaid_code="graph TD\nA[机器学习] --> B[监督学习]",
            markdown_outline="# 机器学习\n- 监督学习",
        )
        self.assertEqual(repository.get_nodes(graph_id), [])
        detail = self.client.get(f"/api/v1/graphs/{graph_id}")
        self.assertEqual(len(detail.json()["data"]["nodes"]), 2)
        outline = self.client.get(f"/api/v1/graphs/{graph_id}/outline")
        self.assertEqual(len(outline.json()["data"]), 1)

    def test_ask_knowledge(self):
        graph_id = repository.create_graph(title="机器学习", graph_type="markdown")
        node_id = repository.add_node(graph_id, "监督学习", note="使用带标签数据训练")
        repository.save_memory_snapshot(graph_id, "机器学习记忆", ["监督学习"])
        # mock LLM 与联网兜底，避免真实网络/模型调用
        with mock.patch(
            "app.services.knowledge.ask_llm",
            return_value="已收录知识：监督学习。知识库未直接覆盖：强化学习。",
        ), mock.patch(
            "app.services.knowledge._web_retrieval",
            return_value=([], []),
        ):
            response = self.client.post(
                "/api/v1/ask",
                json={"question": "什么是监督学习？", "use_database": True},
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("已收录知识", data["answer"])
        self.assertTrue(data["has_sources"])
        self.assertIn(node_id, [source["id"] for source in data["sources"]])


if __name__ == "__main__":
    unittest.main()
