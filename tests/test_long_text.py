"""Long-text pipeline, upload safety, and preview tests."""

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.config import config
from app.memory import repository
from app.memory.database import init_db
from app.services.chunking import (
    chunk_content,
    classify_content,
    estimate_long_text,
)
from app.services.longtext import (
    _fallback_extract,
    create_book_subgraphs,
    map_reduce,
    prepare_book_payload,
)
from app.tools.web_fetcher import fetch_url
from app.web.server import app


class ChunkingTestCase(unittest.TestCase):
    def test_tier_and_chunking(self):
        small = "短文本" * 100
        medium = ("机器学习" * 3000)  # 15000 chars -> still S? threshold 30000, no.
        medium = ("机器学习与深度学习" * 8000)  # ~64000 chars
        self.assertEqual(classify_content(small), "S")
        self.assertEqual(classify_content(medium), "M")
        chunks = chunk_content(medium)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(
                len(chunk["text"]),
                config.SINGLE_LLM_CHUNK_LIMIT
                * (1 + config.CHUNK_OVERLAP_RATIO)
                + 200,
            )

    def test_estimate(self):
        estimate = estimate_long_text("a" * 120000)
        self.assertEqual(estimate["tier"], "M")
        self.assertGreater(estimate["blocks"], 1)
        self.assertGreater(estimate["estimated_tokens"], 0)


class LongTextPipelineTestCase(unittest.TestCase):
    def test_fallback_only_keeps_explicit_relations(self):
        concepts, relations = _fallback_extract(
            "## 主题\n概念A 是核心方法。\n概念B 依赖概念A。"
        )
        labels = {item["label"] for item in concepts}
        self.assertIn("概念A", labels)
        self.assertIn("概念B", labels)
        self.assertEqual(relations[0]["relation_type"], "depends_on")
        self.assertIn("依赖", relations[0]["evidence"])

    def test_map_reduce_fallback(self):
        content = "\n\n".join(
            f"## 主题 {i}\n概念A{i} 是核心方法。\n概念B{i} 依赖概念A{i}。"
            for i in range(200)
        )
        result = map_reduce(content)
        self.assertTrue(result["mermaid"].strip().startswith("graph TD"))
        self.assertTrue(result["markdown"])
        self.assertGreater(len(result["node_payloads"]), 0)
        self.assertGreater(len(result["chunks"]), 0)
        self.assertEqual(result["report"]["tier"], "M")


class BookPipelineTestCase(unittest.TestCase):
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

    def test_book_chapters_create_subgraphs(self):
        content = "\n\n".join(
            f"# 第 {i} 章\n" + "\n".join(
                f"概念{i}_{j} 是第 {i} 章的核心方法。"
                for j in range(1800)
            )
            for i in range(1, 6)
        )
        self.assertEqual(config.BOOK_TEXT_THRESHOLD, 150000)
        payload = prepare_book_payload(content)
        self.assertEqual(payload["report"]["tier"], "L")
        self.assertGreaterEqual(len(payload["chapter_payloads"]), 5)

        mother_id = repository.create_graph(title="母图", graph_type="markdown")
        subgraphs = create_book_subgraphs(mother_id, payload["chapter_payloads"])
        self.assertGreaterEqual(len(subgraphs), 5)
        first = repository.get_graph(subgraphs[0]["graph_id"])
        self.assertEqual(first["parent_graph_id"], mother_id)
        self.assertGreater(len(repository.get_nodes(subgraphs[0]["graph_id"])), 0)
        self.assertGreater(len(repository.list_content_chunks(subgraphs[0]["graph_id"])), 0)


class SafetyAndApiTestCase(unittest.TestCase):
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

    def test_parse_preview_and_internal_url_block(self):
        parsed = self.client.post(
            "/api/v1/graphs/parse",
            data={"text": "x" * 40000},
        )
        self.assertEqual(parsed.status_code, 200)
        self.assertEqual(parsed.json()["data"]["preview"]["tier"], "M")

        blocked = fetch_url("http://127.0.0.1:8000/admin")
        self.assertIn("内网", blocked["error"])
        blocked_api = self.client.post(
            "/api/v1/graphs/parse",
            data={"url": "http://localhost/secret"},
        )
        self.assertEqual(blocked_api.status_code, 400)

    def test_upload_magic_validation(self):
        response = self.client.post(
            "/api/v1/graphs/parse",
            files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("PDF", response.json()["error"])


if __name__ == "__main__":
    unittest.main()
