"""Phase 5 tests: learning path, weekly report, input sources, export."""

import os
import pathlib
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.config import config
from app.memory import repository
from app.memory.database import init_db
from app.services.concept_alignment import align_graph_nodes
from app.tools.doc_parser import parse_document
from app.web.server import app


class Phase5TestCase(unittest.TestCase):
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

    def test_learning_path_and_reports(self):
        graph_id = repository.create_graph(title="学习路径", graph_type="markdown")
        node_a = repository.add_node(graph_id, "线性代数", note="向量与矩阵")
        node_b = repository.add_node(graph_id, "机器学习", note="从数据学习")
        align_graph_nodes(graph_id)
        concepts = repository.list_concepts()
        by_label = {c["canonical_label"]: c for c in concepts}
        repository.create_concept_link(
            by_label["线性代数"]["id"],
            by_label["机器学习"]["id"],
            relation_type="depends",
            confidence=0.9,
            source="user",
            status="confirmed",
        )

        path = self.client.get(
            "/api/v1/learning-path",
            params={"target": "机器学习"},
        ).json()["data"]
        self.assertGreaterEqual(len(path["path"]), 2)
        self.assertEqual(path["target"]["canonical_label"], "机器学习")

        report = self.client.get("/api/v1/weekly-report").json()["data"]
        self.assertGreaterEqual(report["total_concepts"], 2)
        achievements = self.client.get("/api/v1/achievements").json()["data"]
        self.assertGreaterEqual(len(achievements), 1)

    def test_vault_import_and_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = pathlib.Path(tmp)
            (vault / "note.md").write_text(
                "# 注意力机制\n- 自注意力\n- 位置编码",
                encoding="utf-8",
            )
            result = self.client.post(
                "/api/v1/sources/import-vault",
                json={"path": tmp},
            ).json()["data"]
            self.assertEqual(result["imported"], 1)

        subtitle = "1\n00:00:00,000 --> 00:00:02,000\nHello world\n2\n..."
        path = pathlib.Path(tempfile.gettempdir()) / "captions.srt"
        path.write_text(subtitle, encoding="utf-8")
        try:
            parsed = parse_document(str(path))
            self.assertIn("Hello world", parsed["content"])
            self.assertNotIn("-->", parsed["content"])
        finally:
            path.unlink(missing_ok=True)

    def test_anki_export(self):
        response = self.client.get("/api/v1/export/anki.apkg")
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 0)
        self.assertIn("apkg", response.headers.get("content-disposition", ""))


if __name__ == "__main__":
    unittest.main()
