"""FSRS scheduling, multi-mode review sessions, and daily brief tests."""

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.config import config
from app.memory import repository
from app.memory.database import init_db
from app.services.concept_alignment import align_graph_nodes
from app.web.server import app


class ReviewModesTestCase(unittest.TestCase):
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

    def _seed_review(self):
        graph_id = repository.create_graph(title="复习概念", graph_type="markdown")
        node_id = repository.add_node(graph_id, "过拟合", note="训练好测试差")
        align_graph_nodes(graph_id)
        quiz_id = repository.add_quiz_question(
            graph_id, node_id, "什么是过拟合？", "训练好测试差",
        )
        return repository.ensure_review(graph_id, node_id, quiz_id)

    def test_fsrs_review_and_history(self):
        review_id = self._seed_review()
        before = repository.get_due_review(limit=10)
        self.assertEqual(before[0]["id"], review_id)
        graph_id = before[0]["graph_id"]
        self.assertTrue(repository.submit_review(review_id, 3))

        rows = repository.get_due_review(limit=10)
        self.assertNotIn(review_id, [row["id"] for row in rows])
        node = repository.get_nodes(graph_id)[0]
        concept_id = node["concept_id"]
        history = repository.list_review_history(concept_id)
        self.assertGreaterEqual(len(history), 1)
        mastery = repository.get_concept_mastery()
        self.assertGreaterEqual(mastery[concept_id]["retrievability"], 0)

    def test_session_and_brief_api(self):
        self._seed_review()
        brief = self.client.get("/api/v1/review/brief").json()["data"]
        self.assertGreaterEqual(brief["due_count"], 1)
        self.assertTrue(brief["narrative"])

        session = self.client.post(
            "/api/v1/review/session",
            json={"mode": "flashcard", "count": 3},
        ).json()["data"]
        self.assertEqual(session["mode"], "flashcard")
        item = session["items"][0]
        answer = self.client.post(
            f"/api/v1/review/session/{session['id']}/answer",
            json={"response": {"item_id": item["id"], "rating": 3}},
        ).json()["data"]
        self.assertTrue(answer["feedback"])

    def test_all_modes_build(self):
        self._seed_review()
        for mode in (
            "flashcard", "graph_recall", "matching",
            "feynman", "socratic", "cross_doc",
        ):
            session = self.client.post(
                "/api/v1/review/session",
                json={"mode": mode, "count": 2},
            ).json()["data"]
            self.assertTrue(session["items"])


if __name__ == "__main__":
    unittest.main()
