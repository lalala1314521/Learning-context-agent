"""Multi-mode review sessions and daily review brief."""

import random
import re
import uuid
from datetime import date, datetime

from app.memory import repository
from app.services.llm import invoke_structured

_sessions: dict[str, dict] = {}
_MODES = ("flashcard", "graph_recall", "matching", "feynman", "socratic", "cross_doc")


def submit_review(review_id: str, rating: int) -> bool:
    """提交一次复习：FSRS 调度 + 更新进度 + 写入历史（编排在 service 层）。"""
    from datetime import datetime

    from app.services.fsrs import schedule_review

    row = repository.get_review(review_id)
    if not row:
        return False
    now = datetime.now()
    scheduled = schedule_review(
        {
            "repetitions": row["repetitions"],
            "interval_days": row["interval_days"],
            "ease_factor": row["ease_factor"],
            "difficulty": row["difficulty"],
            "stability": row["stability"],
            "last_reviewed_at": row["last_reviewed_at"],
            "lapses": row["lapses"] if "lapses" in row else 0,
        },
        rating,
        now=now,
    )
    repository.update_review_state(review_id, scheduled)
    if row["concept_id"]:
        repository.add_review_history(row["concept_id"], review_id, rating, scheduled)
    return True


def create_review_session(
    mode: str | None = None,
    count: int = 8,
    graph_id: str | None = None,
    llm=None,
) -> dict:
    mode = mode if mode in _MODES else None
    due = repository.get_due_review(limit=max(count, 20))
    if not due:
        due = _due_from_concepts(count)
    if mode is None:
        seed = (due[0].get("id") or "session") if due else "session"
        mode = _MODES[sum(ord(c) for c in seed) % len(_MODES)]

    items = _build_items(mode, due, count, graph_id, llm=llm)
    if not items:
        items = _build_items("flashcard", due, count, graph_id, llm=llm)
    session_id = uuid.uuid4().hex[:12]
    session = {
        "id": session_id,
        "mode": mode,
        "created_at": datetime.now().isoformat(),
        "items": items,
    }
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> dict | None:
    session = _sessions.get(session_id)
    return session


def submit_session_item(
    session_id: str,
    item_id: str,
    response: dict,
) -> dict:
    session = _sessions.get(session_id)
    if not session:
        raise ValueError("复习会话不存在")
    item = next((i for i in session["items"] if i["id"] == item_id), None)
    if not item:
        raise ValueError("复习题不存在")
    item["answered"] = True
    item["response"] = response
    feedback = _grade(item, response)
    if item.get("review_id") and response.get("rating") is not None:
        submit_review(item["review_id"], int(response["rating"]))
    return {
        "item_id": item_id,
        "feedback": feedback,
        "answer": item.get("answer"),
        "next": _next_item(session, item_id),
    }


def _due_from_concepts(count: int) -> list[dict]:
    concepts = repository.list_concepts(limit=count)
    items = []
    for concept in concepts:
        mentions = repository.list_concept_mentions(concept["id"], limit=1)
        if mentions:
            mention = mentions[0]
            items.append({
                "id": concept["id"],
                "concept_id": concept["id"],
                "concept_label": concept["canonical_label"],
                "graph_id": mention["graph_id"],
                "graph_title": mention["graph_title"],
                "node_id": mention["node_id"],
                "question": f"请用自己的话解释「{concept['canonical_label']}」，并说明它与一个相关概念的联系。",
                "answer": concept.get("summary") or f"围绕「{concept['canonical_label']}」说明定义、作用、条件和关系。",
            })
    return items


def _build_items(
    mode: str,
    due: list[dict],
    count: int,
    graph_id: str | None,
    llm=None,
) -> list[dict]:
    if mode == "graph_recall":
        return _graph_recall_items(graph_id, count)
    if mode == "matching":
        return _matching_items(count)
    if mode == "feynman":
        return _feynman_items(due, count)
    if mode == "socratic":
        return _socratic_items(due, count, llm=llm)
    if mode == "cross_doc":
        return _cross_doc_items(count, llm=llm)
    return _flashcard_items(due, count)


def _flashcard_items(due: list[dict], count: int) -> list[dict]:
    items = []
    for item in due[:count]:
        items.append({
            "id": uuid.uuid4().hex[:12],
            "type": "flashcard",
            "prompt": item.get("question") or f"请解释「{item.get('node_label') or item.get('concept_label')}」解决的问题，并举出一个相关关系。",
            "answer": item.get("answer") or "",
            "concept_id": item.get("concept_id"),
            "graph_id": item.get("graph_id"),
            "node_id": item.get("node_id"),
            "concept_label": item.get("concept_label") or item.get("node_label"),
            "meta": {
                "graph_title": item.get("graph_title"),
                "node_label": item.get("node_label"),
                "concept_id": item.get("concept_id"),
                "graph_id": item.get("graph_id"),
                "node_id": item.get("node_id"),
            },
            "review_id": item.get("id"),
        })
    return items


def _graph_recall_items(graph_id: str | None, count: int) -> list[dict]:
    graphs = repository.list_graphs(limit=100)
    selected = [g for g in graphs if graph_id is None or g["id"] == graph_id]
    random.shuffle(selected)
    items = []
    for graph in selected[:max(1, count)]:
        nodes = repository.get_nodes(graph["id"])
        if len(nodes) < 4:
            continue
        blank_count = max(1, round(len(nodes) * 0.3))
        blanks = random.sample(nodes, blank_count)
        visible = [
            {
                "id": n["id"],
                "label": n["label"],
                "blanked": n["id"] in {b["id"] for b in blanks},
            }
            for n in nodes
        ]
        items.append({
            "id": uuid.uuid4().hex[:12],
            "type": "graph_recall",
            "prompt": f"回忆并补全《{graph['title']}》中被遮罩的节点",
            "graph": {
                "id": graph["id"],
                "title": graph["title"],
                "nodes": visible,
            },
            "answer": {b["id"]: b["label"] for b in blanks},
        })
        if len(items) >= count:
            break
    return items


def _matching_items(count: int) -> list[dict]:
    concepts = repository.list_concepts(limit=count * 2)
    random.shuffle(concepts)
    pairs = []
    for concept in concepts[:count]:
        summary = concept.get("summary") or concept.get("canonical_label")
        pairs.append({
            "left": concept["canonical_label"],
            "right": summary[:60],
        })
    if not pairs:
        return []
    return [{
        "id": uuid.uuid4().hex[:12],
        "type": "matching",
        "prompt": "把左列概念与右列解释/例子正确连线",
        "pairs": pairs,
        "answer": {p["left"]: p["right"] for p in pairs},
    }]


def _feynman_items(due: list[dict], count: int) -> list[dict]:
    items = []
    for item in due[:count]:
        if not item.get("concept_id"):
            continue
        concept = repository.get_concept(item["concept_id"])
        if not concept:
            continue
        items.append({
            "id": uuid.uuid4().hex[:12],
            "type": "feynman",
            "prompt": f"用你自己的话讲清楚「{concept['canonical_label']}」",
            "concept": concept["canonical_label"],
            "concept_id": concept["id"],
            "graph_id": item.get("graph_id"),
            "node_id": item.get("node_id"),
            "concept_label": concept["canonical_label"],
            "graph_title": item.get("graph_title"),
            "answer": concept.get("summary") or "",
            "meta": {
                "concept_id": concept["id"],
                "graph_id": item.get("graph_id"),
                "node_id": item.get("node_id"),
                "graph_title": item.get("graph_title"),
            },
            "review_id": item.get("id"),
        })
    return items


def _socratic_items(due: list[dict], count: int, llm=None) -> list[dict]:
    items = []
    for item in due[:count]:
        if not item.get("concept_id"):
            continue
        concept = repository.get_concept(item["concept_id"])
        if not concept:
            continue
        neighbors = [
            link for link in repository.list_concept_links_for_concept(concept["id"])
        ][:3]
        neighbor_text = ", ".join({
            link["from_label"] if link["from_concept"] != concept["id"] else link["to_label"]
            for link in neighbors
        })
        if neighbor_text:
            prompt = (
                f"「{concept['canonical_label']}」和「{neighbor_text}」有什么关系？"
                "请给出你的推理，然后等待追问。"
            )
        else:
            prompt = f"请解释「{concept['canonical_label']}」的核心含义，并给出一个例子。"
        items.append({
            "id": uuid.uuid4().hex[:12],
            "type": "socratic",
            "prompt": prompt,
            "concept": concept["canonical_label"],
            "concept_id": concept["id"],
            "graph_id": item.get("graph_id"),
            "node_id": item.get("node_id"),
            "concept_label": concept["canonical_label"],
            "graph_title": item.get("graph_title"),
            "neighbors": neighbor_text,
            "answer": concept.get("summary") or "",
            "meta": {
                "concept_id": concept["id"],
                "graph_id": item.get("graph_id"),
                "node_id": item.get("node_id"),
                "graph_title": item.get("graph_title"),
            },
        })
    return items


def _cross_doc_items(count: int, llm=None) -> list[dict]:
    links = repository.list_concept_links(limit=200, min_confidence=0.5)
    items = []
    for link in links[:count]:
        items.append({
            "id": uuid.uuid4().hex[:12],
            "type": "cross_doc",
            "prompt": (
                f"你已学过「{link['from_label']}」，也学过「{link['to_label']}」。"
                f"请解释两者之间「{link['relation_type']}」的关系，并给出一个应用场景。"
            ),
            "answer": link.get("evidence") or f"{link['from_label']} 与 {link['to_label']} 通过关系边关联",
            "meta": {
                "from_concept": link["from_concept"],
                "to_concept": link["to_concept"],
            },
        })
    return items


def _grade(item: dict, response: dict) -> str:
    if item["type"] == "graph_recall":
        answers = item.get("answer") or {}
        submitted = response.get("answers") or {}
        correct = sum(
            1 for key, value in answers.items()
            if str(submitted.get(key) or "").strip() == str(value).strip()
        )
        return f"图回忆：答对 {correct}/{len(answers)} 个节点"
    if item["type"] == "matching":
        pairs = item.get("pairs") or []
        submitted = response.get("pairs") or {}
        correct = sum(
            1 for pair in pairs
            if str(submitted.get(pair["left"]) or "").strip()
            == str(pair["right"] or "").strip()
        )
        return f"连线题：答对 {correct}/{len(pairs)} 对"
    answer = str(item.get("answer") or "")
    text = str(response.get("text") or "")
    if not text:
        rating = response.get("rating")
        labels = {0: "忘记", 1: "困难", 2: "模糊", 3: "掌握"}
        return f"已记录：{labels.get(rating, '未评分')}"
    def terms(value: str) -> set[str]:
        words = set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", value))
        compact = re.sub(r"\s+", "", value)
        words.update(compact[index:index + 2] for index in range(max(0, len(compact) - 1)))
        return {word.lower() for word in words if len(word.strip()) > 0}
    answer_terms, response_terms = terms(answer), terms(text)
    negation = re.compile(r"(不|未|无|并非|不会|不能|不是|否)")
    if bool(negation.search(answer)) != bool(negation.search(text)) and answer and text:
        return "回答提到了相同概念，但否定/肯定方向与参考答案不一致，请重新核对原文依据。"
    overlap = len(answer_terms & response_terms)
    total = max(1, len(answer_terms))
    coverage = round(overlap / total * 100)
    if coverage >= 55:
        return f"回答已覆盖主要概念（约 {coverage}%），可以再补充一个条件或例子。"
    if coverage >= 25:
        return f"回答抓到了部分线索（约 {coverage}%），建议回到证据段补充关系和适用条件。"
    return "回答与材料的关键关系还不够接近，建议先写出定义、作用和一个证据。"


def _next_item(session: dict, item_id: str) -> str | None:
    ids = [item["id"] for item in session["items"]]
    try:
        index = ids.index(item_id)
    except ValueError:
        return None
    return ids[index + 1] if index + 1 < len(ids) else None


def daily_brief(llm=None) -> dict:
    due = repository.get_due_review(limit=100)
    concepts = []
    seen = set()
    for item in due:
        label = item.get("concept_label") or item.get("node_label") or ""
        concept_id = item.get("concept_id")
        if label and concept_id not in seen:
            seen.add(concept_id)
            concepts.append({
                "id": concept_id,
                "label": label,
                "graph_title": item.get("graph_title"),
                "due_at": item.get("due_at"),
            })
    narrative = _narrative(concepts, llm=llm)
    return {
        "date": date.today().isoformat(),
        "due_count": len(due),
        "concepts": concepts[:20],
        "narrative": narrative,
        "weak_areas": repository.list_domains(),
    }


def _narrative(concepts: list[dict], llm=None) -> str:
    if not concepts:
        return "今天没有到期概念，可以打开星图探索已有知识连接。"
    labels = [c["label"] for c in concepts[:8]]
    if llm is not None:
        data = invoke_structured(
            "请把下面的复习概念写成 3-5 句连贯的今日知识简报导语。"
            f"概念：{'、'.join(labels)}",
            llm=llm,
            retries=1,
        )
        if data and data.get("narrative"):
            return str(data["narrative"])
    return (
        f"早上好，今天有 {len(concepts)} 个概念到期。"
        f"它们包括：{'、'.join(labels)}。"
        "建议沿着概念边从基础概念开始复习，再迁移到跨文档综合题。"
    )
