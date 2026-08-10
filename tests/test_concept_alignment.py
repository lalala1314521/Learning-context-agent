"""Concept layer tests for embedding, alignment, and API surface."""

import json
import os
import pathlib
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.config import config
from app.memory import repository
from app.memory.database import init_db
from app.memory.embeddings import cosine_similarity, embed_text
from app.services.concept_alignment import align_graph_nodes
from app.web.server import app


class ConceptDbTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._original_path = config.DATABASE_PATH
        self._original_llm = config.CONCEPT_LLM_DISAMBIGUATION
        config.DATABASE_PATH = self.db_path
        config.CONCEPT_LLM_DISAMBIGUATION = False
        init_db()

    def tearDown(self):
        config.DATABASE_PATH = self._original_path
        config.CONCEPT_LLM_DISAMBIGUATION = self._original_llm
        try:
            os.remove(self.db_path)
        except OSError:
            pass


class EmbeddingTestCase(unittest.TestCase):
    def test_embedding_is_deterministic_and_normalized(self):
        a = embed_text("梯度下降")
        b = embed_text("梯度下降")
        c = embed_text("反向传播")
        self.assertEqual(a, b)
        self.assertGreater(cosine_similarity(a, b), cosine_similarity(a, c))
        self.assertAlmostEqual(sum(v * v for v in a), 1.0, places=5)


class ConceptAlignmentTestCase(ConceptDbTestCase):
    def test_duplicate_labels_align_to_same_concept(self):
        graph_a = repository.create_graph(title="笔记A", graph_type="markdown")
        repository.add_node(graph_a, "梯度下降", note="沿负梯度方向更新参数")
        repository.add_node(graph_a, "损失函数", note="衡量预测与真实值的差距")
        graph_b = repository.create_graph(title="笔记B", graph_type="markdown")
        repository.add_node(graph_b, "梯度下降", note="迭代更新模型参数")
        repository.add_node(graph_b, "交叉熵损失", note="分类任务常用的损失")

        first = align_graph_nodes(graph_a)
        second = align_graph_nodes(graph_b)

        self.assertEqual(first.aligned, 2)
        self.assertEqual(second.aligned, 2)
        nodes_a = {n["label"]: n for n in repository.get_nodes(graph_a)}
        nodes_b = {n["label"]: n for n in repository.get_nodes(graph_b)}
        self.assertEqual(
            nodes_a["梯度下降"]["concept_id"],
            nodes_b["梯度下降"]["concept_id"],
        )
        concept = repository.get_concept(nodes_a["梯度下降"]["concept_id"])
        self.assertEqual(concept["mention_count"], 2)
        self.assertGreater(len(second.new_links), 0)

    def test_alias_alignment(self):
        concept_id = repository.create_concept("梯度下降", summary="优化算法")
        repository.add_concept_alias(concept_id, "GD")
        graph = repository.create_graph(title="笔记", graph_type="markdown")
        repository.add_node(graph, "GD", note="Gradient Descent")

        result = align_graph_nodes(graph)
        self.assertEqual(result.aligned, 1)
        self.assertEqual(repository.get_nodes(graph)[0]["concept_id"], concept_id)

    def test_api_concept_surface_and_merge(self):
        graph = repository.create_graph(title="API概念", graph_type="markdown")
        repository.add_node(graph, "过拟合", note="训练好测试差")
        repository.add_node(graph, "正则化", note="抑制过拟合")
        align_graph_nodes(graph)

        client = TestClient(app)
        concepts = client.get("/api/v1/concepts").json()["data"]
        self.assertEqual(len(concepts), 2)
        concept_id = concepts[0]["id"]
        detail = client.get(f"/api/v1/concepts/{concept_id}").json()["data"]
        self.assertGreaterEqual(len(detail["mentions"]), 1)

        loser = concepts[1]["id"]
        merged = client.post(
            "/api/v1/concepts/merge",
            json={"winner_id": concept_id, "loser_id": loser},
        )
        self.assertEqual(merged.status_code, 200)
        remaining = client.get("/api/v1/concepts").json()["data"]
        self.assertEqual(len(remaining), 1)

    def test_galaxy_and_knowledge_path(self):
        graph_a = repository.create_graph(title="笔记A", graph_type="markdown")
        repository.add_node(graph_a, "梯度下降", note="沿负梯度方向更新参数")
        repository.add_node(graph_a, "损失函数", note="衡量预测与真实值的差距")
        graph_b = repository.create_graph(title="笔记B", graph_type="markdown")
        repository.add_node(graph_b, "梯度下降", note="迭代更新模型参数")
        repository.add_node(graph_b, "交叉熵损失", note="分类任务常用的损失")
        align_graph_nodes(graph_a)
        align_graph_nodes(graph_b)

        client = TestClient(app)
        galaxy = client.get("/api/v1/galaxy").json()["data"]
        self.assertGreaterEqual(len(galaxy["concepts"]), 3)
        self.assertGreater(len(galaxy["links"]), 0)
        self.assertGreater(len(galaxy["domains"]), 0)

        labels = {c["id"]: c["canonical_label"] for c in galaxy["concepts"]}
        start = next(cid for cid, label in labels.items() if label == "损失函数")
        end = next(cid for cid, label in labels.items() if label == "交叉熵损失")
        path = client.get(
            f"/api/v1/concepts/{start}/path/{end}"
        ).json()["data"]
        self.assertGreaterEqual(len(path["path"]), 2)
        self.assertTrue(path["explanation"])

    def test_delete_concept_and_link(self):
        graph_a = repository.create_graph(title="删除A", graph_type="markdown")
        repository.add_node(graph_a, "梯度下降", note="优化算法")
        repository.add_node(graph_a, "损失函数", note="衡量误差")
        graph_b = repository.create_graph(title="删除B", graph_type="markdown")
        repository.add_node(graph_b, "梯度下降", note="迭代更新")
        repository.add_node(graph_b, "交叉熵损失", note="分类损失")
        align_graph_nodes(graph_a)
        align_graph_nodes(graph_b)

        client = TestClient(app)
        links = client.get("/api/v1/concept-links").json()["data"]
        self.assertGreater(len(links), 0)
        link_id = links[0]["id"]
        deleted_link = client.delete(f"/api/v1/concept-links/{link_id}")
        self.assertEqual(deleted_link.status_code, 200)
        remaining = client.get("/api/v1/concept-links").json()["data"]
        self.assertNotIn(link_id, [item["id"] for item in remaining])

        concept_id = client.get("/api/v1/concepts").json()["data"][0]["id"]
        deleted_concept = client.delete(f"/api/v1/concepts/{concept_id}")
        self.assertEqual(deleted_concept.status_code, 200)
        concepts = client.get("/api/v1/concepts").json()["data"]
        self.assertNotIn(concept_id, [item["id"] for item in concepts])

    def test_golden_set_shape(self):
        path = pathlib.Path(__file__).parent / "fixtures" / "disambiguation_golden.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["merge_pairs"]), 50)
        self.assertEqual(len(data["split_pairs"]), 50)
        for pair in data["merge_pairs"] + data["split_pairs"]:
            self.assertTrue(pair["a"].strip())
            self.assertTrue(pair["b"].strip())


if __name__ == "__main__":
    unittest.main()
